# MD-Gliner2

MessyDesk processing service ("cruncher") wrapping [GLiNER2](https://huggingface.co/fastino/gliner2.5-multi-v1),
a zero-shot NLP model for entity extraction, text classification, and structured data extraction — all
without task-specific fine-tuning, driven purely by the labels/fields you give it.

## Tasks

- `extract_entities` — find entities (person, organization, location, date, ...) matching user-defined
  labels. Produces span-level results (Faceted ROI-data), never autotagged.
- `classify_text` — assign one or more user-defined categories to the whole text. `autotag: true`, with
  a user-facing `multi_label` checkbox to allow more than one category at once.
- `extract_data` — pull user-defined fields (e.g. invoice_number, date, total_amount) out of the text
  into structured data.

All three are `one-to-one`. See [service.json](service.json) for exact params.

## Output shape

`extract_entities` writes span-level results (start/end offsets into the source text) as a double-extension
`gliner.ner.json` output file, so MessyDesk's generic file intake detects `type: "ner.json"` and the result
is browsable in the Tags view without an `Entity`/`TagLink`. `extract_data` writes
`gliner.fields.json` (type `fields.json`, format `messydesk-fields/1`): the fields asked for and a
record per instance found, each value `{text, confidence, start, end}` or `null`; the UI shows it
as a table. `classify_text` produces plain result JSON (`gliner.json`, used for autotagging).

`extract_entities` with `autotag` (Create tags) also writes `file_tags`: each entity text once, at
its best confidence, for the source file. MessyDesk tags the text with them. See
[help/index.md](help/index.md) for the user-facing description.

## Local development

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python api.py            # listens on :9010
```

Note: changes to `api.py` require restarting the process (no autoreload) before they take effect.
Set `DEVICE=cuda` (or `mps`) to run the model on GPU instead of CPU.

## Container

The model (`GLINER_MODEL`, default `fastino/gliner2.5-multi-v1`) is downloaded into the image at
build time and the service runs with `HF_HUB_OFFLINE=1`: it starts without network access, and
every container of a version runs the same model. The image is about 2.5 GB.

```
make build     # podman by default; CONTAINER_RUNTIME=docker for Docker
make test      # the tests, in the image, with the real model
make start     # runs on :9010
make restart    # after code changes
make bash       # shell into the running container
```

## Output cleanup

`/process` writes results under `output/<uuid>/` for `/files` to serve. Since output isn't deleted on
fetch, a background sweep removes any output directory older than `OUTPUT_MAX_AGE_SECONDS` (default 1
hour), checked every `OUTPUT_CLEANUP_INTERVAL_SECONDS` (default 5 minutes).

## Storage modes

The service picks its mode at start-up:

- **Disk mode** when `MD_PATH` points at the MessyDesk root (the directory that contains `data/`). The service reads the input from `message.file.path`, writes its output to `MD_PATH/data/<db>/tmp/`, and `/config` reports the `elg_fs` adapter. In a container, mount MessyDesk's `data/` and set `MD_PATH` to the mount's parent directory, for example `-v /path/to/MessyDesk/data:/app/data -e MD_PATH=/app`.
- **HTTP mode** when `MD_PATH` is unset or has no `data/`. The input comes as the `content` upload, outputs are served from `/files`, and `/config` reports the `elg` adapter. `STORAGE_MODE=http` forces this mode.

A request that uploads `content` is always handled in HTTP mode. `SERVICE_ADAPTER` overrides the adapter that `/config` reports.
