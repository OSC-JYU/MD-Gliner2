"""extract_entities (with Create tags), extract_data (fields.json) and the output types, with a
fake model; test_real_model runs the baked-in model when the image has it."""

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEXT = "Invoice 2024-117 from Oy Saha Ab, Helsinki, dated 12 March 1921. Paid to Johan Virtanen. Helsinki office."


class FakeSchema:
    def __init__(self):
        self.fields = []

    def structure(self, name):
        return self

    def field(self, name, **_):
        self.fields.append(name)
        return self


class FakeModel:
    def create_schema(self):
        return FakeSchema()

    def extract(self, text, schema, **options):
        assert options == {"include_confidence": True, "include_spans": True}
        return {"data": [{"invoice_number": {"text": "2024-117", "confidence": 0.98, "start": 8, "end": 16}, "payee": None}]}

    def extract_entities(self, text, labels, **_):
        return {"entities": {
            "location": [{"text": "Helsinki", "confidence": 0.9, "start": 34, "end": 42},
                         {"text": "Helsinki", "confidence": 0.7, "start": 91, "end": 99}],
            "person": [{"text": "Johan  Virtanen", "confidence": 0.99, "start": 74, "end": 88}],
        }}


@pytest.fixture()
def md(tmp_path, monkeypatch):
    (tmp_path / "data/messydesk/projects/p1").mkdir(parents=True)
    (tmp_path / "data/messydesk/projects/p1/letter.txt").write_text(TEXT, encoding="utf-8")
    monkeypatch.setenv("MD_PATH", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    import md_storage

    importlib.reload(md_storage)
    import api

    importlib.reload(api)
    monkeypatch.setattr(api, "get_model", lambda: FakeModel())
    return tmp_path, api


def run(md, task, params):
    import asyncio
    import io

    from fastapi import UploadFile

    root, api = md
    message = {"task": {"id": task, "params": params},
               "file": {"@rid": "#80:1", "label": "letter.txt", "path": "data/messydesk/projects/p1/letter.txt"}}
    response = asyncio.run(api.process(UploadFile(filename="m.json", file=io.BytesIO(json.dumps(message).encode())), None))
    entry = response["response"]["files"][0]
    return entry, json.loads((root / "data/messydesk/tmp" / entry["path"]).read_text(encoding="utf-8"))


def test_extract_data_writes_fields_json(md):
    entry, out = run(md, "extract_data", {"fields": "invoice_number, payee"})
    assert (entry["label"], entry["type"], entry["extension"]) == ("letter.txt.json", "fields.json", "json")
    assert out["format"] == "messydesk-fields/1" and out["fields"] == ["invoice_number", "payee"]
    assert out["records"] == [{"invoice_number": {"text": "2024-117", "confidence": 0.98, "start": 8, "end": 16}, "payee": None}]
    assert out["source"] == {"rid": "#80:1", "label": "letter.txt"}


def test_entities_without_tags(md):
    entry, out = run(md, "extract_entities", {"labels": "person, location"})
    assert entry["type"] == "ner.json"
    assert len(out["rois"]) == 3 and "file_tags" not in out


def test_create_tags_tags_the_text_with_each_entity_once(md):
    _, out = run(md, "extract_entities", {"labels": "person, location", "autotag": True})
    assert out["file_tags"] == {"#80:1": [
        {"label": "Johan Virtanen", "confidence": 0.99},
        {"label": "Helsinki", "confidence": 0.9},
    ]}


@pytest.mark.skipif(not os.environ.get("HF_HUB_OFFLINE"), reason="needs the model baked into the image")
def test_real_model_offline():
    import api

    importlib.reload(api)
    result = api.run_extract_data(TEXT, {"fields": "invoice_number, payee"})
    record = result["records"][0]
    assert record["invoice_number"]["text"] == "2024-117"
    assert TEXT[record["payee"]["start"]:record["payee"]["end"]] == record["payee"]["text"]
