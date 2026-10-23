import asyncio
import contextlib
import functools
import os
import time
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableGenerator
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
from starlette.staticfiles import StaticFiles

from assemblyai_stt import AssemblyAISTT
from cartesia_prompts import CARTESIA_TTS_SYSTEM_PROMPT
from cartesia_tts import CartesiaTTS
from conversation_log import ConversationLog
from events import (
    AgentChunkEvent,
    AgentEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    VoiceAgentEvent,
    event_to_dict,
)
from gemini_live import GeminiLiveAgent
import auth
import brand
import credentials
import delivery
import flow
import knowledge_base
from knowledge_base import ingest, search, seed_modules
from local_live import LocalLiveSession
from local_stt import LocalSTT
from ollama_harness import warm_up
import store
import voices
from local_tts import service_status
from orders import ORDER_TOOLS, current_order, normalize_phone, start_order
from utils import merge_async_iters, split_speakable

load_dotenv()

# The first start copies knowledge/*.md into modules. Then the index is rebuilt
# from the modules on every start.
seed_modules()
print(f"Knowledge base: {ingest()} chunks")
delivery.seed()
auth.seed()
credentials.import_env_key()
store.end_open_conversations()

# Static files are served from the shared web build output
STATIC_DIR = Path(__file__).parent.parent.parent / "web" / "dist"

if not STATIC_DIR.exists():
    raise RuntimeError(
        f"Web build not found at {STATIC_DIR}. "
        "Run 'make build-web' or 'make dev-py' from the project root."
    )

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # The desk login cookie is only sent from the same origin
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_login(request: Request, call_next):
    """The desk and its API need a user with the right permission (auth.py)."""
    access = await asyncio.to_thread(auth.check_access, request)
    if access.redirect:
        return RedirectResponse(access.redirect, status_code=303)
    if not access.allowed:
        return JSONResponse({"detail": access.detail}, status_code=access.status)
    return await call_next(request)


app.include_router(auth.router)


def search_knowledge(query: str) -> str:
    """Search the shop's menu, prices, allergen info and FAQ (hours, delivery,
    payment, refunds). Use this before answering any question about these."""
    return search(query)


TOOLS = [*ORDER_TOOLS, search_knowledge]

SHOP_PROMPT = """
You are a helpful order assistant at {shop}. Your goal
is to take the customer's order.
Be concise, warm and friendly. Ask one thing at a time.
Always speak and reply in English only, even if the customer uses another language.
Speak with a natural Indian English accent and say all prices in rupees.

Greet the customer by saying: "{greeting}"
{steps}
Tool results tell you if something is missing or wrong; follow them.
Until the OTP confirms the order, the customer can cancel it: call cancel_order.
After that, it cannot be cancelled.
The order total comes from add_to_order and get_order_total; never add up prices
yourself. Tell the customer the total before they choose a payment method.

For any question about prices, ingredients, allergens, hours, delivery, payment or
refunds, call search_knowledge first and answer only from its result. If it does not
contain the answer, say you don't know.
{contact}
Menu: {menu}.
"""


def build_shop_prompt(steps: list[flow.Step]) -> str:
    """The system prompt for Gemini and Claude, from the business details, the
    flow and the menu modules set on the desk."""
    return SHOP_PROMPT.format(
        shop=brand.shop(),
        contact=brand.contact(),
        greeting=flow.greeting(steps),
        steps=flow.steps_prompt(steps),
        menu=knowledge_base.menu_overview() or "call search_knowledge for the menu",
    )


# Which voice pipeline to run:
# - "sandwich": AssemblyAI STT → Claude agent → Cartesia TTS
# - "ollama": voice to voice around a local Ollama model in a harness: STT and
#   TTS on this Mac when the voice service runs (else AssemblyAI and Cartesia),
#   and the customer can speak over the agent
# - "realtime": Gemini Live speech-to-speech
# PIPELINE sets the default. The desk page can switch it at runtime; the
# choice is saved in the store and applies to the next session.
PIPELINES = ("sandwich", "ollama", "realtime")
PIPELINE = os.getenv("PIPELINE", "realtime")

if PIPELINE not in PIPELINES:
    raise RuntimeError(
        f"Unknown PIPELINE '{PIPELINE}'. Use 'sandwich', 'ollama' or 'realtime'."
    )

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")

