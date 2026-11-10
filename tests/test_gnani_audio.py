import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from gnani_audio import normalize_pcm_wav


def fixture(seconds=1.0, channels=1, width=2, rate=16000):
    frames = bytes([0x24, 0x12]) * (int(seconds * rate) * channels * width // 2)
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(frames)
    return out.getvalue(), frames


def streaming(audio, riff=True, data=True, sentinel=0xFFFFFFFF):
    out = bytearray(audio)
    if riff:
        struct.pack_into("<I", out, 4, sentinel)
    if data:
        struct.pack_into("<I", out, 40, sentinel)
    return bytes(out)


class AudioTests(unittest.TestCase):
    def assert_samples(self, normalized, expected):
        with wave.open(io.BytesIO(normalized), "rb") as wav:
            self.assertEqual(wav.readframes(wav.getnframes()), expected)
            self.assertEqual(wav.getnframes(), len(expected) // (wav.getnchannels() * wav.getsampwidth()))

    def test_regular_wav_preserves_samples(self):
        audio, frames = fixture()
        normalized, info = normalize_pcm_wav(audio)
        self.assertEqual(info["duration_seconds"], 1.0)
        self.assertFalse(info["streaming_header_repaired"])
        self.assert_samples(normalized, frames)

    def test_reproduces_reported_duration_and_repairs_it(self):
        audio, frames = fixture()
        audio = streaming(audio)
        with wave.open(io.BytesIO(audio), "rb") as wav:
            self.assertAlmostEqual(wav.getnframes() / wav.getframerate(), 134217.7279375)
        normalized, info = normalize_pcm_wav(audio)
        self.assertEqual(info["duration_seconds"], 1.0)
        self.assertTrue(info["streaming_header_repaired"])
        self.assert_samples(normalized, frames)

    def test_unknown_riff_size_only(self):
        audio, frames = fixture()
        normalized, info = normalize_pcm_wav(streaming(audio, data=False))
        self.assertEqual(info["actual_frames"], 16000)
        self.assert_samples(normalized, frames)

    def test_unknown_data_size_only(self):
        audio, frames = fixture()
        normalized, _ = normalize_pcm_wav(streaming(audio, riff=False))
        self.assert_samples(normalized, frames)

    def test_signed_max_size_sentinel(self):
        audio, frames = fixture()
        normalized, _ = normalize_pcm_wav(streaming(audio, sentinel=0x7FFFFFFF))
        self.assert_samples(normalized, frames)

    def test_actual_overlong_audio_rejected_with_both_header_types(self):
        audio, _ = fixture(seconds=30.001)
        for source in (audio, streaming(audio)):
            with self.subTest(streaming=source != audio):
                with self.assertRaisesRegex(ValueError, "not cropped"):
                    normalize_pcm_wav(source)

    def test_exactly_thirty_seconds_allowed(self):
        audio, _ = fixture(seconds=30)
        _, info = normalize_pcm_wav(streaming(audio))
        self.assertEqual(info["duration_seconds"], 30)

    def test_truncated_riff_rejected(self):
        audio, _ = fixture()
        with self.assertRaisesRegex(ValueError, "RIFF length"):
            normalize_pcm_wav(audio[:-2])

    def test_truncated_data_with_unknown_riff_rejected(self):
        audio, _ = fixture()
        audio = streaming(audio, data=False)
        with self.assertRaisesRegex(ValueError, "truncated"):
            normalize_pcm_wav(audio[:-2])

    def test_partial_frame_rejected(self):
        audio, _ = fixture()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            normalize_pcm_wav(streaming(audio)[:-1])

    def test_empty_audio_rejected(self):
        audio, _ = fixture(seconds=0)
        with self.assertRaisesRegex(ValueError, "empty"):
            normalize_pcm_wav(audio)

    def test_invalid_response_rejected(self):
        for audio in (b"", b'{"error":"bad request"}', b"not a WAV file"):
            with self.subTest(audio=audio):
                with self.assertRaises(ValueError):
                    normalize_pcm_wav(audio)

    def test_missing_data_chunk_rejected(self):
        audio = bytearray(fixture()[0][:36])
        struct.pack_into("<I", audio, 4, len(audio) - 8)
        with self.assertRaisesRegex(ValueError, "data chunk"):
            normalize_pcm_wav(bytes(audio))

    def test_metadata_padding_supported(self):
        audio, frames = fixture()
        out = bytearray(audio[:36] + b"JUNK" + struct.pack("<I", 3) + b"abc\0" + audio[36:])
        struct.pack_into("<I", out, 4, len(out) - 8)
        normalized, _ = normalize_pcm_wav(bytes(out))
        self.assert_samples(normalized, frames)

    def test_stereo_uses_full_frame_size(self):
        audio, frames = fixture(channels=2)
        normalized, info = normalize_pcm_wav(streaming(audio))
        self.assertEqual(info["duration_seconds"], 1.0)
        self.assertEqual(info["channels"], 2)
        self.assert_samples(normalized, frames)

    def test_other_sample_rate(self):
        audio, _ = fixture(rate=24000)
        _, info = normalize_pcm_wav(streaming(audio))
        self.assertEqual(info["duration_seconds"], 1.0)

    def test_invalid_duration_limit_rejected(self):
        audio, _ = fixture()
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_pcm_wav(audio, max_seconds=value)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg not installed")
    def test_actual_ffmpeg_nonseekable_wav_output(self):
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
             "-t", "0.5", "-ac", "1", "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"],
            capture_output=True, check=True, timeout=10,
        )
        normalized, info = normalize_pcm_wav(result.stdout)
        self.assertEqual(info["duration_seconds"], 0.5)
        self.assertTrue(info["streaming_header_repaired"])
        self.assertGreater(len(normalized), 44)

    def test_offline_cli_repairs_saved_audio_without_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "scripts").mkdir()
            for name in ("check_gnani.py", "gnani_audio.py"):
                shutil.copy2(SCRIPTS / name, root / "scripts" / name)
            saved = root / ".local" / "gnani-check-old"
            saved.mkdir(parents=True)
            (saved / "synthetic-input.wav").write_bytes(streaming(fixture()[0]))
            result = subprocess.run(
                [sys.executable, str(root / "scripts" / "check_gnani.py"),
                 "--reuse-latest", "--language", "hi", "--offline"],
                input="", capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("no API requests", result.stdout)
            reports = list((root / ".local").glob("gnani-resume-*/result.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text())
            self.assertFalse(report["tts_requested_this_run"])
            self.assertFalse(report["stt_requested_this_run"])
            self.assertIsNone(report["transcript"])
            self.assertEqual(report["audio"]["duration_seconds"], 1.0)


if __name__ == "__main__":
    unittest.main()
