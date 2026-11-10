# SunoJob: WAV duration check fix

The reported 134217.7 seconds is reproduced by a 16 kHz, 16-bit mono WAV
whose data length is 0xFFFFFFFF, an unknown-length streaming placeholder.
This reproduction makes a streaming header the likely cause of the user's
failure, but the original response has not been inspected here.

The replacement counts complete PCM frames in the received data and writes a
new WAV header. It preserves sample bytes, rejects genuinely overlong audio,
rejects ordinary truncated files, and never crops audio to pass the limit.
Only explicit unknown-length sentinels are repaired. Original WAVs are retained.
This helper supports RIFF PCM WAV, not every audio container or codec. It
cannot prove that an unknown-length stream contains all intended speech.

## Install on the laptop

Download SunoJob_API_Check_Fix.zip to ~/Downloads, then run:

```bash
cd "$HOME/sunojob"
cp -p scripts/check_gnani.py "scripts/check_gnani.py.before-wav-fix-$(date +%s%N)"
.venv/bin/python -m zipfile -e "$HOME/Downloads/SunoJob_API_Check_Fix.zip" .
.venv/bin/python -m unittest discover -s tests -p test_gnani_audio.py -v
```

No new Python dependencies are required. The API check uses requests, already
installed during the initial setup. Normalization and the tests use Python's
standard library. One test also uses FFmpeg if available.

## Diagnose and repair without an API key or credit usage

```bash
.venv/bin/python scripts/check_gnani.py --reuse-latest --language hi --offline
```

This chooses the latest `.local/gnani-check-*/synthetic-input.wav`, which the
previous script saved before raising its duration error. It prints the header
and actual frame counts, writes a new normalized WAV, and saves a report.
It does not contact either API. If the original audio is absent, supply its
exact local path using --audio instead of --reuse-latest.

## Resume the failed Hindi integration check

```bash
.venv/bin/python scripts/check_gnani.py --reuse-latest --language hi
```

This reuses the saved original response, validates it, asks for a hidden API
key, and makes only one STT request. It does not repeat TTS. Each run writes
to a new `.local/gnani-resume-*` directory. Listen to the normalized WAV and
read the returned transcript; success here is integration evidence only.

## English and Telugu checks after resuming

```bash
.venv/bin/python scripts/check_gnani.py --language en
.venv/bin/python scripts/check_gnani.py --language te
```

Each fresh-language run makes one TTS request and one STT request and consumes
API credits. Telugu and English fixtures are fictional. These do not test
real customer speech or code-mixed accuracy. When reusing audio, --language
must match the recording; there is no automatic language inference here.

## Verification and limitations

Offline regression tests reproduce the exact reported header duration,
preserve sample bytes, handle metadata padding and stereo, and reject
malformed, truncated, empty, incomplete-frame and overlong files. A real
FFmpeg nonseekable WAV fixture exercises the same streaming-size pattern.
The CLI is tested in offline mode with cached audio and no credentials.
No live Gnani request has been made by the assistant. The customer's actual
WAV still needs the offline check, followed by the authenticated resume run.

Docs checked: https://docs.gnani.ai/api/TTS/tts-inference
https://docs.gnani.ai/api/STT/speech-to-text
https://docs.gnani.ai/api/TTS/available-voices