# LLM for the sandwich pipeline: "anthropic" (Claude) or "ollama" (local model)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")


def current_pipeline() -> str:
    saved = store.get_setting("pipeline")
    return saved if saved in PIPELINES else PIPELINE


def _build_llm():
    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=OLLAMA_MODEL,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            reasoning=False,  # no thinking tokens; keeps time-to-first-word low
            keep_alive=-1,  # keep the model loaded between turns
            num_ctx=4096,
        )
    return "anthropic:claude-haiku-4-5"


# Agents are built on first use, so a switch on the desk page needs no restart.
# They are cached by prompt: a flow or menu change on the desk builds a new one.
@functools.lru_cache(maxsize=4)
def sandwich_agent(prompt: str):
    return create_agent(
        model=_build_llm(),
        tools=TOOLS,
        system_prompt=prompt + CARTESIA_TTS_SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )


@functools.lru_cache(maxsize=4)
def realtime_agent(prompt: str, greeting: str) -> GeminiLiveAgent:
    return GeminiLiveAgent(system_prompt=prompt, tools=TOOLS, greeting=greeting)


def warm_up_ollama() -> float:
    """Load the model and cache the prompt prefix before the first customer."""
    return warm_up([search_knowledge])


if current_pipeline() == "ollama":
    try:
        print(f"Ollama: model warmed up in {warm_up_ollama():.1f}s")
    except Exception as e:
        print(f"Ollama: warm-up failed ({e}). Is 'ollama serve' running?")


async def _stt_stream(
    audio_stream: AsyncIterator[bytes],
    stt: AssemblyAISTT | LocalSTT | None = None,
) -> AsyncIterator[VoiceAgentEvent]:
    """
    Transform stream: Audio (Bytes) → Voice Events (VoiceAgentEvent)

    This function takes a stream of audio chunks and sends them to AssemblyAI for STT.

    It uses a producer-consumer pattern where:
    - Producer: A background task reads audio chunks from audio_stream and sends
      them to AssemblyAI via WebSocket. This runs concurrently with the consumer,
      allowing transcription to begin before all audio has arrived.
    - Consumer: The main coroutine receives transcription events from AssemblyAI
      and yields them downstream. Events include both partial results (stt_chunk)
      and final transcripts (stt_output).

    Args:
        audio_stream: Async iterator of PCM audio bytes (16-bit, mono, 16kHz)
        stt: The STT to use; AssemblyAI if not given

    Yields:
        STT events (stt_chunk for partials, stt_output for final transcripts)
    """
    stt = stt or AssemblyAISTT(sample_rate=16000)

    async def send_audio():
        """
        Background task that pumps audio chunks to AssemblyAI.

        This runs concurrently with the main coroutine, continuously reading
        audio chunks from the input stream and forwarding them to AssemblyAI.
        When the input stream ends, it signals completion by closing the
        WebSocket connection.
        """
        try:
            # Stream each audio chunk to AssemblyAI as it arrives
            async for audio_chunk in audio_stream:
                await stt.send_audio(audio_chunk)
        finally:
            # Signal to AssemblyAI that audio streaming is complete
            await stt.close()

    # Launch the audio sending task in the background
    # This allows us to simultaneously receive transcripts in the main coroutine
    send_task = asyncio.create_task(send_audio())

    try:
        # Consumer loop: receive and yield transcription events as they arrive
        # from AssemblyAI. The receive_events() method listens on the WebSocket
        # for transcript events and yields them as they become available.
        async for event in stt.receive_events():
            yield event
    finally:
        # Cleanup: ensure the background task is cancelled and awaited
        with contextlib.suppress(asyncio.CancelledError):
            send_task.cancel()
            await send_task
        # Ensure the WebSocket connection is closed
        await stt.close()


