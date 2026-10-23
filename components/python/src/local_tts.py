"""
Text to speech with a voice saved on the desk, through the local voice
service (components/voice/server.py).

LocalTTS has the same methods as CartesiaTTS, so _tts_stream can use either.
The service streams the audio of each request as it is generated, so the
first audio arrives in well under a second. Text that arrives while a piece
is being spoken is joined into the next request. cancel() stops the speech
at once, when the customer speaks over the agent.
"""

import asyncio
import os
from typing import AsyncIterator, Optional

import httpx

from events import TTSChunkEvent

LOCAL_VOICE_URL = os.getenv("LOCAL_VOICE_URL", "http://127.0.0.1:8001")


async def service_status() -> dict:
    """The voice service status: {'running', 'ready', 'stt_ready', 'error'}.
    The error is why the models could not load, or empty."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            health = (await client.get(f"{LOCAL_VOICE_URL}/health")).json()
        return {
            "running": True,
            "ready": bool(health.get("ready")),
            "stt_ready": bool(health.get("stt_ready")),
            "error": health.get("error", ""),
        }
    except (httpx.HTTPError, ValueError):
        return {"running": False, "ready": False, "stt_ready": False, "error": ""}


async def speak_stream(
    client: httpx.AsyncClient, sample: str, text: str
) -> AsyncIterator[bytes]:
    """Raw 16-bit PCM at 24 kHz for the text, in the voice of the sample, in
    parts as the service generates them."""
    body = {"ref_path": sample, "text": text}
    async with client.stream("POST", f"{LOCAL_VOICE_URL}/speak", json=body) as response:
        if response.status_code != 200:
            detail = (await response.aread()).decode(errors="replace")
            raise RuntimeError(detail)
        # Keep each part a whole number of 16-bit samples
        rest = b""
        async for data in response.aiter_bytes():
            data = rest + data
            cut = len(data) - len(data) % 2
            rest = data[cut:]
            if cut:
                yield data[:cut]


async def speak(client: httpx.AsyncClient, sample: str, text: str) -> bytes:
    """All the PCM for the text at once."""
    return b"".join([part async for part in speak_stream(client, sample, text)])


class LocalTTS:
    def __init__(self, sample: str):
        self.sample = sample
        self._client = httpx.AsyncClient(timeout=60)
        self._queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self._counter = 0
        # Raised by cancel(), so the speech in progress stops
        self._generation = 0

    def new_context_id(self) -> str:
        self._counter += 1
        return f"local_{self._counter}"

    async def connect(self) -> None:
        """Nothing to open. The service keeps the models loaded."""

    async def send_text(
        self,
        text: Optional[str],
        context_id: Optional[str] = None,
        continue_: bool = False,
    ) -> None:
        if text and text.strip():
            await self._queue.put(text)

    async def cancel(self, context_id: Optional[str] = None) -> None:
        """Drop the text not yet spoken and stop the piece being spoken."""
        self._generation += 1
        while not self._queue.empty():
            if self._queue.get_nowait() is None:
                self._queue.put_nowait(None)
                break

    async def receive_events(self) -> AsyncIterator[TTSChunkEvent]:
        while True:
            text = await self._queue.get()
            if text is None:
                return
            # Join the text that arrived while the last piece was spoken
            closing = False
            while not self._queue.empty():
                more = self._queue.get_nowait()
                if more is None:
                    closing = True
                    break
                text += more
            generation = self._generation
            try:
                async for pcm in speak_stream(self._client, self.sample, text.strip()):
                    if generation != self._generation:
                        break
                    yield TTSChunkEvent.create(pcm)
            except (httpx.HTTPError, RuntimeError) as e:
                print(f"Local voice: can't speak ({e})")
            if closing:
                return

    async def close(self) -> None:
        await self._queue.put(None)
        await self._client.aclose()
