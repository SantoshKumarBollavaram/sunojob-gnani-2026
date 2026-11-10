# Complete the existing SunoJob workflow

This archive consolidates the earlier voice, owner-review and email checkpoints,
including the email-validation fix. It includes two CLI tools and no new dependencies. The receipt-presentation update is documented in RECEIPT_UPDATE_README.md.
It does not modify the review database schema or expose the server remotely.

## 1. Read saved completion evidence first

```bash
cd "$HOME/sunojob"
.venv/bin/python -m sunojob.checkpoint
```

This command makes no network requests, sends nothing, and opens the database
read-only. Each row checks the CURRENT card digest, matching approval versions,
receipt integrity and saved SMTP outcomes. Drafts, later corrections and damaged
records cannot qualify on an old approval. It does not print names, recipient
addresses or transcripts. `--json` returns the same evidence in JSON.

SMTP acceptance is not inbox delivery. A saved approval does not verify identity
or prove that the user understood a spoken readback. Perform the manual checks.

## 2. Finish the live email check

```bash
.venv/bin/python -m sunojob.serve --model gemini-3.5-flash-lite --email
```

Enter credentials only at the terminal prompts. Refresh http://127.0.0.1:8765
with Ctrl+Shift+R. Open the approved English request, expand the email section,
enter both recipient addresses, and preview. Blank or invalid fields now receive
specific errors beside these controls. Nothing is sent by previewing.

Review both addresses and the saved record. Check the review checkbox and press
**Send to both now**. Check BOTH actual inboxes, including Spam, and compare the
attached HTML and JSON records. Reusing an accepted preview does not resend it.
If an outcome is unknown, do not repeatedly click Send. See EMAIL_DELIVERY_README.md.

## 3. Complete Telugu on a new request

Choose Telugu + English and speak naturally:

> యాభై కాదు, నలభై భోజన పెట్టెలు సిద్ధం చేయండి. ఉల్లిపాయ వేయవద్దు. మెనూ మార్చే ముందు నన్ను అడగండి.

Check 40 lunch boxes, no onion and ask before menu changes. Generate and fully
listen to the readback. Reply with a correction, for example:

> నలభై ఐదు భోజన పెట్టెలు చేయండి.

Check that the quantity is now 45, both restrictions survived, and the revised
card is unconfirmed. Generate and listen to that version's readback, then say
**అవును**. Complete separate owner approval, then download and compare receipts.
Refresh and check persistence. Record any transcription or meaning error rather
than editing it out of the test log. This is a prompted development check.

## 4. Evaluate a recorded request

The runner evaluates speech-to-card extraction. Browser confirmation, TTS,
owner approval and email are separate checks. Input audio may be WAV/WebM/OGG
or another FFmpeg-supported recording, 0.1–25 seconds, smaller than 4 MB.

First show the exact scripted practice reference and expected slots:

```bash
.venv/bin/python -m sunojob.recording_eval template --case catering_en_correction
```

Record that request in your own voice using a recorder, or reuse an existing
request recording from `.local/voice-audio/`. Files beginning with `readback-`
are synthesized readbacks and must not be treated as natural customer speech.
Listen to your actual file. Verify the reference text and labels BEFORE running
the model. If your words differ, use custom checked labels instead of claiming
that the fixture text is the reference.

```bash
read -r -p "Path of the checked English request recording: " sunojob_audio
.venv/bin/python -m sunojob.recording_eval run \
  --case catering_en_correction \
  --audio "$sunojob_audio" \
  --reference-checked \
  --model gemini-3.5-flash-lite
```

This makes ONE STT request, then ONE logical extraction (up to three HTTP attempts
for explicit Gemini 503 responses). It makes no TTS or SMTP calls. The reference
and expected labels are NOT included in the extraction prompt. English uses
en-IN transcription; Telugu/mixed uses the existing te-IN,en-IN configuration.
No account capacity or provider availability is assumed.

The result records the checked labels and their digest, audio digest, recognized
transcript, extraction, elapsed time, failed stage if any, word-edit statistics,
and strict instruction/restriction/correction matches. Evidence quotes are checked
against the recognized transcript; expected meaning is scored against the labels.
It saves failed provider attempts, including interrupted provider calls, with no
raw provider error text. Exceptions before a usable evaluation can start (such as
a missing file or invalid labels) are operator errors, not model attempts.

