"""Real speech/model adapters. All credentials stay in the server process."""

import base64
import binascii
import hashlib
import io
import json
from pathlib import Path
import subprocess
import uuid
import wave

import requests

from .providers import GeminiExtractor, ProviderError


def captured_wav(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Invalid audio encoding") from None
    if not raw or len(raw) > 4_000_000:
        raise ValueError("Recording must be nonempty and smaller than 4 MB")
    try:
        result = subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "pipe",
            "-i", "pipe:0", "-map", "0:a:0", "-t", "26", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
        ], input=raw, capture_output=True, timeout=15, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        raise ValueError("Audio conversion failed. Check FFmpeg and try a WAV recording.") from None
    frames = result.stdout
    duration = len(frames) / 32000
    if not 0.1 <= duration <= 25:
        raise ValueError("Record between 0.1 and 25 seconds; overlong audio is not cropped")
    if len(frames) % 2:
        raise ValueError("Audio contains an incomplete PCM frame")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(frames)
    return output.getvalue(), duration


class LiveServices:
    mode = "live"

    def __init__(self, gnani_key, gemini_key, model, audio_dir):
        self.gnani_key, self.gemini_key, self.model = gnani_key, gemini_key, model
        self.audio_dir = Path(audio_dir)
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    def _post(self, url, **kwargs):
        try:
            response = requests.post(url, headers={"X-API-Key-ID": self.gnani_key},
                                     timeout=(10, 90), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise ProviderError("Gnani network error; no automatic retry was made") from None
        if response.status_code != 200:
            detail = response.text.replace(self.gnani_key, "[REDACTED]")[:500]
            raise ProviderError(f"Gnani HTTP {response.status_code}: {detail}")
        return response

    def transcribe(self, encoded, language):
        audio, duration = captured_wav(encoded)
        path = self.audio_dir / (uuid.uuid4().hex + ".wav")
        path.write_bytes(audio)
        response = self._post("https://api.vachana.ai/stt/v3",
            files={"audio_file": ("request.wav", audio, "audio/wav")},
            data={"model": "prisma-v3.0", "language_code": "te-IN,en-IN" if language == "te-IN" else "en-IN"})
        try:
            body = response.json()
        except ValueError:
            raise ProviderError("Gnani returned invalid transcription JSON") from None
        text = body.get("transcript") if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip() or body.get("success") is not True:
            raise ProviderError("No usable transcription; please record the instruction again")
        return text, {"origin": "speech", "audio_file": path.name, "duration_seconds": duration,
                      "audio_sha256": hashlib.sha256(audio).hexdigest(), "model": body.get("model")}

    def extract(self, sources):
        provider = GeminiExtractor(self.gemini_key, self.model)
        report = {"model": self.model, "sources": [s.model_dump() for s in sources]}
        folder = self.audio_dir.parent / "voice-attempts"
        folder.mkdir(exist_ok=True)
        path = folder / (uuid.uuid4().hex + ".json")
        try:
            result = provider.extract(sources)
            report["extraction"] = result.model_dump()
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            raise
        finally:
            report["http_attempts"] = provider.attempts
            report["validation_attempts"] = provider.validation_attempts
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return result, {"extraction_model": self.model, "http_attempts": provider.attempts,
                        "attempt_report": path.name}

    def synthesize(self, text, language):
        response = self._post("https://api.vachana.ai/api/v1/tts/inference", json={
            "text": text, "model": "timbre-v2.5", "voice": "Lehara" if language == "te-IN" else "Kaveri",
            "language": language, "speed": 1.0,
            "audio_config": {"sample_rate": 16000, "num_channels": 1, "sample_width": 2,
                             "encoding": "linear_pcm", "container": "wav"},
        })
        # Reuse the previously tested streaming-WAV fix. Readback can be longer
        # than a transcription clip, so its duration limit is separate.
        from scripts.gnani_audio import normalize_pcm_wav
        audio, _ = normalize_pcm_wav(response.content, max_seconds=180)
        (self.audio_dir / ("readback-" + hashlib.sha256(audio).hexdigest() + ".wav")).write_bytes(audio)
        return audio
