"""
The local (Ollama) mode as voice to voice.

The local model can't hear or speak, so the session puts speech to text in
front of it and text to speech after it. With the voice service running and
a desk voice chosen, all three run on this Mac. Like the Gemini Live mode:

- The agent greets the customer first.
- The customer can speak over the agent. The agent stops talking at once,
  the client drops the audio it has queued (the interrupted event), and the
  agent answers the new words.
- While the agent is busy, words like "okay" or "hello" do not stop it, and
  are not a turn. Otherwise each "hello?" in a slow reply starts the reply
  again.
- After a long silence the agent checks in.

Three tasks feed one queue of events to the client: STT events, the agent
turns (model text and tools), and the TTS audio. The agent turns run one at a
time, so the history of OllamaHarness stays in order.
"""

import asyncio
import contextlib
import re
import time
from typing import AsyncIterator, Callable, Optional

from cartesia_tts import CartesiaTTS
from events import AgentEndEvent, InterruptedEvent, VoiceAgentEvent
from gemini_live import IdleWatch
from ollama_harness import OllamaHarness
from utils import split_speakable
import voices

# Put in the turn queue to check on a quiet customer
NUDGE = object()

# Words that only show the customer is listening or waiting
FILLERS = {
    "ok", "okay", "hmm", "hm", "mm", "mhm", "uh", "um", "ah", "oh", "hello",
    "hi", "hey", "yeah", "right", "sure", "fine", "haan", "ha", "acha", "achha",
}


def is_filler(text: str) -> bool:
    words = re.findall(r"[a-z']+", text.lower())
    return all(word in FILLERS for word in words)


class LocalLiveSession:
    """One customer call with the local model."""

    def __init__(self, extra_tools: list[Callable[..., str]]):
        self.harness = OllamaHarness(extra_tools=extra_tools)
        self.tts = voices.make_tts() or CartesiaTTS()
        self.idle = IdleWatch()
        self._out: asyncio.Queue[Optional[VoiceAgentEvent]] = asyncio.Queue()
        self._turns: asyncio.Queue = asyncio.Queue()
        # The agent turn in progress, and the TTS context it speaks in
        self._turn_running = False
        self._context_id: Optional[str] = None
        # Set by a barge-in: the rest of the cut turn is not spoken
        self._muted = False

    async def stream(
        self, stt_events: AsyncIterator[VoiceAgentEvent]
    ) -> AsyncIterator[VoiceAgentEvent]:
        """
        Transform stream: STT events → all voice agent events.

        The stream ends when the STT events end, that is when the client
        leaves.
        """
        await self.tts.connect()
        tasks = [
            asyncio.create_task(self._run(self._listen(stt_events), end=True)),
            asyncio.create_task(self._run(self._speak_turns())),
            asyncio.create_task(self._run(self._forward_audio())),
            asyncio.create_task(self._run(self._watch_idle())),
        ]
        try:
            while (event := await self._out.get()) is not None:
                self.idle.observe(event)
                yield event
        finally:
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    task.cancel()
                    await task
            await self.tts.close()

    async def _run(self, work, end: bool = False) -> None:
        """Run one task. When it fails, or the STT ends, end the stream."""
        try:
            await work
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"LocalLive: {e!r}")
            end = True
        if end:
            await self._out.put(None)

    async def _listen(self, stt_events: AsyncIterator[VoiceAgentEvent]) -> None:
        async for event in stt_events:
            busy = self._agent_busy() and not self._muted
            heard = event.type == "stt_chunk" and not is_filler(event.transcript)
            # Muted: this speech already cut the agent off
            if heard and busy:
                await self._barge_in()
            await self._out.put(event)
            if event.type == "stt_output" and not (busy and is_filler(event.transcript)):
                await self._turns.put(event.transcript)

    def _agent_busy(self) -> bool:
        """The agent is thinking, or its audio is still playing on the client."""
        return self._turn_running or self.idle.speaking_until > time.monotonic()

    async def _barge_in(self) -> None:
        self.harness.cut = True
        self._muted = True
        await self.tts.cancel(self._context_id)
        self._context_id = None
        print("LocalLive: interrupted")
        await self._out.put(InterruptedEvent.create())
        await self._out.put(AgentEndEvent.create())

    async def _speak_turns(self) -> None:
        await self._speak(self._as_stream(self.harness.greet()))
        while True:
            turn = await self._turns.get()
            if turn is NUDGE:
                await self._speak(self._as_stream(self.harness.nudge()))
                continue
            # Words heard while the agent finished a cut turn are one turn
            parts = [turn]
            while not self._turns.empty():
                more = self._turns.get_nowait()
                if more is not NUDGE:
                    parts.append(more)
            await self._speak(self.harness.respond(" ".join(parts)))

    async def _speak(self, events: AsyncIterator[VoiceAgentEvent]) -> None:
        """Send one agent turn to the client, and its text to the TTS a
        sentence at a time."""
        self._turn_running = True
        self._muted = False
        buffer = ""
        try:
            async for event in events:
                if event.type in ("tool_call", "tool_result"):
                    # Tools that ran are real, even in a cut turn
                    await self._out.put(event)
                elif self._muted:
                    continue
                elif event.type == "agent_chunk":
                    await self._out.put(event)
                    ready, buffer = split_speakable(buffer + event.text)
                    if ready:
                        self._context_id = self._context_id or self.tts.new_context_id()
                        await self.tts.send_text(ready, self._context_id, continue_=True)
                elif event.type == "agent_end":
                    if self._context_id:
                        await self.tts.send_text(buffer, self._context_id, continue_=False)
                    else:
                        await self.tts.send_text(buffer)
                    await self._out.put(event)
        finally:
            self._turn_running = False
            self._context_id = None

    async def _forward_audio(self) -> None:
        async for event in self.tts.receive_events():
            if not self._muted:
                await self._out.put(event)

    async def _watch_idle(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            if not self._turn_running and self.idle.should_nudge():
                self.idle.nudged = True
                self.idle.awaiting_reply = True
                await self._turns.put(NUDGE)

    @staticmethod
    async def _as_stream(events: list[VoiceAgentEvent]) -> AsyncIterator[VoiceAgentEvent]:
        for event in events:
            yield event
