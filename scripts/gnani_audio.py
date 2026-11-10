"""Validate PCM WAV payloads and replace unknown-length headers.

Only explicit streaming-size sentinels are repaired. Ordinary truncated WAVs
are rejected. Duration is calculated from actual sample bytes, never from the
advertised frame count. This does not establish speech quality or completeness.
"""

import io
import math
import struct
import wave


UNKNOWN_SIZES = {0xFFFFFFFF, 0x7FFFFFFF}


def normalize_pcm_wav(audio: bytes, max_seconds: float = 30.0):
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be positive and finite")
    if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise ValueError("Response is not a RIFF/WAVE file")

    riff_size = struct.unpack_from("<I", audio, 4)[0]
    if riff_size not in UNKNOWN_SIZES and riff_size + 8 != len(audio):
        raise ValueError("RIFF length does not match the received file")

    offset = 12
    while offset + 8 <= len(audio):
        chunk_id = audio[offset : offset + 4]
        declared_size = struct.unpack_from("<I", audio, offset + 4)[0]
        start = offset + 8
        if chunk_id == b"data":
            break
        if declared_size in UNKNOWN_SIZES or start + declared_size > len(audio):
            raise ValueError("Invalid or truncated WAV metadata chunk")
        offset = start + declared_size + (declared_size % 2)
    else:
        raise ValueError("WAV contains no readable data chunk")

    streaming_header = declared_size in UNKNOWN_SIZES
    if streaming_header:
        # With unknown length, PCM data runs from this chunk to the HTTP EOF.
        frames = audio[start:]
    else:
        if start + declared_size > len(audio):
            raise ValueError("WAV sample data is truncated")
        frames = audio[start : start + declared_size]

    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            declared_frames = wav.getnframes()
            if wav.getcomptype() != "NONE":
                raise ValueError("Only uncompressed PCM WAV is supported")
    except (wave.Error, EOFError) as exc:
        raise ValueError("WAV format metadata is invalid or unsupported") from exc

    frame_size = channels * sample_width
    if not frames or len(frames) % frame_size:
        raise ValueError("WAV contains empty or incomplete PCM frames")
    frame_count = len(frames) // frame_size
    duration = frame_count / sample_rate
    if duration > max_seconds:
        raise ValueError(
            f"Actual audio is {duration:.3f}s; maximum is {max_seconds:g}s. "
            "The audio was not cropped."
        )

    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)

    info = {
        "duration_seconds": duration,
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "actual_frames": frame_count,
        "declared_frames": declared_frames,
        "streaming_header_repaired": streaming_header or riff_size in UNKNOWN_SIZES,
    }
    return output.getvalue(), info
