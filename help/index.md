# MD-GLiNER2 Service

The **MD-GLiNER2** service uses the **[GLiNER2](https://huggingface.co/fastino/gliner2.5-multi-v1)** model to find information in plain text without needing a model trained for your specific labels. You describe what you're looking for in plain words, and the model finds it.

---

## Available Crunchers

### `extract_entities` — Find named entities
Finds mentions of the entity types you list (e.g. `person, organization, location, date`) and returns each one with its position in the text.

* **Why this is useful:** Instead of training or picking a model for a fixed set of entity types, you just type the types you care about.
* The entities are always browsable by type in the **Tags** view.
* **Create tags:** also tags the text with each entity found (its text, e.g. *Helsinki* or *Johan
  Virtanen*), so you can find and filter files by them. Each entity becomes one tag per text, even
  if it is mentioned many times. Long texts can get many tags, so use a short list of entity types.

### `classify_text` — Classify text
Assigns one or more of your categories (e.g. `sports, politics, finance`) to the whole text.

* Check **Allow multiple categories** if a text can reasonably belong to more than one category at once. Otherwise the single best-matching category is returned.
* You can also pick existing tags instead of typing categories. Tags with a description give the model
  extra context (e.g. label `subject` with description "the academic subject discussed") which can
  improve accuracy, and the run will only ever produce those exact tags on your files. This isn't
  available for **Find named entities**, since NER extracts many individual mentions per type rather
  than one whole-document label.

### `extract_data` — Extract structured data
Pulls out the specific fields you name (e.g. `invoice_number, date, total_amount`) as structured values.

* **Result:** a table with a column per field, usually one row; when the model finds several
  records in the text (e.g. a list of invoices) it can give one row each. Each value shows how
  confident the model is, and where in the text it was found.
* > ⚠️ **Note:** Fields that aren't present in the text are left empty — this cruncher does not guess missing values.
* Name fields the way a person would describe them (`payee`, `total amount`); the model reads the
  field names.

---

## Tips for labels

* Use plain, descriptive words — the model was not trained on your data, so it relies on the label wording itself (e.g. `location` works better than a project-specific code name).
* Keep the list short and specific to what you need; unrelated labels can dilute results.

## External Resources
* [GLiNER2 model card](https://huggingface.co/fastino/gliner2.5-multi-v1)
* [GLiNER2 GitHub repository](https://github.com/fastino-ai/GLiNER2)
