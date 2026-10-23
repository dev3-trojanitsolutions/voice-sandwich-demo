"""
Agent harness for a small local model served by Ollama.

A 4B model makes more mistakes than Claude or Gemini when it gets a long prompt
and many tools. This harness keeps each request small and checks what the model
does:

- The ordering flow (set on the desk, see flow.py) is tracked in code
  (orders.order_stage), not in the prompt. Each turn the model gets the
  instruction for the current step, and the harness runs only the tools of
  that step and the steps before it.
- Each request only appends to the previous one: the same tools and persona
  first, then history exactly as it was sent, notes included. Ollama then
  reuses its cached prompt and processes only the new tokens. (The chat
  template puts the tools at the top of the prompt, so a different tool list
  per stage would miss the cache.)
- A turn has one round of tool calls, then a spoken reply. A small model
  that may call tools again tends to chain invented calls. The exception:
  when the model sends calls instead of a reply (often one item per round, or
  a fixed call after an error), they run, up to two more rounds. A call that
  already ran in the turn is skipped, so an item is not added twice.
- Tools that need numbers the customer said (phone, OTP) run only when the
  transcript has those numbers.
- The harness sends the OTP itself when the flow reaches the OTP step, so the
  model can ask for it in the same turn.
- Questions about the shop are answered from knowledge base chunks that are
  retrieved before the model runs, which saves a tool-call round trip.
- Tool calls are checked against the tool's signature. A bad call goes back to
  the model as an error, and the turn ends with a fallback line if it repeats.
"""

import asyncio
import inspect
import os
import re
import time
from typing import AsyncIterator, Callable
from uuid import uuid4

import ollama

import brand
from events import (
    AgentChunkEvent,
    AgentEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    VoiceAgentEvent,
)
from flow import Step, greeting, load_flow, step_instruction
from knowledge_base import menu_overview, search
from orders import (
    OTP_DIGITS,
    add_to_order,
    cancel_order,
    current_order,
    get_order_total,
    normalize_phone,
    order_stage,
    save_customer_name,
    save_delivery_address,
    save_order_detail,
    save_phone_number,
    send_otp,
    set_payment_method,
    spoken_digits,
    spoken_pincode,
    verify_otp,
)
from speech_style import SpeechStyle, say_rupees

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

FALLBACK = "Sorry, the line broke up a bit. Can you say that again?"
NUDGE = "Hello? Are you still there?"

# History is cut from HISTORY_MAX to HISTORY_KEEP messages in one step. Each cut
# misses the prompt cache once, so it must not happen every turn. The order
# snapshot in the stage note carries the facts, so old turns are not needed.
HISTORY_MAX = 20
HISTORY_KEEP = 8

# Tool rounds after the first, when the model calls tools instead of replying
EXTRA_TOOL_ROUNDS = 2

REPLY_NOTE = (
    "The tools have run. Now reply to the customer in one or two short "
    "sentences. Do not call tools."
)

MODEL_OPTIONS = {
    # Tools and persona take about 1,000 tokens, and history keeps its notes
    "num_ctx": 8192,
    # Replies are spoken, so keep them short. This also caps a runaway reply.
    "num_predict": 120,
    # Keep it low. At 0.5 the 4B model invented addresses and prices and
    # skipped add_to_order. Variety in the replies comes from speech_style.py.
    "temperature": 0.3,
}

# Fixed first message. Do not put per-turn data here: a change in this text
# makes Ollama process the whole prompt again. The menu comes from the desk, so
# it changes only when staff edit a menu module.
# Keep it short, with no example dialogue: a longer persona or examples made
# the 4B model copy the examples and skip tool calls.
PERSONA = """
You are the person who answers the phone at {shop}.
Your replies are spoken aloud by a text-to-speech voice:
- Reply in one or two short sentences, in English only. Ask one thing at a time.
- Talk like a friendly person on the phone, not an assistant. Use everyday words
  and contractions, for example "What's your address?", not "Could you please
  provide your delivery address?".
- Don't read out the whole menu. Name two or three dishes unless they ask for all.
- Don't repeat a sentence you already said. Say it another way.
- Use plain text only: no lists, markdown, emojis or special characters.
- Say prices in rupees, for example "250 rupees".

Tools save the order. Call a tool as soon as the customer gives the information
it needs. Tool results tell you if something is missing or wrong: follow them.
Never say an order is confirmed unless verify_otp said so.

Answer questions about prices, ingredients, allergens, hours, delivery, payment
or refunds only from the shop info in the latest note, or call search_knowledge.
If neither has the answer, say you don't know.
{contact}
Menu: {menu}.

Each turn ends with a note from the system about the current step. Follow it.
""".strip()

