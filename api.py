import asyncio
import contextlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

SERVICE_DESCRIPTOR_PATH = Path(os.getenv("SERVICE_DESCRIPTOR_PATH", "./service.json")).resolve()
SERVICE_HELP_PATH = Path(os.getenv("SERVICE_HELP_PATH", "./help/index.md")).resolve()
SERVICE_HELP_FALLBACK_PATH = Path(os.getenv("SERVICE_HELP_FALLBACK_PATH", "./README.md")).resolve()
SERVICE_ID_OVERRIDE = os.getenv("SERVICE_ID")
SERVICE_NAME_OVERRIDE = os.getenv("SERVICE_NAME")
SERVICE_ADAPTER_OVERRIDE = os.getenv("SERVICE_ADAPTER")
SERVICE_LOCAL_URL_OVERRIDE = os.getenv("SERVICE_LOCAL_URL")

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Fetched output isn't deleted on read (consumer retries could hit a 404), so a sweep is the
# only cleanup - anything older than this is assumed abandoned (fetched already or never claimed).
OUTPUT_MAX_AGE_SECONDS = int(os.getenv("OUTPUT_MAX_AGE_SECONDS", str(60 * 60)))
OUTPUT_CLEANUP_INTERVAL_SECONDS = int(os.getenv("OUTPUT_CLEANUP_INTERVAL_SECONDS", str(5 * 60)))

MODEL_NAME = os.getenv("GLINER_MODEL", "fastino/gliner2.5-multi-v1")
DEVICE = os.getenv("DEVICE", "cpu")  # "cpu", "cuda", or "mps"
REQUEST_READ_CHUNK_SIZE = int(os.getenv("REQUEST_READ_CHUNK_SIZE", str(1024 * 1024)))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("md-gliner2")


def log_event(level: str, event: str, **fields):
    record = {"event": event, **fields}
    line = json.dumps(record, default=str)
    getattr(logger, level, logger.info)(line)


def apply_service_descriptor_overrides(descriptor: Dict[str, Any]) -> Dict[str, Any]:
    overrides = {
        "id": SERVICE_ID_OVERRIDE,
        "name": SERVICE_NAME_OVERRIDE,
        "adapter": SERVICE_ADAPTER_OVERRIDE,
        "local_url": SERVICE_LOCAL_URL_OVERRIDE,
    }
    for key, value in overrides.items():
        if isinstance(value, str) and value.strip():
            descriptor[key] = value.strip()
    return descriptor


def load_service_descriptor() -> Dict[str, Any]:
    try:
        with SERVICE_DESCRIPTOR_PATH.open("r", encoding="utf-8") as handle:
            descriptor = json.load(handle)
    except FileNotFoundError as err:
        raise RuntimeError(f"Descriptor file not found: {SERVICE_DESCRIPTOR_PATH}") from err
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Descriptor file is not valid JSON: {err}") from err
    except Exception as err:
        raise RuntimeError(f"Could not load service descriptor: {err}") from err

    if not isinstance(descriptor, dict):
        raise RuntimeError("Descriptor root must be a JSON object")

    return apply_service_descriptor_overrides(descriptor)


def load_help_markdown() -> str:
    for candidate in (SERVICE_HELP_PATH, SERVICE_HELP_FALLBACK_PATH):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise RuntimeError("Help markdown file not found")


# Lazily loaded so /health and /config work without pulling in torch/gliner2 on startup.
_model = None
# Inference runs in the thread pool, so two first requests could otherwise load the model twice.
_model_lock = threading.Lock()


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            from gliner2 import AutoExtractor
            log_event("info", "model_load_start", model=MODEL_NAME, device=DEVICE)
            _model = AutoExtractor.from_pretrained(MODEL_NAME, map_location=DEVICE)
            log_event("info", "model_load_done", model=MODEL_NAME, device=DEVICE)
    return _model


def parse_label_list(raw: Any) -> List[str]:
    if isinstance(raw, list):
        items = raw
    else:
        items = str(raw or "").split(",")
    return [item.strip() for item in items if item.strip()]