async def _agent_stream(
    event_stream: AsyncIterator[VoiceAgentEvent],
) -> AsyncIterator[VoiceAgentEvent]:
    """
    Transform stream: Voice Events → Voice Events (with Agent Responses)

    This function takes a stream of upstream voice agent events and processes them.
    When an stt_output event arrives, it passes the transcript to the LangChain agent.
    The agent streams back its response tokens as agent_chunk events.
    Tool calls and results are also emitted as separate events.
    All other upstream events are passed through unchanged.

    The passthrough pattern ensures downstream stages (like TTS) can observe all
    events in the pipeline, not just the ones this stage produces. This enables
    features like displaying partial transcripts while the agent is thinking.

    Args:
        event_stream: An async iterator of upstream voice agent events

    Yields:
        All upstream events plus agent_chunk, tool_call, and tool_result events
    """
    # Generate a unique thread ID for this conversation session
    # This allows the agent to maintain conversation context across multiple turns
    # using the checkpointer (InMemorySaver) configured in the agent
    thread_id = str(uuid4())
    order = current_order.get(None)
    agent = sandwich_agent(build_shop_prompt(order.flow if order else flow.load_flow()))

    # Process each event as it arrives from the upstream STT stage
    async for event in event_stream:
        # Pass through all events to downstream consumers
        yield event

        # When we receive a final transcript, invoke the agent
        if event.type == "stt_output":
            # Stream the agent's response using LangChain's astream method.
            # stream_mode="messages" yields message chunks as they're generated.
            stream = agent.astream(
                {"messages": [HumanMessage(content=event.transcript)]},
                {"configurable": {"thread_id": thread_id}},
                stream_mode="messages",
            )

            # Iterate through the agent's streaming response. The stream yields
            # tuples of (message, metadata), but we only need the message.
            async for message, metadata in stream:
                # Emit agent chunks (AI messages)
                if isinstance(message, AIMessage):
                    # Extract and yield the text content from each message chunk
                    yield AgentChunkEvent.create(message.text)
                    # Emit tool calls if present
                    if hasattr(message, "tool_calls") and message.tool_calls:
                        for tool_call in message.tool_calls:
                            yield ToolCallEvent.create(
                                id=tool_call.get("id", str(uuid4())),
                                name=tool_call.get("name", "unknown"),
                                args=tool_call.get("args", {}),
                            )

                # Emit tool results (tool messages)
                if isinstance(message, ToolMessage):
                    yield ToolResultEvent.create(
                        tool_call_id=getattr(message, "tool_call_id", ""),
                        name=getattr(message, "name", "unknown"),
                        result=str(message.content) if message.content else "",
                    )

            # Signal that the agent has finished responding for this turn
            yield AgentEndEvent.create()


async def _local_stt() -> AssemblyAISTT | LocalSTT:
    """The STT for the local mode: on this Mac when the voice service has the
    model loaded, else AssemblyAI."""
    if (await service_status())["stt_ready"]:
        print("Local mode: speech to text on this Mac")
        return LocalSTT(sample_rate=16000)
    print("Local mode: the voice service has no STT ready, so AssemblyAI listens")
    return AssemblyAISTT(sample_rate=16000)


async def _tts_stream(
    event_stream: AsyncIterator[VoiceAgentEvent],
) -> AsyncIterator[VoiceAgentEvent]:
    """
    Transform stream: Voice Events → Voice Events (with Audio)

    This function takes a stream of upstream voice agent events and processes them.
    When agent_chunk events arrive, it sends the text to Cartesia for TTS synthesis.
    Audio is streamed back as tts_chunk events as it's generated.
    All upstream events are passed through unchanged.

    It uses merge_async_iters to combine two concurrent streams:
    - process_upstream(): Iterates through incoming events, yields them for
      passthrough, and sends agent text chunks to Cartesia for synthesis.
    - tts.receive_events(): Yields audio chunks from Cartesia as they are
      synthesized.

    The merge utility runs both iterators concurrently, yielding items from
    either stream as they become available. This allows audio generation to
    begin before the agent has finished generating all text, minimizing latency.

    Args:
        event_stream: An async iterator of upstream voice agent events

    Yields:
        All upstream events plus tts_chunk events for synthesized audio
    """
    # A voice chosen on the desk speaks through the local voice service
    tts = voices.make_tts() or CartesiaTTS()

    async def process_upstream() -> AsyncIterator[VoiceAgentEvent]:
        """
        Process upstream events, yielding them while sending text to Cartesia.

        This async generator serves two purposes:
        1. Pass through all upstream events (stt_chunk, stt_output, agent_chunk)
           so downstream consumers can observe the full event stream.
        2. Send agent text to Cartesia one sentence at a time, as soon as each
           sentence is complete, so speech starts before the reply is done.
           All sentences of a turn share one Cartesia context, so the voice
           keeps even prosody. agent_end sends the rest and closes the context.
        """
        buffer = ""
        context_id: str | None = None
        async for event in event_stream:
            # Pass through all events to downstream consumers
            yield event
            if event.type == "agent_chunk":
                ready, buffer = split_speakable(buffer + event.text)
                if ready:
                    context_id = context_id or tts.new_context_id()
                    await tts.send_text(ready, context_id, continue_=True)
            if event.type == "agent_end":
                if context_id:
                    await tts.send_text(buffer, context_id, continue_=False)
                else:
                    await tts.send_text(buffer)
                buffer = ""
                context_id = None

    # Connect now, so the first reply does not wait for the TLS handshake
    await tts.connect()

    try:
        # Merge the processed upstream events with TTS audio events
        # Both streams run concurrently, yielding events as they arrive
        async for event in merge_async_iters(process_upstream(), tts.receive_events()):
            yield event
    finally:
        # Cleanup: close the WebSocket connection to Cartesia
        await tts.close()