Do not change the reference AFTER seeing a prediction just to improve its score.
Review synonyms, unsupported claims, conditions and question adequacy manually.
Word error rate is not instruction accuracy; number words and digits are not
silently treated as equivalent by the word-edit metric.

Other single-recording practice cases:

| Case | Purpose |
| --- | --- |
| catering_te_correction | Telugu correction and restrictions |
| catering_mixed_correction | Telugu-English mixing |
| catering_en_negated_old_quantity | Distinguish exclusion from correction |
| catering_en_budget | Budget restriction |
| catering_en_missing_date | Ask for missing delivery date |
| catering_en_deadline_correction | Correct a delivery time |

The supplied cases are DEVELOPMENT fixtures. Prompted recordings of these same
sentences are useful integration checks, not independent real-world validation.
Multi-turn fixtures are deliberately rejected by this single-recording runner.

## 5. Collect independent speech and degraded variants

Have another person describe a request in their own words WITHOUT reading the
fixture. With their permission, save the recording. Listen and transcribe what
they actually said; independently label the intended active instructions,
restrictions and explicit corrections before calling the model.

To obtain the custom-label format:

```bash
mkdir -p .local/evaluation-labels
.venv/bin/python -m sunojob.recording_eval template \
  --case catering_en_correction > .local/evaluation-labels/own-request.json
```

Edit that JSON: give it a unique `id`, set `collection` to `independent_natural`,
set `language` to en-IN, te-IN or mixed, replace `reference_text` with the checked
transcript, and replace the expected instructions/corrections/clarification label.
Keep plain semantic labels: supported kinds are task, prohibition,
permission_required, quantity, deadline, budget and constraint; subjects use
lowercase letters, digits and underscores. Do not add model predictions to labels.
If no correction was spoken, expected_corrections must be an empty list.

```bash
read -r -p "Path of the independently labelled recording: " sunojob_audio
.venv/bin/python -m sunojob.recording_eval run \
  --labels .local/evaluation-labels/own-request.json \
  --audio "$sunojob_audio" --reference-checked
```

For an 8 kHz variant of the SAME checked recording:

```bash
ffmpeg -nostdin -n -i "$sunojob_audio" -ac 1 -ar 8000 \
  .local/evaluation-labels/own-request-8khz.wav
```

Evaluate it with the same checked labels. The existing speech adapter normalizes
inputs to 16 kHz before STT; upsampling the 8 kHz file does not restore its lost
bandwidth. These are related recordings, not independent speakers. For noise
testing, record a separate consented request in a real noisy setting and label
what was actually spoken; do not invent a noise-performance claim.

## 6. Review all attempted runs

```bash
.venv/bin/python -m sunojob.recording_eval summary
```

This command makes no API requests. It counts every saved attempt, including
failures and repeats, and reports distinct input audio hashes and groups by
collection, language, model and live/offline service mode. It recomputes scores
from saved labels and predictions. Duplicate attempt files are rejected rather
than double-counted. An aggregate over repeats is an ATTEMPT count, not an
independent test-set accuracy estimate. Separate models/collections when reporting.
No number of confirmed invented actions is reported until a human audit.

## Completion checklist

- [ ] English request → correction → fresh customer approval → separate owner approval.
- [ ] Telugu request → correction → fresh customer approval → separate owner approval.
- [ ] Refresh preserves current versions, approvals and receipts.
- [ ] Later corrections invalidate prior approval for the current workflow.
- [ ] Both email copies accepted by SMTP; both inboxes manually checked.
- [ ] Customer/owner HTML and JSON attachments match.
- [ ] Independent natural, mixed-language and degraded recordings evaluated with failures retained.
- [ ] Missing details and conditional permissions manually checked for meaning.
- [ ] Final demo, README and measured limitations prepared.
- [ ] Remote access and contest requirements checked before publishing/submitting.

## Verification and remaining limits

225 automated offline tests pass. New coverage includes read-only auditing,
receipt/approval integrity, stale approvals, input privacy, ASR/reference separation,
failure denominators, interrupted calls, duplicate attempts and Telugu word tokens.
No live API or SMTP calls were made here. The new CLI was smoke-tested with empty
local data; service integrations were exercised with offline doubles.

This archive does not implement hosting or identity verification, establish
real-world accuracy, or verify actual inbox delivery. The recorded results are
local evidence files, not cryptographically attested benchmark data.
