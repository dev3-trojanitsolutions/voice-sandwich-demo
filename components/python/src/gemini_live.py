"""
Gemini Live speech-to-speech stage.

This module replaces the whole STT → Agent → TTS "sandwich" with a single
connection to Gemini Live. The model hears the user's audio directly and
speaks its reply directly. Gemini's server messages are translated into the
same VoiceAgentEvent types the sandwich pipeline emits, so the web client works
unchanged.

Audio formats match the existing web client:
- Input: 16-bit PCM, mono, 16kHz (what the AudioWorklet already sends)
- Output: 16-bit PCM, mono, 24kHz (what the playback code already expects)
"""

import asyncio
import contextlib
import os
import time
from typing import AsyncIterator, Callable

from google import genai
from google.genai import errors, types

import credentials
from events import (
    AgentChunkEvent,
    AgentEndEvent,
    InterruptedEvent,
    STTChunkEvent,
    STTOutputEvent,
    ToolCallEvent,
    ToolResultEvent,
    TTSChunkEvent,
    VoiceAgentEvent,
)

GEMINI_LIVE_MODEL = "gemini-3.8-live"
GEMINI_VOICE = "Kore"
# Fixed language for speech output and both transcriptions.
# en-IN gives the voice an Indian English accent.
LANGUAGE_CODE = "en-IN"
INPUT_MIME_TYPE = "audio/pcm;rate=16000"

# Voice activity detection. Gemini Live defaults to HIGH start/end sensitivity,
# which replies after very short pauses. During a barge-in that makes Gemini
# start a reply, get interrupted by the rest of the user's sentence, and start
# over, so the user hears replies that skip ahead. LOW sensitivity plus a longer
# silence window waits for the user to really finish.
VAD_PREFIX_PADDING_MS = int(os.getenv("GEMINI_VAD_PREFIX_PADDING_MS", "200"))
VAD_SILENCE_DURATION_MS = int(os.getenv("GEMINI_VAD_SILENCE_MS", "700"))

# Model audio is 16-bit mono PCM at 24kHz: 48000 bytes per second of speech
OUTPUT_BYTES_PER_SECOND = 24000 * 2

# The agent speaks first when the session opens, and checks in once when the
# user stays silent for IDLE_TIMEOUT_S after the agent finishes speaking.
IDLE_TIMEOUT_S = float(os.getenv("GEMINI_IDLE_SECONDS", "8"))
GREETING_PROMPT = (
    "[The customer just connected and has not spoken yet. Greet them now by "
    'saying: "{greeting}"]'
)
IDLE_PROMPT = (
    "[The customer has been silent for a while. Check on them by saying: "
    '"Hello, are you there?"]'
)


class IdleWatch:
    """
    Tracks when the user was last heard and when the agent's audio will finish
    playing on the client, so the agent can check in after a silence.

    Gemini sends audio faster than real time, so turn_complete arrives before
    the client stops playing. The playback end is estimated from the audio
    length instead.
    """

    def __init__(self):
        now = time.monotonic()
        self.last_user_speech = now
        self.speaking_until = now
        # True while the agent owes a reply (user spoke, tool running, greeting)
        self.awaiting_reply = True
        # Check in only once per silence; reset when the user speaks
        self.nudged = False

    def observe(self, event: VoiceAgentEvent) -> None:
        now = time.monotonic()
        if event.type == "stt_chunk":
            self.last_user_speech = now
            self.awaiting_reply = True
            self.nudged = False
        elif event.type == "tool_call":
            self.awaiting_reply = True
        elif event.type == "tts_chunk":
            self.awaiting_reply = False
            seconds = len(event.audio) / OUTPUT_BYTES_PER_SECOND
            self.speaking_until = max(now, self.speaking_until) + seconds
        elif event.type == "interrupted":
            # The client dropped the queued audio
            self.speaking_until = now
        elif event.type == "agent_end":
            self.awaiting_reply = False

    def should_nudge(self) -> bool:
        if self.nudged or self.awaiting_reply:
            return False
        quiet_since = max(self.last_user_speech, self.speaking_until)
        return time.monotonic() - quiet_since >= IDLE_TIMEOUT_S