pipeline = (
    RunnableGenerator(_stt_stream)  # Audio -> STT events
    | RunnableGenerator(_agent_stream)  # STT events -> STT + Agent events
    | RunnableGenerator(_tts_stream)  # STT + Agent events -> All events
)


class TurnTimer:
    """Logs how long each turn waits after the user stops speaking."""

    def __init__(self):
        self.turn_end = 0.0
        self.first_text = 0.0
        self.first_audio = 0.0

    def observe(self, event: VoiceAgentEvent) -> None:
        now = time.monotonic()
        if event.type == "stt_output":
            self.turn_end, self.first_text, self.first_audio = now, 0.0, 0.0
        elif not self.turn_end:
            return
        elif event.type == "agent_chunk" and event.text and not self.first_text:
            self.first_text = now
        elif event.type == "tts_chunk" and not self.first_audio:
            self.first_audio = now
            text_ms = (self.first_text - self.turn_end) * 1000 if self.first_text else 0
            audio_ms = (now - self.turn_end) * 1000
            print(f"Turn latency: first text {text_ms:.0f} ms, first audio {audio_ms:.0f} ms")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Only logged-in users can talk to the agent; closing before accept
    # rejects the connection
    if not await asyncio.to_thread(auth.current_user, websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    mode = current_pipeline()
    # Each connection is one customer with their own order
    start_order(channel=mode)

    async def websocket_audio_stream() -> AsyncIterator[bytes]:
        """Async generator that yields audio bytes from the websocket."""
        while True:
            data = await websocket.receive_bytes()
            yield data

    if mode == "realtime":
        steps = current_order.get().flow
        agent = realtime_agent(build_shop_prompt(steps), flow.greeting(steps))
        output_stream = agent.stream(websocket_audio_stream())
    elif mode == "ollama":
        # Voice to voice around the local model, with barge-in
        session = LocalLiveSession(extra_tools=[search_knowledge])
        output_stream = session.stream(
            _stt_stream(websocket_audio_stream(), await _local_stt())
        )
    else:
        output_stream = pipeline.atransform(websocket_audio_stream())

    # Process all events from the pipeline, sending events back to the client
    timer = TurnTimer()
    log = ConversationLog(mode)
    await log.start()
    try:
        async for event in output_stream:
            timer.observe(event)
            await log.observe(event)
            try:
                await websocket.send_json(event_to_dict(event))
            except (WebSocketDisconnect, RuntimeError):
                # The client left while events were still on the way
                break
    finally:
        await log.finish()


# Desk API. The routes come before the static mount, which matches every path.
# The require_login middleware checks the user's permission for each route.


class SettingsUpdate(BaseModel):
    pipeline: str


class CustomerCreate(BaseModel):
    name: str
    phone: str


class ModuleIn(BaseModel):
    name: str
    kind: str = "notes"
    intro: str = ""


class SectionIn(BaseModel):
    title: str
    body: str


class OrderIn(BaseModel):
    ids: list[int]


class KnowledgeTest(BaseModel):
    question: str


class FlowIn(BaseModel):
    steps: list[dict]


TITLE_MAX = 300
BODY_MAX = 4000


async def _settings() -> dict:
    return {
        "pipeline": current_pipeline(),
        "local_model": OLLAMA_MODEL,
        "local_stt_ready": (await service_status())["stt_ready"],
        "gemini_ready": bool(credentials.gemini_key()),
    }


@app.get("/api/settings")
async def get_settings():
    return await _settings()


@app.put("/api/settings")
async def update_settings(update: SettingsUpdate):
    if update.pipeline not in PIPELINES:
        raise HTTPException(400, f"Unknown mode '{update.pipeline}'.")
    if update.pipeline == "realtime" and not (await _settings())["gemini_ready"]:
        raise HTTPException(400, "Add the Gemini API key in Settings to use Gemini.")
    if update.pipeline == "ollama":
        # Load the model now, so the switch fails here and not mid-call
        try:
            seconds = await asyncio.to_thread(warm_up_ollama)
            print(f"Ollama: model warmed up in {seconds:.1f}s")
        except Exception as e:
            raise HTTPException(
                503, f"Can't reach Ollama. Start it with 'ollama serve'. ({e})"
            )
    store.set_setting("pipeline", update.pipeline)
    print(f"Desk: voice mode set to {update.pipeline}")
    return await _settings()


class GeminiKeyIn(BaseModel):
    key: str


# Only the last four characters of the key ever leave the server
@app.get("/api/settings/gemini-key")
async def get_gemini_key():
    return await asyncio.to_thread(credentials.gemini_status)


@app.put("/api/settings/gemini-key")
async def save_gemini_key(body: GeminiKeyIn):
    try:
        status = await asyncio.to_thread(credentials.save_gemini_key, body.key)
    except ValueError as e:
        raise HTTPException(400, str(e))
    print("Desk: Gemini API key saved")
    return status


@app.delete("/api/settings/gemini-key")
async def delete_gemini_key():
    status = await asyncio.to_thread(credentials.remove_gemini_key)
    print("Desk: Gemini API key removed")
    return status


@app.get("/api/customers")
async def get_customers():
    return await asyncio.to_thread(store.list_customers)


@app.post("/api/customers", status_code=201)
async def create_customer(customer: CustomerCreate):
    name = customer.name.strip()
    digits = normalize_phone(customer.phone)
    if not name:
        raise HTTPException(400, "Enter the customer's name.")
    if not digits:
        raise HTTPException(400, "Enter a 10-digit phone number.")
    await asyncio.to_thread(store.save_customer, digits, name)
    return {"phone": digits, "name": name}


@app.get("/api/conversations")
async def get_conversations():
    return await asyncio.to_thread(store.list_conversations)


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: int):
    conversation = await asyncio.to_thread(store.get_conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "This conversation no longer exists.")
    return conversation