# UI's tag picker (MessyDesk tags.md §8) sends labels as a list of {label, description} objects
# when the user picked existing tags instead of typing a free-form comma list. Task-specific: only
# classify_text supports this (service.json's "display": "tagpicker") — extract_entities does not,
# since NER can't sensibly restrict/link its per-mention output to a fixed existing-tag set.
# GLiNER2's classification() accepts a plain label list OR a {label: description} dict (better
# zero-shot accuracy), so preserve descriptions through to the model when present.
def parse_label_entries(raw: Any) -> Union[List[str], Dict[str, str]]:
    if isinstance(raw, dict):
        return {str(k).strip(): str(v or "").strip() for k, v in raw.items() if str(k).strip()}
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        descriptions: Dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("name") or "").strip()
            if not label:
                continue
            descriptions[label] = str(item.get("description") or "").strip()
        if any(descriptions.values()):
            return descriptions
        return list(descriptions.keys())
    return parse_label_list(raw)


def parse_bool_param(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


# Word count above which we chunk via the model's _long() variants instead of
# running full attention over the whole document (avoids huge OOM allocations).
CHUNK_SIZE = int(os.getenv("GLINER_CHUNK_SIZE", "384"))
CHUNK_OVERLAP = int(os.getenv("GLINER_CHUNK_OVERLAP", "64"))


def is_long_text(text: str) -> bool:
    return len(text.split()) > CHUNK_SIZE


def parse_request_payload(raw: bytes) -> Dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as err:
        raise HTTPException(400, "Invalid JSON payload") from err
    if not isinstance(payload, dict):
        raise HTTPException(400, "Request payload must be a JSON object")
    return payload


def run_extract_entities(text: str, params: Dict[str, Any]) -> Dict[str, Any]:
    labels = parse_label_list(params.get("labels"))
    if not labels:
        raise HTTPException(400, "No entity labels provided")
    model = get_model()
    if is_long_text(text):
        return model.extract_entities_long(
            text, labels, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
            include_confidence=True, include_spans=True,
        )
    return model.extract_entities(text, labels, include_confidence=True, include_spans=True)


# Adapter owns the JSON-format problem (see MessyDesk tags.md \u00a71): convert GLiNER2's own
# {"entities": {label: [{text, start, end, confidence}, ...]}} shape into the canonical
# ner.json region shape MessyDesk expects, so core never needs to understand model-specific JSON.
def entities_to_regions(result: Dict[str, Any]) -> Dict[str, Any]:
    rois: Dict[str, Any] = {}
    seen_spans: Dict[str, int] = {}
    for label, hits in (result.get("entities") or {}).items():
        for hit in hits or []:
            start = hit.get("start")
            end = hit.get("end")
            span_key = f"{start}_{end}"
            seen_spans[span_key] = seen_spans.get(span_key, 0) + 1
            region_id = f"roi_{span_key}_{seen_spans[span_key]}"
            rois[region_id] = {
                "id": region_id,
                "type": "text",
                "start": start,
                "end": end,
                "text": hit.get("text"),
                "label": label,
                "confidence": hit.get("confidence"),
            }
    return {"rois": rois}



def run_classify_text(text: str, params: Dict[str, Any]) -> Dict[str, Any]:
    labels = parse_label_entries(params.get("labels"))
    if not labels:
        raise HTTPException(400, "No categories provided")
    multi_label = parse_bool_param(params.get("multi_label"))
    model = get_model()
    if multi_label:
        schema = {"category": {"labels": labels, "multi_label": True}}
    else:
        schema = {"category": labels}
    if is_long_text(text):
        return model.classify_text_long(text, schema, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    return model.classify_text(text, schema)


def run_extract_data(text: str, params: Dict[str, Any]) -> Dict[str, Any]:
    fields = parse_label_list(params.get("fields"))
    if not fields:
        raise HTTPException(400, "No fields provided")
    model = get_model()
    schema = model.create_schema().structure("data")
    for field in fields:
        schema = schema.field(field, dtype="str", cardinality="optional")
    if is_long_text(text):
        return model.extract_long(text, schema, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    return model.extract(text, schema)


TASK_HANDLERS = {
    "extract_entities": run_extract_entities,
    "classify_text": run_classify_text,
    "extract_data": run_extract_data,
}


def cleanup_stale_output(max_age_seconds: int) -> None:
    cutoff = time.time() - max_age_seconds
    try:
        entries = list(OUTPUT_DIR.iterdir())
    except FileNotFoundError:
        return
    for entry in entries:
        try:
            if not entry.is_dir() or entry.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            log_event("info", "output_cleanup_removed", dir=str(entry))
        except FileNotFoundError:
            continue
        except Exception as err:
            log_event("warning", "output_cleanup_failed", dir=str(entry), error=str(err))


async def output_cleanup_loop():
    while True:
        await asyncio.sleep(OUTPUT_CLEANUP_INTERVAL_SECONDS)
        cleanup_stale_output(OUTPUT_MAX_AGE_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_stale_output(OUTPUT_MAX_AGE_SECONDS)  # clear anything left over from a previous run
    task = asyncio.create_task(output_cleanup_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(
    title="GLiNER2 API",
    description="Zero-shot entity extraction, text classification, and structured data extraction",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory=str(OUTPUT_DIR)), name="files")


@app.get("/")
async def root():
    return {"message": "GLiNER2 API for MessyDesk"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "md-gliner2"}


@app.get("/config")
async def config():
    try:
        return load_service_descriptor()
    except RuntimeError as err:
        raise HTTPException(500, str(err))


@app.get("/help", response_class=PlainTextResponse)
async def help_markdown():
    try:
        return load_help_markdown()
    except RuntimeError as err:
        raise HTTPException(404, str(err))


@app.post("/process")
async def process(
    message: UploadFile = File(...),
    content: UploadFile = File(...),
):
    try:
        message_chunks = []
        while True:
            chunk = await message.read(REQUEST_READ_CHUNK_SIZE)
            if not chunk:
                break
            message_chunks.append(chunk)
        request_json = parse_request_payload(b"".join(message_chunks))

        text = (await content.read()).decode("utf-8", errors="replace")

        task = request_json.get("task", {}) if isinstance(request_json.get("task"), dict) else {}
        task_id = task.get("id")
        task_params = task.get("params", {}) if isinstance(task.get("params"), dict) else {}

        handler = TASK_HANDLERS.get(task_id)
        if handler is None:
            raise HTTPException(400, f"Unsupported task: {task_id}")

        log_event("info", "process_start", task=task_id)
        # Inference is CPU-bound - run it off the event loop so /health and /files stay responsive.
        result = await run_in_threadpool(handler, text, task_params)

        output_id = uuid.uuid4().hex
        output_dir = OUTPUT_DIR / output_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # extract_entities produces spans, so it maps to a ner.json region file (double
        # extension so MessyDesk's generic file intake detects the "ner.json" type); other
        # tasks (classification, structured extraction) stay as plain result JSON.
        if task_id == "extract_entities":
            output_path = output_dir / "gliner.ner.json"
            with output_path.open("w", encoding="utf-8") as handle:
                json.dump(entities_to_regions(result), handle, ensure_ascii=False, indent=2)
        else:
            output_path = output_dir / "gliner.json"
            with output_path.open("w", encoding="utf-8") as handle:
                json.dump({"task": task_id, "params": task_params, "result": result}, handle, ensure_ascii=False, indent=2)

        log_event("info", "process_done", task=task_id, output=str(output_path))
        return {"response": {"uri": f"/files/{output_id}/{output_path.name}"}}
    except HTTPException:
        raise
    except Exception as err:
        log_event("error", "process_failed", error=str(err))
        raise HTTPException(500, f"Processing failed: {str(err)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "9010")))