CONFIRMED_NOTE = (
    "Step: the order is confirmed and can no longer be changed or cancelled. "
    "Thank the customer by name and answer any questions."
)


def persona() -> str:
    return PERSONA.format(
        shop=brand.shop(),
        contact=brand.contact(),
        menu=menu_overview() or "ask search_knowledge",
    )


ALL_ORDER_TOOLS = [
    save_customer_name,
    save_delivery_address,
    add_to_order,
    get_order_total,
    set_payment_method,
    save_order_detail,
    save_phone_number,
    send_otp,
    verify_otp,
    cancel_order,
]
TOOLS_BY_NAME = {tool.__name__: tool for tool in ALL_ORDER_TOOLS}

# Transcripts from AssemblyAI are unformatted (no "?"), so match on words.
# "is", "do" and "can" are left out: they appear in most answers too.
NUMBER_WORDS = re.compile(
    r"\d|\b(zero|oh|one|two|three|four|five|six|seven|eight|nine|double|triple)\b",
    re.IGNORECASE,
)
# Tools whose arguments are numbers the customer must say in this turn
NEEDS_SPOKEN_NUMBER = {"save_phone_number", "verify_otp"}

QUESTION_WORDS = re.compile(
    r"\?|\b(what|which|how|when|where|why|price|prices|cost|rupees|"
    r"gluten|dairy|milk|egg|nut|nuts|soy|allergy|allergic|vegetarian|spicy|"
    r"open|close|hours|deliver|delivery|refund|pay|payment)\b",
    re.IGNORECASE,
)


REFERS_BACK = re.compile(r"\b(it|its|that|this|they|them|those|these)\b", re.IGNORECASE)

# A payment method is saved only when the customer named one in this turn.
# Small models otherwise pick one when the customer only says "okay".
PAYMENT_WORDS = re.compile(
    r"\b(upi|upa|u p i|card|credit|debit|gpay|google pay|phonepe|paytm)\b",
    re.IGNORECASE,
)

# Words speech to text gives when it mishears a name ("Was", "And a"). A name
# made only of these is refused, so the agent asks again.
NOT_A_NAME = {
    "a",
    "an",
    "and",
    "the",
    "was",
    "is",
    "it",
    "its",
    "i",
    "im",
    "my",
    "name",
    "um",
    "uh",
    "hmm",
    "yes",
    "yeah",
    "no",
    "ok",
    "okay",
    "hello",
    "hi",
    "what",
    "where",
    "who",
    "this",
    "that",
    "so",
    "well",
    "sir",
    "madam",
}


def _looks_like_name(name: str) -> bool:
    words = re.findall(r"[a-z]+", name.lower())
    return any(len(w) > 1 and w not in NOT_A_NAME for w in words)


def _is_question(text: str) -> bool:
    return bool(QUESTION_WORDS.search(text))


def _says_number(text: str, minimum: int = 4) -> bool:
    return len(NUMBER_WORDS.findall(text)) >= minimum


def _repair_args(name: str, args: dict, transcript: str) -> dict:
    """
    Fix argument mistakes small models make often, using the customer's words.

    save_delivery_address: the model may get the pincode digits wrong, or
    put the door number in it. The pincode comes from the customer's words when
    they said one.

    save_phone_number, verify_otp: the model may get the digits wrong, for
    example "double nine" as one 9. The digits come from the customer's words
    when they make a whole number or OTP.
    """
    if name == "send_otp":
        # It takes no arguments. Small models often pass the phone number.
        return {}
    if name == "save_delivery_address" and (pincode := spoken_pincode(transcript)):
        args = {**args, "pincode": pincode}
    if name == "save_phone_number" and (phone := normalize_phone(transcript)):
        args = {"phone_number": phone}
    if name == "verify_otp" and len(otp := spoken_digits(transcript)) == OTP_DIGITS:
        args = {"otp": otp}
    return args