def _clean_module(module: ModuleIn) -> tuple[str, str, str]:
    name = " ".join(module.name.split())
    if not name:
        raise HTTPException(400, "Enter a name for the module.")
    if len(name) > 60:
        raise HTTPException(400, "Keep the module name under 60 characters.")
    if module.kind not in knowledge_base.MODULE_KINDS:
        raise HTTPException(400, f"Unknown module type '{module.kind}'.")
    intro = module.intro.strip()
    if len(intro) > BODY_MAX:
        raise HTTPException(400, f"Keep the intro under {BODY_MAX} characters.")
    return name, module.kind, intro


def _clean_section(section: SectionIn) -> tuple[str, str]:
    title = " ".join(section.title.split())
    body = section.body.strip()
    if not title:
        raise HTTPException(400, "Enter a title.")
    if not body:
        raise HTTPException(400, "Enter the text the agent should know.")
    if len(title) > TITLE_MAX:
        raise HTTPException(400, f"Keep the title under {TITLE_MAX} characters.")
    if len(body) > BODY_MAX:
        raise HTTPException(400, f"Keep the text under {BODY_MAX} characters.")
    return title, body


async def _module_or_404(module_id: int) -> dict:
    module = await asyncio.to_thread(store.get_module, module_id)
    if not module:
        raise HTTPException(404, "This module no longer exists.")
    return module


