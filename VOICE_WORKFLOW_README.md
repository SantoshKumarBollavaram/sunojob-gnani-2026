# SunoJob: local customer voice review checkpoint

## Scope and evidence

This checkpoint adds a local browser interface to the existing card core:

1. Record or upload a short English or Telugu request.
2. Prisma transcribes the audio; Gemini proposes a source-backed draft.
3. Review tasks, restrictions, corrections and original transcript quotes.
4. Generate a deterministic readback using Timbre and play it.
5. Record a confirmation or explain a correction.
6. A correction creates a new draft version, which requires a new readback.
7. An explicit confirmation records the customer's reply against that exact
   version and its card digest. Owner confirmation remains pending.

The application is general-purpose; catering is the development example.
English and Telugu are selectable. Generic field labels may remain English
inside Telugu readbacks; their source wording is retained. Native-speaker
listening tests are still needed before claiming Telugu usability.

Evidence available before this checkpoint: the user's English labelled case
matched four instructions, two restrictions and one correction; the user's
synthetic Telugu speech-to-card run also visibly retained those facts. These
are narrow integration checks, not a real-world accuracy benchmark.

Verification of this package: 130 automated tests passed, including actual
FFmpeg conversion and mocked request contracts for the real speech adapters.
Workflow HTTP tests use explicitly labelled offline service doubles. JavaScript
syntax was checked. This environment's browser could not reach the local test
server, so rendered layout, microphone capture and the integrated live browser
loop have NOT been verified here. Complete the acceptance check below on Linux.

## Install over the existing project

Download `SunoJob_Voice_Workflow.zip` into `~/Downloads`. This is a source
checkpoint, not a replacement for your virtual environment or saved results.
The commands below back up the source directories before extraction. They
leave `.local` results and the existing virtual environment in place.

```bash
bash <<'BASH'
set -eu
cd "$HOME/sunojob"

command -v ffmpeg >/dev/null || {
  printf '%s\n' 'FFmpeg is missing. Install it with: sudo apt install ffmpeg'
  exit 1
}
test -f "$HOME/Downloads/SunoJob_Voice_Workflow.zip"
mkdir -p .local/backups
sunojob_voice_backup="$(mktemp -d .local/backups/voice-workflow-XXXXXX)"
for path in sunojob scripts tests fixtures requirements-core.txt requirements-voice.txt
do
  if [ -e "$path" ]; then
    cp -a "$path" "$sunojob_voice_backup/"
  fi
done

.venv/bin/python -m zipfile -e \
  "$HOME/Downloads/SunoJob_Voice_Workflow.zip" .
.venv/bin/python -m pip install -r requirements-voice.txt
.venv/bin/python -m unittest discover -s tests -q
printf '\nSource backup: %s\n' "$sunojob_voice_backup"
BASH
```

Expected automated result: `Ran 130 tests ... OK`. A Starlette warning about
its legacy httpx test-client support can appear; it does not indicate a failed
test. These tests make no paid API calls and require no API keys.

Start the app from your normal terminal, outside the installation heredoc:

```bash
cd "$HOME/sunojob"
.venv/bin/python -m sunojob.serve --model gemini-3.5-flash-lite
```

Enter the Gnani and Gemini keys at the two hidden terminal prompts. Existing
`GNANI_API_KEY` and `GEMINI_API_KEY` environment variables are also accepted.
Keys stay in server memory and are not sent to the browser or written to files.
Keep this terminal running. Open **http://127.0.0.1:8765** in your laptop browser.
Stop the server with `Ctrl+C`. A different port is available with `--port 8767`.

## First live acceptance check

Use fictional requests. This run makes real provider requests and consumes
available credits/quota. No email or message is sent.

1. Choose **English**. Click **Record request**, allow this local site's
   microphone when your browser asks, and speak:

   > Prepare fifty, actually forty lunch boxes. Do not add onion.
   > Ask me before changing the menu.

   Click **Stop recording**. Recording automatically stops after 24 seconds;
   uploads and decoded recordings must be 0.1–25 seconds, below 4 MB.

2. Check the actual transcript under **Original words and corrections**.
   The draft should show 40 lunch boxes, no onion, and permission required
   before a menu change. It should retain the 50-to-40 correction. Never treat
   a structurally valid card as automatically correct.

3. Click **Generate spoken readback**, then press **Play**. Listen to its end.
   The readback includes active values and supporting original wording; this
   can repeat details. A full playback event enables the voice-reply path.

