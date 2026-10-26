"""
Cartesia Text-to-Speech Streaming

Python implementation of Cartesia's Sonic streaming TTS API.
Converts text to PCM audio in real-time using WebSocket streaming.

Input: Text strings
Output: TTS events (tts_chunk for audio chunks)
"""

import asyncio
import base64
import contextlib
import json
import os
import time
from typing import AsyncIterator, Literal, Optional

import websockets
from websockets.client import WebSocketClientProtocol

import credentials
from events import TTSChunkEvent


class CartesiaTTS:
    _ws: Optional[WebSocketClientProtocol]
    _connection_signal: asyncio.Event
    _close_signal: asyncio.Event

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        model_id: str = "sonic-3",
        sample_rate: int = 24000,
        encoding: Literal[
            "pcm_s16le", "pcm_f32le", "pcm_mulaw", "pcm_alaw"
        ] = "pcm_s16le",
        language: str = "en",
        cartesia_version: str = "2025-04-16",
    ):
        self.api_key = api_key or credentials.key("cartesia")
        if not self.api_key:
            raise ValueError("Add the Cartesia API key in Settings → API Keys")

        # CARTESIA_VOICE_ID picks the voice, for example your own cloned voice
        self.voice_id = (
            voice_id
            or os.getenv("CARTESIA_VOICE_ID")
            or "f6ff7c0c-e396-40a9-a70b-f7607edb6937"
        )
        self.model_id = model_id
        self.sample_rate = sample_rate
        self.encoding = encoding
        self.language = language
        self.cartesia_version = cartesia_version
        self._ws = None
        self._connection_signal = asyncio.Event()
        self._close_signal = asyncio.Event()
        self._context_counter = 0
        # Audio of these contexts still on the way is dropped
        self._cancelled: set[str] = set()

    def new_context_id(self) -> str:
        """
        Generate a valid context_id for Cartesia.
        Context IDs must only contain alphanumeric characters, underscores, and hyphens.
        """
        timestamp = int(time.time() * 1000)
        counter = self._context_counter
        self._context_counter += 1
        return f"ctx_{timestamp}_{counter}"

    async def connect(self) -> None:
        """Open the WebSocket now, so the first reply does not wait for it."""
        await self._ensure_connection()

    async def send_text(
        self,
        text: Optional[str],
        context_id: Optional[str] = None,
        continue_: bool = False,
    ) -> None:
        """
        Send text to synthesize.

        To stream one reply in parts, send each part with the same context_id
        and continue_=True, then end the context with continue_=False. Cartesia
        then speaks the parts as one utterance with even prosody. The closing
        call may have empty text.
        """
        if text is None:
            return

        if not text.strip() and (context_id is None or continue_):
            return

        ws = await self._ensure_connection()

        payload = {
            "model_id": self.model_id,
            "transcript": text,
            "voice": {
                "mode": "id",
                "id": self.voice_id,
            },
            "output_format": {
                "container": "raw",
                "encoding": self.encoding,
                "sample_rate": self.sample_rate,
            },
            "language": self.language,
            "context_id": context_id or self.new_context_id(),
            "continue": continue_,
        }
        await ws.send(json.dumps(payload))

    async def cancel(self, context_id: Optional[str] = None) -> None:
        """Stop speaking one context, when the customer speaks over the agent."""
        if not context_id:
            return
        self._cancelled.add(context_id)
        if self._ws and self._ws.close_code is None:
            await self._ws.send(json.dumps({"context_id": context_id, "cancel": True}))

    async def receive_events(self) -> AsyncIterator[TTSChunkEvent]:
        while not self._close_signal.is_set():
            _, pending = await asyncio.wait(
                [
                    asyncio.create_task(self._close_signal.wait()),
                    asyncio.create_task(self._connection_signal.wait()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )

            with contextlib.suppress(asyncio.CancelledError):
                for task in pending:
                    task.cancel()

            if self._close_signal.is_set():
                break

            if self._ws and self._ws.close_code is None:
                self._connection_signal.clear()
                try:
                    async for raw_message in self._ws:
                        try:
                            message = json.loads(raw_message)
                            if message.get("context_id") in self._cancelled:
                                continue
                            if "data" in message and message["data"] is not None:
                                audio_chunk = base64.b64decode(message["data"])
                                if audio_chunk:
                                    yield TTSChunkEvent.create(audio_chunk)
                            # "done" ends one context only. Keep reading, so
                            # one connection serves the whole session.
                            if "error" in message and message["error"]:
                                print(f"[DEBUG] Cartesia error: {message['error']}")
                                break
                        except json.JSONDecodeError as e:
                            print(f"[DEBUG] Cartesia JSON decode error: {e}")
                            continue
                except websockets.exceptions.ConnectionClosed:
                    print("Cartesia: WebSocket connection closed")
                finally:
                    if self._ws and self._ws.close_code is None:
                        await self._ws.close()
                    self._ws = None

    async def close(self) -> None:
        if self._ws and self._ws.close_code is None:
            await self._ws.close()
        self._ws = None
        self._close_signal.set()

    async def _ensure_connection(self) -> WebSocketClientProtocol:
        if self._close_signal.is_set():
            raise RuntimeError(
                "CartesiaTTS tried establishing a connection after it was closed"
            )
        if self._ws and self._ws.close_code is None:
            return self._ws

        url = (
            f"wss://api.cartesia.ai/tts/websocket"
            f"?api_key={self.api_key}&cartesia_version={self.cartesia_version}"
        )
        self._ws = await websockets.connect(url)

        self._connection_signal.set()
        return self._ws