async def _reindex(module_id: int) -> dict:
    await asyncio.to_thread(knowledge_base.reindex_module, module_id)
    return await _module_or_404(module_id)


@app.get("/api/modules")
async def get_modules():
    return await asyncio.to_thread(store.list_modules)


@app.post("/api/modules", status_code=201)
async def create_module(module: ModuleIn):
    saved = await asyncio.to_thread(store.add_module, *_clean_module(module))
    print(f"Desk: module '{saved['name']}' added")
    return await _reindex(saved["id"])


@app.post("/api/modules/reorder")
async def reorder_modules(order: OrderIn):
    await asyncio.to_thread(store.reorder_modules, order.ids)
    return await asyncio.to_thread(store.list_modules)


@app.put("/api/modules/{module_id}")
async def update_module(module_id: int, module: ModuleIn):
    await _module_or_404(module_id)
    await asyncio.to_thread(store.update_module, module_id, *_clean_module(module))
    # The module name is part of every chunk, so re-index them all
    return await _reindex(module_id)


@app.delete("/api/modules/{module_id}", status_code=204)
async def delete_module(module_id: int):
    if not await asyncio.to_thread(store.delete_module, module_id):
        raise HTTPException(404, "This module no longer exists.")
    await asyncio.to_thread(knowledge_base.remove_module, module_id)


@app.post("/api/modules/{module_id}/sections", status_code=201)
async def create_section(module_id: int, section: SectionIn):
    await _module_or_404(module_id)
    await asyncio.to_thread(store.add_section, module_id, *_clean_section(section))
    return await _reindex(module_id)


@app.post("/api/modules/{module_id}/sections/reorder")
async def reorder_sections(module_id: int, order: OrderIn):
    await _module_or_404(module_id)
    await asyncio.to_thread(store.reorder_sections, module_id, order.ids)
    return await _module_or_404(module_id)


@app.put("/api/sections/{section_id}")
async def update_section(section_id: int, section: SectionIn):
    saved = await asyncio.to_thread(store.update_section, section_id, *_clean_section(section))
    if not saved:
        raise HTTPException(404, "This section no longer exists.")
    return await _reindex(saved["module_id"])


@app.delete("/api/sections/{section_id}")
async def delete_section(section_id: int):
    section = await asyncio.to_thread(store.get_section, section_id)
    if not section or not await asyncio.to_thread(store.delete_section, section_id):
        raise HTTPException(404, "This section no longer exists.")
    return await _reindex(section["module_id"])


@app.post("/api/knowledge/test")
async def test_knowledge(test: KnowledgeTest):
    """What the knowledge search returns for a question, the same search the agent uses."""
    question = test.question.strip()
    if not question:
        raise HTTPException(400, "Enter a question to test.")
    return await asyncio.to_thread(knowledge_base.search_results, question)


def _flow_response() -> dict:
    steps = flow.load_flow()
    return {
        "steps": [flow.to_dict(step) for step in steps],
        "is_default": not store.list_flow_steps(),
        "greeting": flow.greeting(steps),
        "prompt": flow.steps_prompt(steps),
    }


@app.get("/api/flow")
async def get_flow():
    return await asyncio.to_thread(_flow_response)


@app.put("/api/flow")
async def update_flow(update: FlowIn):
    try:
        steps = flow.validate(update.steps)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await asyncio.to_thread(flow.save_flow, steps)
    print(f"Desk: flow saved: {' → '.join(step.key for step in steps)}")
    return await asyncio.to_thread(_flow_response)


@app.post("/api/flow/reset")
async def reset_flow():
    await asyncio.to_thread(flow.reset_flow)
    return await asyncio.to_thread(_flow_response)


class CityIn(BaseModel):
    name: str
    aliases: list[str] = []
    active: bool = True


class ZoneIn(BaseModel):
    name: str
    active: bool = True


class PincodeIn(BaseModel):
    pincode: str
    areas: list[str] = []
    active: bool = True
    # Set to move the pincode to another zone
    zone_id: int | None = None


def _delivery_edit(edit) -> list[dict]:
    """Run a desk edit, then return every area. ValueError becomes a 400."""
    try:
        edit()
    except ValueError as e:
        raise HTTPException(400, str(e))
    return store.list_delivery()


