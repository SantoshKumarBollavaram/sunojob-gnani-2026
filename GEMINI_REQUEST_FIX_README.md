# SunoJob: request-format update and staged API diagnosis

The user's two HTTP 400 responses mean the generation requests were rejected,
but the bare INVALID_ARGUMENT message does not identify a specific field.
Creating another key is not the next repair: model listing already succeeded.
The assistant has not made live authenticated Gemini requests.

This update changes the extraction payload to the current documented REST
responseFormat shape and a small JSON-schema subset. It also adds a three-stage
diagnostic so the next authenticated run isolates failure more precisely.

## Install after the previous checkpoints

Download SunoJob_Gemini_Request_Fix.zip to ~/Downloads, then:

```bash
bash <<'BASH'
set -eu
cd "$HOME/sunojob"
mkdir -p .local/backups
sunojob_backup_dir="$(mktemp -d .local/backups/request-format-XXXXXX)"
cp -p sunojob/providers.py "$sunojob_backup_dir/"
.venv/bin/python -m zipfile -e "$HOME/Downloads/SunoJob_Gemini_Request_Fix.zip" .
.venv/bin/python -m unittest discover -s tests -v
BASH
```

No additional dependencies. The combined suite should run 91 tests. Those are
offline tests, not evidence of server acceptance or model accuracy.

## Run one controlled diagnostic

```bash
cd "$HOME/sunojob"
.venv/bin/python -m sunojob.diagnostics \
  --model gemini-3.5-flash-lite \
  --case catering_en_correction
```

The key is requested once through a hidden prompt. The command makes at most
three generation requests and stops at the first failure. There are no retries
in diagnostic mode. These requests consume API quota and successful generations
may incur usage charges depending on the project's billing plan.

| Stage | What it sends | What a failure narrows down |
| --- | --- | --- |
| basic_text | Reply with OK; no schema or system prompt | Generation path, minimal configuration, service or project access |
| minimal_structured_json | A tiny object with one boolean field | Structured-output request contract or control response |
| full_card | The actual card request using the conservative provider schema | Full prompt/schema handling or local card validation |

It saves the fictional request bodies, returned text and per-stage outcomes in
one .local/sunojob-core/result-*.json report. Authentication headers and API keys
are excluded. Request bodies are saved only for these supplied fictional cases.

If all three stages pass, the last stage already performs a real extraction:
the command prints the validated draft and saves an ordinary case-labelled
result. Evaluate that exact result without another model call:

```bash
read -r -p "Saved diagnostic result path: " sunojob_result
.venv/bin/python -m sunojob evaluate --result "$sunojob_result"
```

If it fails, send the console output and the failing stage. Do not keep retrying
the unchanged request. The partial result is saved even when a stage fails.

## Payload changes

The provider request now contains:

```json
{
  "generationConfig": {
    "maxOutputTokens": 8192,
    "responseFormat": {
      "text": {
        "mimeType": "APPLICATION_JSON",
        "schema": {"type": "object", "properties": {}}
      }
    }
  }
}
```

The small schema above illustrates the envelope only; the executable builder
sends the complete instruction/correction/question schema. It resolves local
references, keeps all field names, required fields, types and enums, and leaves
regex, length limits, evidence counts and other strict checks to the unchanged
local Pydantic models. Invalid evidence, unsupported confirmation fields and
inconsistent corrections are still rejected. This is not a loosening of what
the application accepts as a valid card.

Both older and newer response-format examples appear in Google's documentation.
This update does not claim the old format alone caused the user's 400. The
request-format change and conservative schema still need live verification.

The regular extract command retains its existing capped 503 retry policy.
The diagnostic command intentionally makes one HTTP attempt per stage.

## Verification

21 added offline tests cover reference resolution, provider-schema keywords,
the native MIME enum, field/type preservation, unchanged local validation,
diagnostic stage boundaries, early stopping and successful evaluable drafts.
The archive is installed over all previous checkpoints in a fresh temporary
project before running the combined 91 tests.

Official references checked:

- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/generate-content/structured-output
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
