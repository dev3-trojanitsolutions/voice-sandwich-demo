"""
Speech to text on this Mac, through the local voice service
(components/voice/server.py).

LocalSTT has the same methods as AssemblyAISTT, so _stt_stream can use either.
The service only turns a piece of audio into text, so the turns are found
here: a simple voice activity check on the level of each 20 ms frame.

- Speech starts after START_MS of loud frames. The frames just before it are
  kept, so the first word is not cut.
- While the customer speaks, the speech so far is sent every PARTIAL_MS and
  the text comes back as stt_chunk. Text, not just sound, is what lets the
  agent stop for the customer, so a cough does not interrupt it.
- The turn ends after SILENCE_MS of quiet frames, and the whole turn comes
  back as stt_output.
"""

import array
import asyncio
import math
import os
from collections import deque
from typing import AsyncIterator, Optional

import httpx

from events import STTChunkEvent, STTEvent, STTOutputEvent
from local_tts import LOCAL_VOICE_URL

FRAME_MS = 20
START_MS = 200
PREROLL_MS = 300
PARTIAL_MS = 500
SILENCE_MS = int(os.getenv("LOCAL_STT_SILENCE_MS", "600"))
MAX_TURN_S = 30
# A frame is speech when it is this many times louder than the noise floor,
# and at least MIN_LEVEL (16-bit RMS, about -42 dBFS)
SPEECH_RATIO = 3.0
MIN_LEVEL = 250.0


class LocalSTT:
    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._frame_bytes = sample_rate * FRAME_MS // 1000 * 2
        self._client = httpx.AsyncClient(timeout=30)
        # (final, pcm) pieces to transcribe, in order; None ends the stream
        self._jobs: asyncio.Queue[Optional[tuple[bool, bytes]]] = asyncio.Queue()
        self._rest = b""
        self._preroll: deque[bytes] = deque(maxlen=PREROLL_MS // FRAME_MS)
        self._speech = bytearray()
        self._in_speech = False
        self._loud_ms = 0
        self._quiet_ms = 0
        self._since_partial_ms = 0
        self._floor = MIN_LEVEL / SPEECH_RATIO
        self._closed = False

    async def send_audio(self, audio_chunk: bytes) -> None:
        data = self._rest + audio_chunk
        cut = len(data) - len(data) % self._frame_bytes
        self._rest = data[cut:]
        for start in range(0, cut, self._frame_bytes):
            self._frame(data[start : start + self._frame_bytes])

    async def receive_events(self) -> AsyncIterator[STTEvent]:
        try:
            while (job := await self._jobs.get()) is not None:
                final, pcm = job
                # A newer piece is waiting: this partial is out of date
                if not final and not self._jobs.empty():
                    continue
                text = await self._transcribe(pcm)
                if final and text:
                    yield STTOutputEvent.create(text)
                elif text:
                    yield STTChunkEvent.create(text)
        finally:
            await self._client.aclose()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._jobs.put_nowait(None)

    def _frame(self, frame: bytes) -> None:
        samples = array.array("h", frame)
        level = math.sqrt(sum(s * s for s in samples) / len(samples))
        loud = level > max(self._floor * SPEECH_RATIO, MIN_LEVEL)
        if not loud:
            self._floor = 0.95 * self._floor + 0.05 * level

        if not self._in_speech:
            self._preroll.append(frame)
            self._loud_ms = self._loud_ms + FRAME_MS if loud else max(0, self._loud_ms - FRAME_MS)
            if self._loud_ms >= START_MS:
                self._in_speech = True
                self._speech = bytearray(b"".join(self._preroll))
                self._preroll.clear()
                self._quiet_ms = 0
                self._since_partial_ms = 0
            return

        self._speech += frame
        self._quiet_ms = 0 if loud else self._quiet_ms + FRAME_MS
        self._since_partial_ms += FRAME_MS
        too_long = len(self._speech) >= MAX_TURN_S * self.sample_rate * 2
        if self._quiet_ms >= SILENCE_MS or too_long:
            self._jobs.put_nowait((True, bytes(self._speech)))
            self._in_speech = False
            self._loud_ms = 0
            self._speech = bytearray()
        elif self._since_partial_ms >= PARTIAL_MS:
            self._since_partial_ms = 0
            self._jobs.put_nowait((False, bytes(self._speech)))

    async def _transcribe(self, pcm: bytes) -> str:
        try:
            response = await self._client.post(f"{LOCAL_VOICE_URL}/transcribe", content=pcm)
            response.raise_for_status()
            return response.json().get("text", "").strip()
        except (httpx.HTTPError, ValueError) as e:
            print(f"Local STT: can't transcribe ({e})")
            return ""