def _need(found, what: str):
    if not found:
        raise HTTPException(404, f"{what} not found.")
    return found


@app.get("/api/delivery")
async def get_delivery():
    return await asyncio.to_thread(store.list_delivery)


@app.post("/api/delivery/cities", status_code=201)
async def add_city(city: CityIn):
    def edit():
        aliases = delivery.clean_list([city.name.lower(), *city.aliases])
        store.add_city(delivery.clean_name(city.name, "city"), aliases)

    return await asyncio.to_thread(_delivery_edit, edit)


@app.put("/api/delivery/cities/{city_id}")
async def update_city(city_id: int, city: CityIn):
    _need(await asyncio.to_thread(store.get_city, city_id), "City")

    def edit():
        name = delivery.clean_name(city.name, "city")
        store.update_city(city_id, name, delivery.clean_list(city.aliases), city.active)

    return await asyncio.to_thread(_delivery_edit, edit)


@app.delete("/api/delivery/cities/{city_id}")
async def delete_city(city_id: int):
    _need(await asyncio.to_thread(store.get_city, city_id), "City")
    return await asyncio.to_thread(_delivery_edit, lambda: store.delete_city(city_id))


@app.post("/api/delivery/cities/{city_id}/zones", status_code=201)
async def add_zone(city_id: int, zone: ZoneIn):
    _need(await asyncio.to_thread(store.get_city, city_id), "City")
    return await asyncio.to_thread(
        _delivery_edit,
        lambda: store.add_zone(city_id, delivery.clean_name(zone.name, "zone")),
    )


@app.put("/api/delivery/zones/{zone_id}")
async def update_zone(zone_id: int, zone: ZoneIn):
    _need(await asyncio.to_thread(store.get_zone, zone_id), "Zone")
    return await asyncio.to_thread(
        _delivery_edit,
        lambda: store.update_zone(
            zone_id, delivery.clean_name(zone.name, "zone"), zone.active
        ),
    )


@app.delete("/api/delivery/zones/{zone_id}")
async def delete_zone(zone_id: int):
    _need(await asyncio.to_thread(store.get_zone, zone_id), "Zone")
    return await asyncio.to_thread(_delivery_edit, lambda: store.delete_zone(zone_id))


@app.post("/api/delivery/zones/{zone_id}/pincodes", status_code=201)
async def add_pincode(zone_id: int, pin: PincodeIn):
    _need(await asyncio.to_thread(store.get_zone, zone_id), "Zone")

    def edit():
        pincode = delivery.clean_pincode(pin.pincode)
        store.save_pincode(
            None, pincode, zone_id, delivery.clean_list(pin.areas), pin.active
        )

    return await asyncio.to_thread(_delivery_edit, edit)


@app.put("/api/delivery/pincodes/{pincode}")
async def update_pincode(pincode: str, pin: PincodeIn):
    old = _need(await asyncio.to_thread(store.find_pincode, pincode), "Pincode")
    zone_id = pin.zone_id or old["zone_id"]
    _need(await asyncio.to_thread(store.get_zone, zone_id), "Zone")

    def edit():
        new = delivery.clean_pincode(pin.pincode, old=pincode)
        store.save_pincode(
            pincode, new, zone_id, delivery.clean_list(pin.areas), pin.active
        )

    return await asyncio.to_thread(_delivery_edit, edit)


@app.delete("/api/delivery/pincodes/{pincode}")
async def delete_pincode(pincode: str):
    _need(await asyncio.to_thread(store.find_pincode, pincode), "Pincode")
    return await asyncio.to_thread(
        _delivery_edit, lambda: store.delete_pincode(pincode)
    )


@app.post("/api/delivery/reset")
async def reset_delivery():
    return await asyncio.to_thread(_delivery_edit, delivery.reset)


class VoiceChoice(BaseModel):
    # None for Cartesia
    id: int | None


class AccentIn(BaseModel):
    accent: str


