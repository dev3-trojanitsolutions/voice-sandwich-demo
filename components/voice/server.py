"""
Local voice service: cloned voices, accents and speech to text, on this Mac.

It runs in its own environment (PyTorch and MLX), so its packages cannot
clash with the main server. The main server stores the voices and calls this
service over HTTP on port 8001. Two models do the work:

- OmniVoice makes an accent version of a voice. It clones the voice from a
  recording and speaks a sample line with the chosen accent. It is slow
  (about 10-20 s), so it runs only when staff add an accent on the desk.
  It runs on the GPU with MLX.
- Pocket TTS (Kyutai) speaks during calls. It clones a voice from one sample
  (the recording or an accent version) and streams the audio: the first
  part is ready in about 0.03 s. It runs on the CPU, so it does not slow
  down the local language model on the GPU.
- Parakeet (or Whisper) turns the customer's speech into text, so the
  local mode needs no cloud STT. It runs on the GPU with MLX and
  transcribes a few seconds of speech in well under a second.

Pocket TTS needs the Hugging Face terms accepted at
https://huggingface.co/kyutai/pocket-tts and a login (uvx hf auth login).
"""

import asyncio
import contextlib
import os
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

ACCENT_MODEL = os.getenv("LOCAL_ACCENT_MODEL", "mlx-community/OmniVoice-bf16")
STT_MODEL = os.getenv("LOCAL_STT_MODEL", "mlx-community/parakeet-tdt-0.6b-v3")
SAMPLE_RATE = 24000
# The STT models take 16 kHz audio
STT_SAMPLE_RATE = 16000
# OmniVoice steps: more steps sound better but take longer
ACCENT_STEPS = 16
REF_MAX_SECONDS = 15.0

ACCENTS = (
    "american",
    "british",
    "australian",
    "canadian",
    "indian",
    "chinese",
    "korean",
    "japanese",
    "portuguese",
    "russian",
)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Load in the background, so /health answers while the models load
    threading.Thread(target=_load_models, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)
# One job per model at a time. The two models use different hardware, so
# speech on a call never waits for an accent being made.
_accent_lock = threading.Lock()
_speech_lock = threading.Lock()
_stt_lock = threading.Lock()
_models: dict = {}
_load_error = ""
# Pocket TTS voice state per sample file, keyed by path and file time
_voices: dict[tuple[str, float], dict] = {}


