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
`gliner2.ner.json` output file, so MessyDesk's generic file intake detects `type: "ner.json"` and the result
is browsable in the Tags view without an `Entity`/`TagLink`. `classify_text` and `extract_data` produce
whole-document results and are autotagged/stored accordingly. See [help/index.md](help/index.md) for the
user-facing description.

## Local development

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python api.py            # listens on :9010
```

Note: changes to `api.py` require restarting the process (no autoreload) before they take effect.
Set `DEVICE=cuda` (or `mps`) to run the model on GPU instead of CPU.

## Docker

```
make build
make start     # runs on :9010, MD_URL points back at the MessyDesk backend
make restart    # after code changes
make bash       # shell into the running container
```

## Output cleanup

`/process` writes results under `output/<uuid>/` for `/files` to serve. Since output isn't deleted on
fetch, a background sweep removes any output directory older than `OUTPUT_MAX_AGE_SECONDS` (default 1
hour), checked every `OUTPUT_CLEANUP_INTERVAL_SECONDS` (default 5 minutes).