4. Click **Record reply** and say:

   > Yes, but make it forty-five lunch boxes.

   Expected: version 2, quantity 45, original restrictions retained, customer
   confirmation empty. Exact words vary with the actual transcription.

5. Generate and fully play the new readback. Then record:

   > I confirm.

   Expected: **Customer confirmed this version · Owner review pending**.
   The app deliberately accepts a small set of whole-utterance confirmations;
   it does not infer agreement from arbitrary conversational speech.

6. Refresh the page. The saved request and confirmation should persist.
   Proposing another correction must remove the current approval, create a
   new version after successful extraction, and require fresh readback.

7. Click **Start another request**, choose **తెలుగు + English**, and record:

   > యాభై కాదు, నలభై భోజన పెట్టెలు సిద్ధం చేయండి. ఉల్లిపాయ వేయవద్దు.
   > మెనూ మార్చే ముందు నన్ను అడగండి.

   Review the actual transcript and card, listen fully, then reply **అవును**
   only if the current card is correct. Check the naturalness of the Telugu
   audio as well as the facts. This is the first human-recording check, not
   a measured evaluation set.

If microphone capture is unavailable, upload an audio file. Typed requests
and typed corrections are available as a fallback, but typed text cannot
approve a card. Use the player to replay existing audio without paying for
another synthesis request.

If a provider request fails, retain the error and retry deliberately. Failed
corrections remain pending, so the old card cannot be approved accidentally.
The correction text is retained for retry. Restarting the server recovers
interrupted updates into a state requiring correction. Do not repeatedly
regenerate speech or rerun the earlier API diagnostic to troubleshoot the UI.

## What is recorded

All runtime data is local under `.local`:

- `reviews.sqlite3`: draft versions, current workflow state and review events.
- `voice-audio`: normalized input/response recordings and synthesized readbacks.
- `voice-attempts`: extraction inputs, outputs or failure types and HTTP attempt
  metadata. Failed extraction attempts are retained as well as successful ones.

Keep `.local/` and `.venv/` out of Git and public uploads. Recordings and
transcripts can contain private customer information. Test with fictional data
until retention and deletion behavior is designed for a real pilot.

The extracted card itself stays an immutable draft snapshot. Current approval
is stored separately in the review session and audit events. Confirmation
contains the version, card SHA-256, readback identifier, spoken reply and UTC
timestamp. SQLite transactions reject stale correction results and consumed
readback tokens. SHA-256 detects inconsistency against the saved snapshot;
it does not provide a signature, trusted timestamp or external tamper resistance.

Source validation checks exact quote existence, structure and internal
consistency. It cannot prove that a quote semantically supports a claim, that
all instructions were extracted, or that the transcription matches the audio.
Playback completion is a browser-reported event, not proof someone listened.
Customer identity is not verified.

## Module map

| File | Responsibility |
| --- | --- |
| `sunojob/serve.py` | Hidden key prompts and loopback-only server startup |
| `sunojob/webapp.py` | Browser endpoints, same-origin checks and validation |
| `sunojob/speech.py` | Audio conversion, Prisma, Timbre and extraction logging |
| `sunojob/workflow.py` | Persistent versions and version-specific approval rules |
| `sunojob/readback.py` | Deterministic readback with source wording |
| `sunojob/static/` | Microphone capture, cards, playback and corrections |
| `scripts/gnani_audio.py` | Existing tested streaming-WAV normalizer |

Gnani calls have no automatic retries. Gemini retries explicit 503 responses
at most three total attempts; it does not silently change models. The model
request format is the same one that passed the user's live diagnostic.

## Next completion gates

1. Pass the English and Telugu live browser checks above; fix observed failures.
2. Add separate owner acceptance of the same card version, then a shared receipt
   and delivery to both parties. Define recipient verification and approval
   invalidation before implementing sending. This checkpoint has no owner UI,
   email integration or shared receipt.
3. Build an independently labelled set of natural recordings. Include negation,
   corrections, ambiguities, Telugu-English mixing and 8 kHz/noise variants.
   Keep failed attempts in the denominator and manually review unsupported
   claims. Publish measured counts and failure examples, not fixture scores
   presented as accuracy.
4. Prepare deployment, a concise public demo, reproducible evaluation, README
   and submission material. Recheck the actual contest form requirements before
   submission; no award, interview or internship is guaranteed by this build.

Move to each gate when its acceptance checks pass. The submission cutoff still
applies, but these are completion gates rather than day-by-day work estimates.
