# SunoJob checkpoint 1: evidence-backed draft cards

This adds a runnable text-to-card extraction core and a labelled evaluation
harness to the existing Linux project. It does not replace the working Gnani
scripts, recordings, reports or virtual environment. It is a CLI checkpoint;
the browser interface, voice confirmation state machine, owner approval and
email delivery are subsequent checkpoints, not completed functionality here.

## Install

Download SunoJob_Card_Core.zip to ~/Downloads, then:

```bash
cd "$HOME/sunojob"
.venv/bin/python -m zipfile -e "$HOME/Downloads/SunoJob_Card_Core.zip" .
.venv/bin/python -m pip install -r requirements-core.txt
.venv/bin/python -m pip freeze > requirements-lock.txt
.venv/bin/python -m unittest discover -s tests -v
```

The core requires Python 3.12 and Pydantic 2. The API adapter uses requests,
already installed for the Gnani check. The reliability update retries explicit
HTTP 503 responses only, for at most three HTTP attempts per extraction.

## First run: labelled fixture, no key or API usage

```bash
.venv/bin/python -m sunojob demo --case catering_en_correction
.venv/bin/python -m sunojob demo --case catering_te_correction
```

These explicitly load a human-written expected card. They verify schema,
evidence resolution and display, not model quality. They cannot be passed to
the evaluation command as live predictions. This prevents reporting fixture
success as AI performance.

## Check the chosen speech languages

The updated Gnani script from the previous WAV fix supports these commands:

```bash
.venv/bin/python scripts/check_gnani.py --language en
.venv/bin/python scripts/check_gnani.py --language te
```

Each makes one TTS and one STT request. Listen to the saved normalized WAV and
inspect each returned transcript, especially the quantity correction, onion
restriction and condition before changing the menu. These are synthetic
integration checks, not tests of natural or code-mixed speech.

## Live extraction

Get a separate Gemini API key from https://aistudio.google.com/apikey if your
account has access. Gnani credits are not Gemini credits. No subscription or
free quota is assumed. The key is requested through a hidden terminal prompt
and is not written to the result. GEMINI_API_KEY can also be supplied in the
local environment. Keep all keys out of chat and Git.

```bash
.venv/bin/python -m sunojob extract --case catering_en_correction
```

This makes one logical extraction (at most three HTTP attempts for 503),
validates the draft, prints its source evidence,
and saves the attempt in `.local/sunojob-core/result-*.json`. The default model
is gemini-3.5-flash-lite, which is documented as supporting structured output.
Access is account-dependent. Select another available model through --model
or SUNOJOB_GEMINI_MODEL. Hosted Evon access has not been verified for the user;
the small ExtractionProvider protocol allows a future adapter to use the same
models, validator and evaluator.

The adapter uses GenerateContent REST with generationConfig.responseFormat,
text.mimeType set to APPLICATION_JSON, and text.schema. Local references are
inlined and the provider schema uses only basic type/properties/required/items/
enum keywords. The original strict local Pydantic validation is unchanged.
This API's response-format fields are evolving; the request parsing is tested
with mocked responses. Live
authentication, quota and model/schema acceptance still need verification
with the user's key. Every HTTP attempt's status and duration is recorded.
Only 503 responses are automatically retried, with 1s and 2s delays. Numeric
Retry-After values up to 10 seconds are respected; larger or unparseable values
stop automatic retries. Authentication, permission, model-access, quota,
network, malformed-output and semantic-validation errors are not retried.
There is no automatic switch to another model.

To extract directly from a successful Gnani report, use its exact printed
report path, for example by opening the prompt below:

```bash
read -r -p "Full path of your successful Gnani result.json: " sunojob_report
.venv/bin/python -m sunojob extract --gnani-report "$sunojob_report" --language te-IN
```

Choose en-IN, te-IN, hi-IN or mixed to match the actual source. For a text
file, use --text-file with its path. Text and Gnani-report extractions have no
automatic gold labels; review them manually.

## Evaluate a labelled extraction

Copy the exact Saved result path from a live --case extraction:

```bash
read -r -p "Full path of your saved extraction result: " sunojob_result
.venv/bin/python -m sunojob evaluate --result "$sunojob_result"
```

The evaluator counts strict matches on kind/subject/value, restrictions kept,
corrections applied, and unmatched candidate claims. Missing predictions,
provider failures and rejected drafts receive no matching credit and remain
in expected counts. A failed --case attempt is saved and can be scored too.

Unmatched claims require manual adjudication. They may be inventions, wrong
values, polarity errors or harmless paraphrases. The confirmed invented-action
count is null until a human audit; exact matching is not a semantic oracle.
Clarification checking currently checks presence, not question adequacy.

The 12 supplied cases are transparent development fixtures, including English,
Telugu, mixed speech, numeric correction, negation, conditional permission,
budget, time clarification, multi-turn correction, conflict, prompt injection,
multiline evidence and a greeting with no request. They are not a held-out
benchmark. Freeze new recordings before tuning prompts for final evaluation.

## Code map

| File | Responsibility |
| --- | --- |
| sunojob/models.py | Strict draft, instruction, correction and evidence schema |
| sunojob/validation.py | Exact quotes, offsets, IDs and correction consistency |
| sunojob/providers.py | Replaceable model interface and Gemini adapter |
| sunojob/evaluation.py | Strict labelled scoring and explicit limitations |
| sunojob/__main__.py | CLI, hidden credential prompt and attempt reports |
| fixtures/catering_cases.json | Human-written development inputs and labels |
| tests/test_card_core.py | Core regression tests; no model/API calls |

## Important limits

- Every instruction and correction requires an exact quote and source turn.
  Offsets are Python Unicode code points, not JavaScript UTF-16 indexes.
- Quote existence does not prove that a paraphrase preserves its meaning.
  A deliberately reversed prohibition is included in the tests to demonstrate
  that limitation: structure passes, while the labelled scorer flags it.
- Questions about missing information are generated questions, not sourced facts.
- The model cannot mark customer_confirmed or owner_confirmed. Such output is
  rejected; application output always remains draft and requires human review.
- Only explicit corrections supersede values. Unresolved conflicts should ask
  a question. Internal checks do not detect every possible semantic conflict.
- The source digest detects a change in serialized source content; it does
  not prove identity, approval, legal enforceability or external authenticity.
- No model-generated card is a binding agreement merely because it exists.
  Both-party approval and reliable delivery are still to be implemented.

## Verification

Core tests run offline using Pydantic 2.14.1 and Python 3.12.14. Provider
responses are mocked. No live Gemini request was made by the assistant.
The package was also tested alongside the existing 19 WAV regression tests.

Official references checked:

- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/generate-content/structured-output
- https://ai.google.dev/gemini-api/docs/api-key
- https://docs.gnani.ai/api/TTS/available-voices