def _load_models() -> None:
    global _load_error
    from mlx_audio.stt.utils import load_model as load_stt_model
    from mlx_audio.tts.utils import load_model
    from pocket_tts import TTSModel

    try:
        # Speech to text first: a call needs it before it needs a voice
        start = time.monotonic()
        _models["stt"] = load_stt_model(STT_MODEL)
        _transcribe(np.zeros(STT_SAMPLE_RATE // 2, dtype=np.float32))
        print(f"Voice service: {STT_MODEL} loaded in {time.monotonic() - start:.1f}s")

        start = time.monotonic()
        speech = TTSModel.load_model()
        if not speech.has_voice_cloning:
            raise RuntimeError(
                "Pocket TTS can't download its voice cloning weights. Accept the "
                "terms at https://huggingface.co/kyutai/pocket-tts, then run "
                "'uvx hf auth login' and restart the service."
            )
        # The first generation is slower. Do it now, not on a call.
        for _ in speech.generate_audio_stream(speech.get_state_for_audio_prompt("alba"), "Hello."):
            pass
        _models["speech"] = speech
        print(f"Voice service: Pocket TTS loaded in {time.monotonic() - start:.1f}s")

        start = time.monotonic()
        _models["accent"] = load_model(ACCENT_MODEL)
        print(f"Voice service: {ACCENT_MODEL} loaded in {time.monotonic() - start:.1f}s")
    except Exception as e:
        _load_error = str(e)
        print(f"Voice service: can't load the models. {e}")
        return
    _models["ready"] = True
    print("Voice service: ready")


def _model(key: str):
    if _load_error:
        raise HTTPException(503, _load_error)
    model = _models.get(key)
    if model is None or "ready" not in _models:
        raise HTTPException(503, "The voice models are still loading. Try again in a minute.")
    return model


def _check_file(path: str) -> None:
    if not Path(path).is_file():
        raise HTTPException(404, f"No sample file at {path}.")


class AccentIn(BaseModel):
    ref_path: str
    ref_text: str
    accent: str
    text: str
    out_path: str


class SpeakIn(BaseModel):
    # The sample to clone: a recording or an accent version
    ref_path: str
    text: str


@app.get("/health")
async def health():
    return {"ready": "ready" in _models, "stt_ready": "stt" in _models, "error": _load_error}


def _make_accent(body: AccentIn) -> float:
    from mlx_audio.tts.models.omnivoice.utils import create_voice_clone_prompt

    model = _model("accent")
    with _accent_lock:
        start = time.monotonic()
        ref_tokens = create_voice_clone_prompt(
            body.ref_path,
            tokenizer=model.audio_tokenizer,
            max_duration_s=REF_MAX_SECONDS,
        )
        parts = [
            np.array(result.audio)
            for result in model.generate(
                text=body.text,
                language="english",
                instruct=f"{body.accent} accent",
                ref_text=body.ref_text,
                ref_tokens=ref_tokens,
                num_steps=ACCENT_STEPS,
            )
        ]
        audio = np.concatenate(parts)
        Path(body.out_path).parent.mkdir(parents=True, exist_ok=True)
        sf.write(body.out_path, audio, SAMPLE_RATE, subtype="PCM_16")
        print(f"Voice service: {body.accent} accent made in {time.monotonic() - start:.1f}s")
    return len(audio) / SAMPLE_RATE


@app.post("/accent")
async def make_accent(body: AccentIn):
    if body.accent not in ACCENTS:
        raise HTTPException(400, f"Unknown accent '{body.accent}'.")
    _check_file(body.ref_path)
    seconds = await asyncio.to_thread(_make_accent, body)
    return {"seconds": round(seconds, 1)}


def _voice_state(model, path: str) -> dict:
    key = (path, Path(path).stat().st_mtime)
    if key not in _voices:
        _voices[key] = model.get_state_for_audio_prompt(path)
    return _voices[key]


def _stream_speech(
    body: SpeakIn,
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    stop: threading.Event,
) -> None:
    """Generate in a thread and pass each part to the queue as 16-bit PCM.
    Stops when the client goes away, so the next speech does not wait."""
    model = _models["speech"]
    try:
        with _speech_lock:
            state = _voice_state(model, body.ref_path)
            for chunk in model.generate_audio_stream(state, body.text):
                if stop.is_set():
                    break
                audio = np.clip(chunk.numpy().reshape(-1), -1.0, 1.0)
                pcm = (audio * 32767).astype("<i2").tobytes()
                loop.call_soon_threadsafe(queue.put_nowait, pcm)
    except Exception as e:
        print(f"Voice service: can't speak. {e}")
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, None)


@app.post("/speak")
async def speak(body: SpeakIn):
    """Speak text in the voice of one sample. Streams raw 16-bit PCM at
    24 kHz, part by part, as it is generated."""
    _model("speech")
    _check_file(body.ref_path)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    stop = threading.Event()
    if body.text.strip():
        threading.Thread(
            target=_stream_speech, args=(body, loop, queue, stop), daemon=True
        ).start()
    else:
        queue.put_nowait(None)

    async def parts():
        try:
            while (pcm := await queue.get()) is not None:
                yield pcm
        finally:
            stop.set()

    return StreamingResponse(parts(), media_type="audio/L16")


def _transcribe(audio: np.ndarray) -> str:
    import mlx.core as mx

    with _stt_lock:
        result = _models["stt"].generate(mx.array(audio))
    return result.text.strip()


@app.post("/transcribe")
async def transcribe(request: Request):
    """The text of the speech in the body: raw 16-bit PCM at 16 kHz."""
    if _load_error:
        raise HTTPException(503, _load_error)
    if "stt" not in _models:
        raise HTTPException(503, "The speech to text model is still loading.")
    data = await request.body()
    data = data[: len(data) - len(data) % 2]
    if not data:
        return {"text": ""}
    audio = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768
    return {"text": await asyncio.to_thread(_transcribe, audio)}


if __name__ == "__main__":
    port = int(os.getenv("LOCAL_VOICE_PORT", "8001"))
    uvicorn.run(app, host="127.0.0.1", port=port)