def _order_snapshot() -> str:
    order = current_order.get()
    known = []
    if order.name:
        known.append(f"name={order.name}")
    if order.address_verified:
        known.append(f"address={order.address} (we deliver there)")
    elif order.address_parts:
        parts = ", ".join(f"{k}={v}" for k, v in order.address_parts.items())
        known.append(f"address so far: {parts}")
    if order.items:
        known.append(f"items={order.items_text()}; total=₹{order.total()}")
    if order.payment_method:
        known.append(f"payment={order.payment_method}")
    for step in order.flow:
        if step.key in order.details:
            known.append(f"{step.key}={order.details[step.key]}")
    if order.phone:
        known.append(f"phone={order.phone}")
    if order.otp:
        known.append("OTP sent")
    return say_rupees("Known so far: " + ("; ".join(known) if known else "nothing"))


def _check_call(tool: Callable[..., str], args: dict) -> dict:
    """
    Make sure the arguments fit the tool's signature and coerce simple types
    (small models often send quantity as "2"). Raises ValueError if not.
    """
    signature = inspect.signature(tool)
    try:
        bound = signature.bind(**args)
    except TypeError as e:
        raise ValueError(str(e)) from e
    checked = {}
    for name, value in bound.arguments.items():
        annotation = signature.parameters[name].annotation
        if annotation is int and not isinstance(value, int):
            try:
                value = int(str(value).strip())
            except ValueError:
                raise ValueError(f"'{name}' must be a whole number") from None
        elif annotation is str and not isinstance(value, str):
            value = str(value)
        checked[name] = value
    return checked


def warm_up(extra_tools: list[Callable[..., str]]) -> float:
    """
    Load the model and cache the tools and persona prefix before the first
    customer. Returns the time it took in seconds.
    """
    start = time.monotonic()
    ollama.Client(host=OLLAMA_BASE_URL).chat(
        model=OLLAMA_MODEL,
        # The same opening as a real conversation (see greet), so the first
        # customer turn finds it in the cache
        messages=[
            {"role": "system", "content": persona()},
            {"role": "assistant", "content": greeting(load_flow())},
            {"role": "user", "content": "Hi"},
        ],
        tools=[*ALL_ORDER_TOOLS, *extra_tools],
        think=False,
        keep_alive=-1,
        options={**MODEL_OPTIONS, "num_predict": 1},
    )
    return time.monotonic() - start


