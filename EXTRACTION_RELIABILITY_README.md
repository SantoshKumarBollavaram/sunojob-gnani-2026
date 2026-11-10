# SunoJob extraction reliability update

Apply this after SunoJob_Card_Core.zip. It updates the Gemini adapter and CLI,
adds 14 reliability tests, and updates the checkpoint instructions. It does
not change the Gnani integration, card schema, evidence rules or fixture labels.
No additional dependencies are required.

## Why this model

The user received a 404 for gemini-2.5-flash and an explicit high-demand 503
for gemini-3.8-flash. Their model listing also includes gemini-3.5-flash-lite.
Google documents that model as stable and supporting structured outputs:
https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite

It is now the default. Listing a model does not establish generation quota,
account eligibility or current serving capacity. The next real extraction
still has to verify those. No live Gemini call has been made by the assistant.

## Install

Download SunoJob_Extraction_Reliability_Fix.zip to ~/Downloads, then:

```bash
bash <<'BASH'
set -eu
cd "$HOME/sunojob"
mkdir -p .local/backups
sunojob_backup_dir="$(mktemp -d .local/backups/extraction-XXXXXX)"
cp -p sunojob/providers.py sunojob/__main__.py "$sunojob_backup_dir/"
.venv/bin/python -m zipfile -e "$HOME/Downloads/SunoJob_Extraction_Reliability_Fix.zip" .
.venv/bin/python -m unittest discover -s tests -v
BASH
```

With the existing WAV and card suites, 70 tests should run. Tests use fake HTTP
responses and do not make model requests or consume credits.

## Try a real extraction

```bash
cd "$HOME/sunojob"
export SUNOJOB_GEMINI_MODEL="gemini-3.5-flash-lite"
.venv/bin/python -m sunojob extract --case catering_en_correction
```

The export overrides the earlier 3.8 selection in the current shell. Subsequent
fresh shells use the same new default unless another environment override is
set. The key is entered through a hidden prompt, never stored in the report.

## Retry policy and records

- A logical extraction uses at most three HTTP requests to the same model.
- Only an explicit HTTP 503 is automatically retried. Default delays: 1s, 2s.
- Numeric Retry-After up to 10s is respected. Larger or unparseable values stop
  automatic retries, allowing a human to decide when to try again.
- 400, 401, 403, 404, 429 and other HTTP statuses are not automatically retried.
- Network failures/timeouts, invalid JSON, schema/evidence failures, truncated
  model output and blocked output are not automatically retried.
- No automatic model fallback or silent repair of extracted instructions.
- Each attempt records status, elapsed time and retry decision without keys or
  request content. Successful and failed logical attempts keep these records.
- A recovered extraction is not evidence that the provider never failed.
- The requested model and provider-returned model version are saved separately.
- No temperature override is sent, following current Gemini 3 guidance.

## Evaluation

Copy the exact Saved result path from extraction:

```bash
read -r -p "Saved extraction result path: " sunojob_result
.venv/bin/python -m sunojob evaluate --result "$sunojob_result"
```

The existing semantic rubric is unchanged. Strict unmatched claims need manual
review and are not automatically labelled inventions. Failed logical attempts
remain recorded. This update improves handling of a temporary error; it cannot
guarantee model availability or correctness.

## Verification

All 14 new reliability tests pass offline, including 503 recovery, capped
retries, non-retryable errors, Retry-After handling, credential redaction,
attempt-report persistence and returned-model recording. All 70 combined
tests pass after installing the ZIP over the previous two checkpoints in a
fresh temporary project.