async def _voices_response() -> dict:
    active = await asyncio.to_thread(voices.active_voice)
    return {
        "voices": await asyncio.to_thread(voices.list_grouped),
        "active_id": active["id"] if active else None,
        "service": await service_status(),
        "script": voices.SCRIPT,
        "accents": voices.ACCENTS,
        "min_seconds": voices.MIN_SECONDS,
        "max_seconds": voices.MAX_SECONDS,
    }


def _voice_or_404(voice_id: int) -> dict:
    voice = store.get_voice(voice_id)
    if not voice:
        raise HTTPException(404, "No such voice.")
    return voice


async def _require_service() -> None:
    status = await service_status()
    if not status["running"]:
        raise HTTPException(
            503, "The local voice service is off. Start it with 'make dev-voice'."
        )
    if status["error"]:
        raise HTTPException(503, status["error"])
    if not status["ready"]:
        raise HTTPException(
            503, "The voice models are still loading. Try again in a minute."
        )


@app.get("/api/voices")
async def get_voices():
    return await _voices_response()


@app.post("/api/voices", status_code=201)
async def add_voice(request: Request, name: str):
    """Save a recording. The body is the WAV file, the name a query parameter."""
    name = " ".join(name.split())
    if not name:
        raise HTTPException(400, "Give the voice a name.")
    if len(name) > voices.NAME_MAX:
        raise HTTPException(400, f"Keep the name under {voices.NAME_MAX} characters.")
    data = await request.body()
    try:
        return await asyncio.to_thread(voices.add_recording, name, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/voices/{voice_id}", status_code=204)
async def delete_voice(voice_id: int):
    await asyncio.to_thread(_voice_or_404, voice_id)
    deleted = await asyncio.to_thread(store.delete_voice, voice_id)
    active = await asyncio.to_thread(voices.active_voice)
    if active is None or active["id"] in deleted:
        await asyncio.to_thread(voices.set_active, None)


@app.post("/api/voices/{voice_id}/accents", status_code=201)
async def add_accent(voice_id: int, body: AccentIn):
    parent = await asyncio.to_thread(_voice_or_404, voice_id)
    if parent["parent_id"] is not None:
        raise HTTPException(400, "Make accents from the original recording.")
    if body.accent not in voices.ACCENTS:
        raise HTTPException(400, f"Unknown accent '{body.accent}'.")
    await _require_service()
    try:
        return await voices.add_accent(parent, body.accent)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"The voice service could not make the accent. ({e})")


@app.get("/api/voices/{voice_id}/audio")
async def voice_audio(voice_id: int):
    voice = await asyncio.to_thread(_voice_or_404, voice_id)
    return FileResponse(voice["file"], media_type="audio/wav")


@app.post("/api/voices/{voice_id}/preview")
async def preview_voice(voice_id: int):
    voice = await asyncio.to_thread(_voice_or_404, voice_id)
    await _require_service()
    try:
        return Response(await voices.preview(voice), media_type="audio/wav")
    except Exception as e:
        raise HTTPException(502, f"The voice service could not speak. ({e})")


@app.put("/api/voices/active")
async def choose_voice(choice: VoiceChoice):
    if choice.id is not None:
        await asyncio.to_thread(_voice_or_404, choice.id)
        await _require_service()
    await asyncio.to_thread(voices.set_active, choice.id)
    print(f"Desk: voice set to {choice.id or 'Cartesia'}")
    return await _voices_response()


class BrandIn(BaseModel):
    name: str
    description: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    icon: str = ""


@app.get("/api/brand")
async def get_brand():
    return await asyncio.to_thread(brand.get)


@app.put("/api/brand")
async def save_brand(details: BrandIn):
    try:
        saved = await asyncio.to_thread(brand.save, details.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    print(f"Desk: business details saved ({saved['name']})")
    return saved


@app.get("/api/brand/logo")
async def brand_logo():
    found = await asyncio.to_thread(brand.logo_file)
    if not found:
        raise HTTPException(404, "There is no logo.")
    path, media_type = found
    return FileResponse(
        path, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"}
    )


@app.post("/api/brand/logo")
async def upload_logo(request: Request):
    """Replace the logo. The body is the image file."""
    data = await request.body()
    try:
        return await asyncio.to_thread(brand.set_logo, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/brand/logo")
async def delete_logo():
    return await asyncio.to_thread(brand.remove_logo)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("main:app", port=8000, reload=True)