class OllamaHarness:
    """One customer conversation with the local model."""

    def __init__(self, extra_tools: list[Callable[..., str]]):
        self.client = ollama.AsyncClient(host=OLLAMA_BASE_URL)
        # Tools offered in every stage, e.g. search_knowledge
        self.extra_tools = extra_tools
        # The same list on every request, for the prompt cache
        self.all_tools = [*ALL_ORDER_TOOLS, *extra_tools]
        self.history: list[dict] = []
        self.last_user_text = ""
        # Read once, so the prompt prefix stays the same for the whole call
        self.persona = persona()
        self.flow: list[Step] = current_order.get().flow
        # Set when the customer speaks over the agent. The turn stops at the
        # next safe point: tools that started still finish, so the order and
        # the history stay in step.
        self.cut = False
        # Rewrites the replies so they sound less like an assistant
        self.style = SpeechStyle()

    def greet(self) -> list[VoiceAgentEvent]:
        """Speak first with a fixed greeting, so no model call is needed."""
        text = greeting(self.flow)
        self.history.append({"role": "assistant", "content": text})
        return [AgentChunkEvent.create(text), AgentEndEvent.create()]

    def nudge(self) -> list[VoiceAgentEvent]:
        """Check on a customer who has gone quiet, with no model call."""
        self.history.append({"role": "assistant", "content": NUDGE})
        return [AgentChunkEvent.create(NUDGE), AgentEndEvent.create()]

    async def respond(self, transcript: str) -> AsyncIterator[VoiceAgentEvent]:
        """
        Transform: final user transcript → agent events for one turn.

        The first request may call tools. If it does, the harness runs the ones
        allowed in the current stage and sends a second request for the spoken
        reply. Tool calls in that second request are ignored.
        """
        self.cut = False
        self.history.append({"role": "user", "content": transcript})
        shop_info = await self._prefetch_knowledge(transcript)
        self.last_user_text = transcript

        text, calls = "", []
        async for event in self._ask(shop_info, reply_only=False):
            if isinstance(event, list):
                calls = event
            else:
                text += event.text
                yield event

        rounds_left = EXTRA_TOOL_ROUNDS
        done: set[str] = set()
        while calls and not self.cut:
            for call in calls:
                args = sorted((call.function.arguments or {}).items())
                key = f"{call.function.name}{args}"
                if key in done:
                    self.history.append(
                        {
                            "role": "tool",
                            "tool_name": call.function.name,
                            "content": "Already done.",
                        }
                    )
                    continue
                done.add(key)
                async for event in self._run_tool(call, transcript):
                    yield event
            async for event in self._send_otp_when_due():
                yield event
            text, calls = "", []
            async for event in self._ask(
                shop_info, reply_only=True, may_retry=rounds_left > 0
            ):
                if isinstance(event, list):
                    calls = event
                else:
                    text += event.text
                    yield event
            rounds_left -= 1

        if not text.strip() and not self.cut:
            yield AgentChunkEvent.create(FALLBACK)
            self.history.append({"role": "assistant", "content": FALLBACK})

        yield AgentEndEvent.create()

    async def _ask(self, shop_info: str, reply_only: bool, may_retry: bool = False):
        """
        One model request. Yields agent_chunk events as text streams in, then
        the list of tool calls as the last item. The reply goes into history.
        A reply request drops tool calls, unless may_retry is set and the model
        sent calls instead of any text.
        """
        note = self._stage_note()
        if shop_info:
            note += f"\nShop info:\n{say_rupees(shop_info)}"
        if reply_only:
            note += f"\n{REPLY_NOTE}"
        # Attach the note to the last message (the user turn or a tool result).
        # Many chat templates accept a system message only at the start. The
        # note stays in history, so the next prompt extends this one exactly.
        recent = self._recent_history()
        recent[-1]["content"] += f"\n\n[System note: {note}]"
        messages = [{"role": "system", "content": self.persona}, *recent]

        text, calls = "", []
        # Set when the model starts markup ("<think>", "</th…"), which a voice
        # must not read out. Text after it is dropped.
        in_markup = False
        self.style.start()
        stream = await self.client.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            tools=self.all_tools,
            stream=True,
            think=False,
            keep_alive=-1,
            options=MODEL_OPTIONS,
        )
        async for chunk in stream:
            if self.cut:
                # Close the request, so Ollama stops generating
                await stream.aclose()
                calls = []
                break
            content = chunk.message.content
            if content and not in_markup:
                if "<" in content:
                    content, in_markup = content.split("<", 1)[0], True
                content = self.style.feed(content)
                if content:
                    text += content
                    yield AgentChunkEvent.create(content)
            calls.extend(chunk.message.tool_calls or [])
        if not self.cut and (rest := self.style.flush()):
            text += rest
            yield AgentChunkEvent.create(rest)

        if reply_only and (text.strip() or not may_retry):
            calls = []
        self.history.append(
            {
                "role": "assistant",
                "content": text,
                "tool_calls": [
                    {
                        "function": {
                            "name": c.function.name,
                            "arguments": c.function.arguments,
                        }
                    }
                    for c in calls
                ],
            }
        )
        yield calls

    def _stage_steps(self) -> tuple[Step | None, Step | None]:
        """The current step, and the next one while the customer is still
        adding items (they may answer it in this turn)."""
        order = current_order.get()
        key = order_stage(order)
        if key == "confirmed":
            return None, None
        index = next(i for i, step in enumerate(self.flow) if step.key == key)
        following = None
        if key == "items" and order.items and index + 1 < len(self.flow):
            following = self.flow[index + 1]
        return self.flow[index], following

    def _stage_note(self) -> str:
        step, following = self._stage_steps()
        if step is None:
            return f"{CONFIRMED_NOTE}\n{_order_snapshot()}"
        if step.key == "otp" and current_order.get().otp:
            # Sent already: a second send_otp would replace the code
            note = (
                f'Step: {step.label}: the OTP is sent. Ask "{step.ask}" {step.notes} '
                "Call verify_otp with the OTP they read out."
            )
        else:
            note = f"Step: {step_instruction(step)}"
        # Without this the model reads the step's question and the staff notes
        # out word for word ("Let me tell you about the starters first...")
        note += " Ask in your own words."
        if following:
            note += f"\nWhen they are done ordering, next step: {step_instruction(following)}"
        return f"{note}\n{_order_snapshot()}"

    def _stage_tools(self) -> list[Callable[..., str]]:
        """Tools of the current step and every step before it, so the customer
        can correct an earlier answer, plus cancel_order."""
        step, following = self._stage_steps()
        if step is None:
            return list(self.extra_tools)
        names: list[str] = []
        for s in self.flow:
            names += s.tools()
            if s is step:
                break
        if following:
            names += following.tools()
        tools = [TOOLS_BY_NAME[n] for n in dict.fromkeys(names)]
        return [*tools, cancel_order, *self.extra_tools]

    def _recent_history(self) -> list[dict]:
        """
        History, cut in one step when it gets long. The cut starts at a user
        message, so no tool result loses the call it answers.
        """
        if len(self.history) > HISTORY_MAX:
            recent = self.history[-HISTORY_KEEP:]
            while recent and recent[0]["role"] != "user":
                recent = recent[1:]
            self.history = recent
        return self.history

    async def _prefetch_knowledge(self, transcript: str) -> str:
        if not _is_question(transcript):
            return ""
        # A follow-up such as "is it gluten free?" needs the previous turn to
        # make sense. Other questions are searched alone: an unrelated previous
        # turn (e.g. the address) pulls the wrong chunks.
        query = transcript
        if REFERS_BACK.search(transcript):
            query = f"{self.last_user_text} {transcript}".strip()
        return await asyncio.to_thread(search, query, 2)

    async def _send_otp_when_due(self) -> AsyncIterator[VoiceAgentEvent]:
        """
        Send the OTP as soon as the flow reaches the OTP step. A turn has only
        one round of tool calls, so the model could otherwise call send_otp
        only on the customer's next turn, after it already asked for the OTP.
        """
        order = current_order.get()
        if order_stage(order) != "otp" or order.otp:
            return
        call_id = str(uuid4())
        yield ToolCallEvent.create(id=call_id, name="send_otp", args={})
        result = await asyncio.to_thread(send_otp)
        # Record it as part of the model's last tool round, so history stays a
        # valid call → result sequence
        last_call = next(m for m in reversed(self.history) if m["role"] == "assistant")
        last_call["tool_calls"].append(
            {"function": {"name": "send_otp", "arguments": {}}}
        )
        self.history.append(
            {"role": "tool", "tool_name": "send_otp", "content": result}
        )
        yield ToolResultEvent.create(
            tool_call_id=call_id, name="send_otp", result=result
        )

    async def _run_tool(
        self, call: ollama.Message.ToolCall, transcript: str
    ) -> AsyncIterator[VoiceAgentEvent]:
        name = call.function.name
        args = dict(call.function.arguments or {})
        call_id = str(uuid4())
        yield ToolCallEvent.create(id=call_id, name=name, args=args)

        tools = self._stage_tools()
        tool = next((t for t in tools if t.__name__ == name), None)
        if tool is None:
            result = f"Error: {name} cannot be used at this step. Follow the step note."
        elif name in NEEDS_SPOKEN_NUMBER and not _says_number(transcript):
            result = (
                f"Error: the customer did not say the number for {name}. "
                "Ask them for it."
            )
        elif name == "save_phone_number" and not normalize_phone(transcript):
            # Otherwise the model pads a part number, "9845" → 9845000000
            heard = len(spoken_digits(transcript))
            result = (
                f"Error: the customer said {heard} digits, not a 10-digit number. "
                "Tell them how many digits you heard and ask for the whole number."
            )
        elif name == "set_payment_method" and not PAYMENT_WORDS.search(transcript):
            result = (
                "Error: the customer did not choose a payment method yet. "
                "Ask: UPI or card?"
            )
        elif name == "save_customer_name" and not _looks_like_name(
            str(args.get("name", ""))
        ):
            result = (
                f'Error: "{args.get("name", "")}" is probably a mishearing, not a '
                "name. Ask for their name again, casually."
            )
        else:
            try:
                args = _repair_args(name, args, transcript)
                result = await asyncio.to_thread(tool, **_check_call(tool, args))
            except ValueError as e:
                result = f"Error: bad arguments for {name}: {e}."
            except Exception as e:
                result = f"Error running {name}: {e}"

        # The model copies "₹220" from tool results, and the voice can't say it
        self.history.append(
            {"role": "tool", "tool_name": name, "content": say_rupees(result)}
        )
        yield ToolResultEvent.create(tool_call_id=call_id, name=name, result=result)
