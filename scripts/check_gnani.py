"""Check Gnani speech APIs; resume saved TTS without paying to regenerate it."""

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter

from gnani_audio import normalize_pcm_wav


ROOT = Path(__file__).resolve().parents[1]
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"
STT_URL = "https://api.vachana.ai/stt/v3"
FIXTURES = {
    "hi": {
        "voice": "Nalini", "language": "hi-IN",
        "text": "पचास नहीं, चालीस डिब्बे तैयार करें। प्याज न डालें। मेन्यू बदलने से पहले मुझसे पूछें।",
    },
    "en": {
        "voice": "Kaveri", "language": "en-IN",
        "text": "Prepare fifty, actually forty lunch boxes. Do not add onion. Ask me before changing the menu.",
    },
    "te": {
        "voice": "Lehara", "language": "te-IN",
        "text": "యాభై కాదు, నలభై భోజన పెట్టెలు సిద్ధం చేయండి. ఉల్లిపాయ వేయవద్దు. మెనూ మార్చే ముందు నన్ను అడగండి.",
    },
}


def require_success(response, stage, secret):
    if response.status_code == 200:
        return
    explanations = {
        400: "Request parameters rejected.",
        401: "API key missing or invalid.",
        402: "Check account credits.",
        403: "Check account access and key service permissions.",
        429: "Rate limited; retry later.",
        500: "Service internal error.",
        503: "Service temporarily unavailable.",
    }
    detail = response.text.replace(secret, "[REDACTED]")[:600]
    reason = explanations.get(response.status_code, "Request failed.")
    raise RuntimeError(f"{stage}: HTTP {response.status_code}. {reason}\n{detail}")


def post(session, url, **kwargs):
    import requests

    try:
        return session.post(url, **kwargs)
    except requests.RequestException:
        raise RuntimeError(
            "Network/client error. No automatic retry was made."
        ) from None


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=FIXTURES, default="en")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--reuse-latest", action="store_true",
                        help="Reuse the newest saved synthetic-input.wav; no TTS call")
    source.add_argument("--audio", type=Path, help="Use an existing PCM WAV; no TTS call")
    parser.add_argument("--offline", action="store_true",
                        help="Validate/repair saved audio without a key or API calls")
    args = parser.parse_args()
    if args.offline and not (args.reuse_latest or args.audio):
        parser.error("--offline requires --reuse-latest or --audio")
    return args


def main():
    args = parse_args()
    fixture = FIXTURES[args.language]
    local_root = ROOT / ".local"
    source = args.audio
    if args.reuse_latest:
        candidates = list(local_root.glob("gnani-check-*/synthetic-input.wav"))
        if not candidates:
            raise RuntimeError("No saved TTS audio found. Use --audio PATH or a fresh run.")
        source = max(candidates, key=lambda p: p.stat().st_mtime_ns)

    # Inspect saved data before asking for a key or making any network request.
    info = None
    if source is not None:
        source = source.expanduser().resolve(strict=True)
        audio = source.read_bytes()
        normalized, info = normalize_pcm_wav(audio)
        print(f"Reusing: {source}", flush=True)

    local_root.mkdir(exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="gnani-resume-" if source else "gnani-check-",
                                  dir=local_root))
    tts_seconds = None
    if not args.offline:
        import requests

        key = os.environ.get("GNANI_API_KEY", "").strip()
        if not key:
            key = getpass.getpass("Gnani API key (hidden): ").strip()
        if not key or any(not 33 <= ord(c) <= 126 for c in key):
            raise RuntimeError("API key must contain printable ASCII without whitespace.")

        with requests.Session() as session:
            session.headers.update({"X-API-Key-ID": key})
            if source is None:
                print(f"Generating {args.language} synthetic speech...", flush=True)
                started = perf_counter()
                response = post(
                    session, TTS_URL,
                    json={
                        "text": fixture["text"], "voice": fixture["voice"],
                        "model": "timbre-v2.5", "language": fixture["language"],
                        "speed": 1.0,
                        "audio_config": {"sample_rate": 16000, "num_channels": 1,
                                         "sample_width": 2, "encoding": "linear_pcm",
                                         "container": "wav"},
                    },
                    timeout=(10, 90), allow_redirects=False,
                )
                tts_seconds = perf_counter() - started
                require_success(response, "TTS", key)
                audio = response.content
                (run_dir / "synthetic-input.wav").write_bytes(audio)
                normalized, info = normalize_pcm_wav(audio)

            audio_path = run_dir / "normalized-input.wav"
            audio_path.write_bytes(normalized)
            print_audio_info(info, audio_path)
            if not 8000 <= info["sample_rate"] <= 44100:
                raise RuntimeError("STT check requires a sample rate from 8 to 44.1 kHz.")

            print("Transcribing with Prisma v3.0...", flush=True)
            started = perf_counter()
            response = post(
                session, STT_URL,
                files={"audio_file": ("normalized-input.wav", normalized, "audio/wav")},
                data={"model": "prisma-v3.0", "language_code": fixture["language"]},
                timeout=(10, 90), allow_redirects=False,
            )
            stt_seconds = perf_counter() - started
            require_success(response, "STT", key)
            try:
                result = response.json()
            except ValueError as exc:
                raise RuntimeError("STT returned invalid JSON.") from exc
            if not isinstance(result, dict) or result.get("success") is not True:
                raise RuntimeError("STT did not report success.")
            transcript = result.get("transcript")
            if not isinstance(transcript, str) or not transcript.strip():
                raise RuntimeError("STT returned an empty or invalid transcript.")
    else:
        audio_path = run_dir / "normalized-input.wav"
        audio_path.write_bytes(normalized)
        print_audio_info(info, audio_path)
        result, transcript, stt_seconds = {}, None, None

    report = {
        "check": "synthetic integration or offline audio check; not an accuracy benchmark",
        "source_audio": str(source) if source else "new synthetic TTS",
        "source_text": fixture["text"] if source is None else None,
        "language_hint": fixture["language"],
        "audio": info,
        "transcript": transcript,
        "tts_requested_this_run": source is None,
        "stt_requested_this_run": not args.offline,
        "stt_model_returned": result.get("model"),
        "tts_request_seconds": tts_seconds,
        "stt_request_seconds": stt_seconds,
    }
    report_path = run_dir / "result.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    if args.offline:
        print("PASS: Saved audio validated; no API requests made.")
    elif source:
        print("PASS: Saved audio validated and STT succeeded; TTS was not repeated.")
    else:
        print("PASS: TTS, audio validation and STT succeeded.")
    if transcript:
        print(f"Actual transcript:\n{transcript}")
    print(f"Report: {report_path}")


def print_audio_info(info, audio_path):
    print(f"Header frames: {info['declared_frames']}; actual frames: {info['actual_frames']}")
    print(f"Actual duration: {info['duration_seconds']:.3f}s")
    print(f"Unknown-length header repaired: {info['streaming_header_repaired']}")
    print(f"Normalized WAV: {audio_path}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        sys.exit(1)
    except Exception:
        # HTTP libraries can include credentials in exception messages. Do not
        # print arbitrary exception text or automatic tracebacks containing keys.
        print("FAILED: Network/client error. No automatic retry was made.", file=sys.stderr)
        sys.exit(1)
