"""
Voices saved on the desk: a person's recorded voice and its accent versions.

Staff record themselves reading SCRIPT. The recording is the original voice.
The local voice service (components/voice/server.py) then makes accent
versions: it clones the recording and speaks SAMPLE_LINE with the accent.
Each version is saved as its own voice, with the original as its parent.

One voice can be active: a recorded voice or an accent version.
The sandwich and ollama pipelines then speak with it, through LocalTTS. With
no active voice they use Cartesia.
"""

import io
import wave

import httpx

import store
from local_tts import LOCAL_VOICE_URL, LocalTTS, speak

# What staff read when they record. The service needs the exact words.
SCRIPT = (
    "Welcome to Ustad Hotel. Today we have Chicken 65, Mutton Biriyani and "
    "fresh lime soda. May I know your name and your delivery address, please?"
)
# What an accent version says. About 9 seconds, the length the service
# clones best from.
SAMPLE_LINE = (
    "Welcome to Ustad Hotel. Our Chicken 65 and Mutton Biriyani are freshly "
    "made today. May I know your name and delivery address, please?"
)
PREVIEW_LINE = "Thank you for your order. Would you like to pay by UPI or credit card?"

ACCENTS = {
    "american": "American",
    "british": "British",
    "australian": "Australian",
    "canadian": "Canadian",
    "indian": "Indian",
    "chinese": "Chinese",
    "korean": "Korean",
    "japanese": "Japanese",
    "portuguese": "Portuguese",
    "russian": "Russian",
}

SAMPLE_RATE = 24000
MIN_SECONDS = 6
MAX_SECONDS = 15
NAME_MAX = 40
ACTIVE_KEY = "voice_id"


def _public(voice: dict) -> dict:
    return {
        "id": voice["id"],
        "name": voice["name"],
        "accent": voice["accent"],
        "accent_label": ACCENTS.get(voice["accent"], "Original"),
        "created_at": voice["created_at"],
    }


def list_grouped() -> list[dict]:
    """Original voices, each with its accent versions."""
    voices = store.list_voices()
    groups = []
    for voice in voices:
        if voice["parent_id"] is None:
            versions = [_public(v) for v in voices if v["parent_id"] == voice["id"]]
            groups.append(_public(voice) | {"versions": versions})
    return groups


def active_voice() -> dict | None:
    value = store.get_setting(ACTIVE_KEY)
    return store.get_voice(int(value)) if value and value.isdigit() else None


def set_active(voice_id: int | None) -> None:
    store.set_setting(ACTIVE_KEY, str(voice_id) if voice_id else "")


def make_tts():
    """The TTS for a new session: the active voice, or None for Cartesia."""
    voice = active_voice()
    if not voice:
        return None
    try:
        httpx.get(f"{LOCAL_VOICE_URL}/health", timeout=1)
    except httpx.HTTPError:
        print(
            f"Local voice: the voice service is off, so '{voice['name']}' can't "
            "speak. Start it with 'make dev-voice', or restart 'make dev-py'."
        )
    return LocalTTS(voice["file"])


def check_wav(data: bytes) -> float:
    """Check a recording from the desk and return its length in seconds.
    Raises ValueError with a message for staff."""
    try:
        with wave.open(io.BytesIO(data)) as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            seconds = wav.getnframes() / rate
    except (wave.Error, EOFError):
        raise ValueError("The recording is not a WAV file.")
    if channels != 1 or width != 2 or rate != SAMPLE_RATE:
        raise ValueError("The recording must be 16-bit mono WAV at 24 kHz.")
    if seconds < MIN_SECONDS:
        raise ValueError(
            f"The recording is only {seconds:.1f} seconds. Read the whole "
            f"script, so it is at least {MIN_SECONDS} seconds."
        )
    if seconds > MAX_SECONDS:
        raise ValueError(
            f"The recording is {seconds:.1f} seconds. Keep it under {MAX_SECONDS} seconds."
        )
    return seconds


def add_recording(name: str, data: bytes) -> dict:
    check_wav(data)
    voice = store.add_voice(name, SCRIPT)
    with open(voice["file"], "wb") as f:
        f.write(data)
    return _public(voice) | {"versions": []}


async def add_accent(parent: dict, accent: str) -> dict:
    """Make an accent version of an original voice. Takes 10-20 seconds."""
    for existing in store.list_voices():
        if existing["parent_id"] == parent["id"] and existing["accent"] == accent:
            label = ACCENTS[accent]
            article = "an" if label[0] in "AEIOU" else "a"
            raise ValueError(f"{parent['name']} already has {article} {label} version.")
    voice = store.add_voice(parent["name"], SAMPLE_LINE, accent, parent["id"])
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{LOCAL_VOICE_URL}/accent",
                json={
                    "ref_path": parent["file"],
                    "ref_text": parent["ref_text"],
                    "accent": accent,
                    "text": SAMPLE_LINE,
                    "out_path": voice["file"],
                },
            )
        if response.status_code != 200:
            raise RuntimeError(response.json().get("detail", response.text))
    except Exception:
        store.delete_voice(voice["id"])
        raise
    return _public(voice)


async def preview(voice: dict) -> bytes:
    """PREVIEW_LINE spoken the way callers hear this voice, as a WAV file."""
    async with httpx.AsyncClient(timeout=60) as client:
        pcm = await speak(client, voice["file"], PREVIEW_LINE)
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return out.getvalue()
