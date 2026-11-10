"""Text to Speech: turn a script into an MP3 or WAV with Microsoft Edge neural voices.

Ported from the desktop ``AnderOng TTS`` tool (``edge-tts`` + Tkinter). In the browser
edition the synthesis runs **on the server** because the browser cannot open the Edge TTS
websocket itself (CORS + it needs a signed connection), and because the resulting file then
becomes a plain download the operator can upload to the PBX as a voice prompt.

Why one engine only
-------------------
``edge-tts`` is the only free, keyless engine that gives good Malay + Chinese neural voices
*and* honours prosody. The Google Translate backend (``gTTS``) was tried and removed: it has
no rate/volume control and only one voice per language, so it added a confusing second mode
without adding quality.

About emotions
--------------
The commercial Azure Speech service supports ``<mstts:express-as style="cheerful">``, but the
**free Edge endpoint rejects it** (every request with ``express-as`` returns no audio). What the
free endpoint *does* honour was measured, not assumed:

======================  ==================  ==========================
parameter               honoured?           evidence
======================  ==================  ==========================
``rate``                yes                 +40% shortened 67968 → 48960 frames
``volume``              yes                 +60% raised RMS 2532 → 3784
``pitch``               no                  frame count/peak/RMS unchanged
``mstts:express-as``    no                  no audio at all
======================  ==================  ==========================

So "tone" is offered as presets built from the parameters that really work
(rate + volume + sentence pauses), instead of a fake emotion dropdown.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import wave
from typing import Dict, List

import edge_tts
import miniaudio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..security import require_session
from ..sessions import PbxSession

logger = logging.getLogger("dpauto.tts")

router = APIRouter()

# Voice catalogue, kept identical to the desktop tool's VOICE_MAPPING.
VOICE_MAPPING: Dict[str, Dict[str, str]] = {
    "English": {"Female": "en-US-AvaNeural", "Male": "en-US-AndrewNeural"},
    "Malay": {"Female": "ms-MY-YasminNeural", "Male": "ms-MY-OsmanNeural"},
    "Chinese": {"Female": "zh-CN-XiaoxiaoNeural", "Male": "zh-CN-YunjianNeural"},
}

# ---------------------------------------------------------------- tone presets
# ``rate`` / ``volume`` are what the free endpoint really honours (see module docstring).
# ``pause`` inserts a short break after sentence punctuation, which is what makes a
# "calm" read actually feel slower without sounding stretched.
TONE_PRESETS: List[dict] = [
    {
        "id": "neutral",
        "label": "Neutral",
        "detail": "Straight read, no adjustments.",
        "rateOffset": 0,
        "volumeOffset": 0,
    },
    {
        "id": "warm",
        "label": "Warm / friendly",
        "detail": "A touch slower and softer — a reception greeting.",
        "rateOffset": -8,
        "volumeOffset": -4,
    },
    {
        "id": "calm",
        "label": "Calm / slow",
        "detail": "Clearly slower and quieter — instructions and after-hours messages.",
        "rateOffset": -20,
        "volumeOffset": -6,
    },
    {
        "id": "bright",
        "label": "Bright / upbeat",
        "detail": "A little faster and louder — promotions and short announcements.",
        "rateOffset": 12,
        "volumeOffset": 8,
    },
    {
        "id": "urgent",
        "label": "Urgent",
        "detail": "Fast and loud — time-sensitive notices.",
        "rateOffset": 25,
        "volumeOffset": 14,
    },
]
DEFAULT_TONE = "neutral"

# Output containers offered by the page. Edge only streams MP3, so WAV is transcoded
# server-side from the MP3 (miniaudio, no ffmpeg needed in the container).
FORMATS = [
    {
        "id": "mp3",
        "label": "MP3",
        "extension": "mp3",
        "mediaType": "audio/mpeg",
        "detail": "Smallest file; accepted by every PBX upload and browser.",
    },
    {
        "id": "wav",
        "label": "WAV (24 kHz, 16-bit mono)",
        "extension": "wav",
        "mediaType": "audio/wav",
        "detail": "Uncompressed PCM; use when the PBX or an editor wants WAV.",
    },
]
DEFAULT_FORMAT = "mp3"
WAV_SAMPLE_RATE = 24000

# The desktop slider is -50% .. +50%; the cap on text keeps one request bounded.
MAX_TEXT_CHARS = 5000
MIN_RATE = -50
MAX_RATE = 50
MIN_VOLUME = -50
MAX_VOLUME = 50

SAMPLE_SCRIPTS = {
    "English": "Thank you for calling Boustead Heavy Industries Corporation Berhad. Your call is important to us.",
    "Malay": "Terima kasih kerana menghubungi Boustead Heavy Industries Corporation Berhad.",
    "Chinese": "感谢您致电 Boustead Heavy Industries Corporation Berhad。",
}


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_CHARS)
    language: str = Field(default="Malay", max_length=40)
    gender: str = Field(default="Female", max_length=20)
    rate: int = Field(default=0, ge=MIN_RATE, le=MAX_RATE)
    tone: str = Field(default=DEFAULT_TONE, max_length=30)
    format: str = Field(default=DEFAULT_FORMAT, max_length=10)


@router.get("/voices")
def voices(_session: PbxSession = Depends(require_session)) -> dict:
    """Language / gender / voice catalogue, tone presets, formats and limits."""
    return {
        "languages": [
            {
                "language": language,
                "genders": list(genders.keys()),
                "voices": dict(genders),
            }
            for language, genders in VOICE_MAPPING.items()
        ],
        "defaults": {"language": "Malay", "gender": "Female", "rate": 10, "tone": DEFAULT_TONE, "format": DEFAULT_FORMAT},
        "tones": TONE_PRESETS,
        "formats": FORMATS,
        "maxTextChars": MAX_TEXT_CHARS,
        "minRate": MIN_RATE,
        "maxRate": MAX_RATE,
        "samples": SAMPLE_SCRIPTS,
        # Documented for the UI: the free endpoint has no emotion tag support.
        "supportsEmotionTag": False,
        "emotionNote": (
            "The free Edge endpoint rejects Azure's express-as emotion tag. "
            "Use the tone presets instead — they combine rate, volume and pauses."
        ),
    }


def _signed(value: int, unit: str) -> str:
    """edge-tts wants a signed value, e.g. ``+10%`` / ``-5%``."""
    return f"+{value}{unit}" if value >= 0 else f"{value}{unit}"


def _apply_tone(tone_id: str) -> tuple:
    """Resolve a tone preset into ``(rateOffset, volumeOffset)``.

    Only ``rate`` and ``volume`` are used: those are the two prosody knobs the free Edge
    endpoint actually honours (measured — see the module docstring). ``<break>`` was tried
    for extra pauses and is *not* used: the endpoint ignores the requested duration and
    inflated a 4.25 s clip to ~10 s regardless of the value.
    """
    tone = next((item for item in TONE_PRESETS if item["id"] == tone_id), TONE_PRESETS[0])
    return int(tone["rateOffset"]), int(tone["volumeOffset"])


def _safe_slug(text: str) -> str:
    """A short, ASCII-only fragment taken from the script.

    HTTP headers are latin-1, so a Chinese/Cyrillic script cannot go into the file name
    verbatim (that raised ``UnicodeEncodeError`` and turned every such request into a 500).
    Non-ASCII words are dropped; when nothing survives, a stable fallback is used.
    """
    cleaned = "".join(ch if (ch.isalnum() or ch in " -_") else " " for ch in text)
    words = [word for word in cleaned.split() if word and word.isascii()][:5]
    return "_".join(words)[:40] or "script"


async def _synthesize_mp3(text: str, voice: str, rate: str, volume: str) -> bytes:
    """Stream the MP3 audio chunks from edge-tts into memory (no temp file)."""
    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            buffer.extend(chunk["data"])
    return bytes(buffer)


def _mp3_to_wav(mp3: bytes) -> bytes:
    """Decode the MP3 and re-encode it as 24 kHz / 16-bit / mono PCM WAV."""
    decoded = miniaudio.decode(
        mp3,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=WAV_SAMPLE_RATE,
    )
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(WAV_SAMPLE_RATE)
        handle.writeframes(decoded.samples.tobytes())
    return out.getvalue()


@router.post("/synthesize")
async def synthesize(payload: TTSRequest, _session: PbxSession = Depends(require_session)) -> Response:
    """Generate audio for the given script and return it as the response body."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": "Please provide a script to convert."},
        )

    genders = VOICE_MAPPING.get(payload.language)
    if genders is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_request",
                "message": f"Unknown language '{payload.language}'. Choose one of: {', '.join(VOICE_MAPPING)}.",
            },
        )
    voice = genders.get(payload.gender)
    if voice is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_request",
                "message": (
                    f"Unknown gender '{payload.gender}' for {payload.language}. "
                    f"Choose one of: {', '.join(genders)}."
                ),
            },
        )

    fmt = next((item for item in FORMATS if item["id"] == payload.format), None)
    if fmt is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bad_request",
                "message": f"Unknown format '{payload.format}'. Choose one of: {', '.join(item['id'] for item in FORMATS)}.",
            },
        )

    tone_rate, tone_volume = _apply_tone(payload.tone)
    rate_value = max(MIN_RATE, min(MAX_RATE, int(payload.rate) + tone_rate))
    volume_value = max(MIN_VOLUME, min(MAX_VOLUME, tone_volume))
    rate_label = _signed(rate_value, "%")
    volume_label = _signed(volume_value, "%")

    started = time.perf_counter()
    try:
        mp3 = await _synthesize_mp3(text, voice, rate_label, volume_label)
    except Exception as exc:  # noqa: BLE001 - the network / Edge service can fail in many ways
        logger.warning("tts synthesis failed (%s/%s): %s", voice, rate_label, exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "tts_error",
                "message": (
                    "Voice generation failed. Check the container's internet access to "
                    f"speech.platform.bing.com ({type(exc).__name__}: {exc})."
                ),
            },
        ) from exc

    if not mp3:
        raise HTTPException(
            status_code=502,
            detail={"code": "tts_error", "message": "The voice service returned no audio for this script."},
        )

    if fmt["id"] == "wav":
        try:
            audio = _mp3_to_wav(mp3)
        except Exception as exc:  # noqa: BLE001 - decoding a malformed stream must not 500
            logger.warning("wav transcode failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail={"code": "tts_error", "message": f"Could not convert the audio to WAV ({type(exc).__name__}: {exc})."},
            ) from exc
    else:
        audio = mp3

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    tone = next((item for item in TONE_PRESETS if item["id"] == payload.tone), TONE_PRESETS[0])
    filename = f"tts_{payload.language.lower()}_{payload.gender.lower()}_{tone['id']}_{_safe_slug(text)}.{fmt['extension']}"
    logger.info(
        "tts ok: %s chars, voice=%s tone=%s rate=%s volume=%s format=%s, %d bytes in %dms",
        len(text),
        voice,
        tone["id"],
        rate_label,
        volume_label,
        fmt["id"],
        len(audio),
        elapsed_ms,
    )
    return Response(
        content=audio,
        media_type=fmt["mediaType"],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-TTS-Filename": filename,
            "X-TTS-Bytes": str(len(audio)),
            "X-TTS-Voice": voice,
            "X-TTS-Rate": rate_label,
            "X-TTS-Volume": volume_label,
            "X-TTS-Tone": tone["id"],
            "X-TTS-Format": fmt["id"],
            "X-TTS-Elapsed-Ms": str(elapsed_ms),
            "Cache-Control": "no-store",
        },
    )