class GeminiLiveAgent:
    """
    Speech-to-speech agent backed by Gemini Live.

    Tools are plain Python functions. Their names, docstrings and type hints
    become Gemini function declarations, so the same functions can be shared
    with the sandwich pipeline's LangChain agent.
    """

    def __init__(
        self, system_prompt: str, tools: list[Callable[..., str]], greeting: str
    ):
        # The key set on the desk, or GOOGLE_API_KEY from .env
        self.client = genai.Client(api_key=credentials.gemini_key() or None)
        self.greeting_prompt = GREETING_PROMPT.format(greeting=greeting)
        self.tools = {tool.__name__: tool for tool in tools}
        self.config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=system_prompt,
            speech_config=types.SpeechConfig(
                language_code=LANGUAGE_CODE,
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=GEMINI_VOICE
                    )
                )
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=[LANGUAGE_CODE]
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=[LANGUAGE_CODE]
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=VAD_PREFIX_PADDING_MS,
                    silence_duration_ms=VAD_SILENCE_DURATION_MS,
                )
            ),
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration.from_callable_with_api_option(
                            callable=tool, api_option="GEMINI_API"
                        )
                        for tool in tools
                    ]
                )
            ],
        )

    async def stream(
        self, audio_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[VoiceAgentEvent]:
        """
        Transform stream: Audio (Bytes) → Voice Events (VoiceAgentEvent)

        Uses the same producer-consumer pattern as the sandwich STT stage:
        - Producer: A background task forwards microphone audio to Gemini.
        - Consumer: The main coroutine reads Gemini's server messages and
          yields them as voice agent events.

        Conversation history is kept by the Gemini session itself, so no
        checkpointer is needed.
        """
        async with self.client.aio.live.connect(
            model=GEMINI_LIVE_MODEL, config=self.config
        ) as session:

            async def send_audio():
                """Background task that pumps audio chunks to Gemini."""
                try:
                    async for audio_chunk in audio_stream:
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=audio_chunk, mime_type=INPUT_MIME_TYPE
                            )
                        )
                finally:
                    # Closing the session ends the consumer's receive loop
                    await session.close()

            idle = IdleWatch()

            async def watch_idle():
                """Background task that checks in when the user goes quiet."""
                while True:
                    await asyncio.sleep(0.5)
                    if idle.should_nudge():
                        idle.nudged = True
                        idle.awaiting_reply = True
                        await session.send_realtime_input(text=IDLE_PROMPT)

            # Speak first instead of waiting for the user
            await session.send_realtime_input(text=self.greeting_prompt)

            send_task = asyncio.create_task(send_audio())
            idle_task = asyncio.create_task(watch_idle())

            try:
                async for event in self._receive_events(session):
                    idle.observe(event)
                    yield event
            except errors.APIError:
                # The session was closed because the client disconnected
                if not send_task.done():
                    raise
            finally:
                for task in (send_task, idle_task):
                    with contextlib.suppress(asyncio.CancelledError):
                        task.cancel()
                        await task

    async def _receive_events(
        self, session: genai.live.AsyncSession
    ) -> AsyncIterator[VoiceAgentEvent]:
        """
        Translate Gemini server messages into voice agent events.

        Mapping:
        - input_transcription  → stt_chunk (accumulated), then stt_output
        - output_transcription → agent_chunk
        - model audio          → tts_chunk
        - tool_call            → tool_call + tool_result (tool runs here)
        - interrupted          → interrupted + agent_end (client stops playback)
        - turn_complete        → agent_end
        """
        user_transcript = ""
        user_turn_ended = False
        cancelled_tool_ids: set[str] = set()

        def end_user_turn() -> list[VoiceAgentEvent]:
            """
            Emit stt_output once, when the model starts responding.

            The transcript is cleared here, not on turn_complete, so speech that
            arrives while the model talks (a barge-in) starts the next user turn.
            """
            nonlocal user_transcript, user_turn_ended
            if user_turn_ended or not user_transcript.strip():
                return []
            user_turn_ended = True
            transcript = user_transcript.strip()
            user_transcript = ""
            return [STTOutputEvent.create(transcript)]

        # session.receive() ends after each model turn, so loop over turns
        while True:
            async for message in session.receive():
                if message.tool_call_cancellation:
                    cancelled_tool_ids.update(message.tool_call_cancellation.ids or [])

                if message.tool_call:
                    for event in end_user_turn():
                        yield event
                    async for event in self._run_tools(
                        session, message.tool_call, cancelled_tool_ids
                    ):
                        yield event

                content = message.server_content
                if not content:
                    continue

                if content.input_transcription and content.input_transcription.text:
                    user_transcript += content.input_transcription.text
                    yield STTChunkEvent.create(user_transcript.strip())

                if content.output_transcription and content.output_transcription.text:
                    for event in end_user_turn():
                        yield event
                    yield AgentChunkEvent.create(content.output_transcription.text)

                if content.model_turn:
                    for part in content.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            for event in end_user_turn():
                                yield event
                            yield TTSChunkEvent.create(part.inline_data.data)

                if content.interrupted:
                    # The model's turn was cut. Close it, and let the barge-in
                    # speech end the next user turn with its own stt_output.
                    interrupted = InterruptedEvent.create()
                    print(f"GeminiLive: interrupted at {interrupted.ts}")
                    yield interrupted
                    yield AgentEndEvent.create()
                    user_turn_ended = False

                if content.turn_complete:
                    for event in end_user_turn():
                        yield event
                    yield AgentEndEvent.create()
                    user_turn_ended = False

    async def _run_tools(
        self,
        session: genai.live.AsyncSession,
        tool_call: types.LiveServerToolCall,
        cancelled_ids: set[str],
    ) -> AsyncIterator[VoiceAgentEvent]:
        """
        Run the requested tools and send their results back to Gemini.

        Calls that Gemini cancelled (the user interrupted) are skipped, and no
        response is sent for them.
        """
        responses: list[types.FunctionResponse] = []

        for call in tool_call.function_calls or []:
            if call.id in cancelled_ids:
                continue
            args = call.args or {}
            yield ToolCallEvent.create(id=call.id or "", name=call.name, args=args)

            tool = self.tools.get(call.name)
            try:
                # Run in a thread so slow tools (e.g. knowledge search) don't
                # block the event loop while audio is streaming
                result = (
                    await asyncio.to_thread(tool, **args)
                    if tool
                    else f"Unknown tool: {call.name}"
                )
            except Exception as e:
                result = f"Error running {call.name}: {e}"

            yield ToolResultEvent.create(
                tool_call_id=call.id or "", name=call.name, result=result
            )
            responses.append(
                types.FunctionResponse(
                    id=call.id, name=call.name, response={"result": result}
                )
            )

        if responses:
            await session.send_tool_response(function_responses=responses)
