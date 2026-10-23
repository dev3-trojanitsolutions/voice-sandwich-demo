"""
Saves each voice session's transcript to the store, for the desk page.

ConversationLog watches the same events the browser gets, so it works for
every pipeline. The agent's words arrive as chunks and are saved as one
message when the agent finishes, starts a tool call or is interrupted.
"""

import asyncio

import store
from events import VoiceAgentEvent
from orders import current_order


class ConversationLog:
    def __init__(self, channel: str):
        self.channel = channel
        self.id: int | None = None
        self.agent_text = ""
        self.tool_args: dict[str, dict] = {}
        self.heard_customer = False
        self.name = ""
        self.phone = ""
        self.outcome = ""

    async def start(self) -> None:
        self.id = await asyncio.to_thread(store.start_conversation, self.channel)

    async def observe(self, event: VoiceAgentEvent) -> None:
        """Save what the event adds. Errors are logged, never raised to the call."""
        if self.id is None:
            return
        try:
            await self._observe(event)
        except Exception as e:
            print(f"ConversationLog: could not save ({e})")

    async def _observe(self, event: VoiceAgentEvent) -> None:
        if event.type == "stt_output" and event.transcript.strip():
            await self._flush_agent()
            self.heard_customer = True
            await self._add("customer", event.transcript.strip())
        elif event.type == "agent_chunk":
            self.agent_text += event.text
        elif event.type == "agent_end":
            await self._flush_agent()
            await self._save_customer_details()
        elif event.type == "tool_call":
            await self._flush_agent()
            self.tool_args[event.id] = event.args
        elif event.type == "tool_result":
            args = self.tool_args.pop(event.tool_call_id, {})
            await self._add("tool", event.result, event.name, args)
            if event.name == "cancel_order" and event.result.startswith("Order cancelled"):
                self.outcome = "cancelled"

    async def finish(self) -> None:
        """Save the rest and close the conversation. One with no customer speech
        is deleted, so opened-and-closed sessions don't fill the list."""
        if self.id is None:
            return
        try:
            if not self.heard_customer:
                await asyncio.to_thread(store.delete_conversation, self.id)
                return
            await self._flush_agent()
            self._read_order()
            await asyncio.to_thread(
                store.update_conversation,
                self.id,
                self.name,
                self.phone,
                self.outcome,
                True,
            )
        except Exception as e:
            print(f"ConversationLog: could not close ({e})")

    async def _flush_agent(self) -> None:
        text = self.agent_text.strip()
        self.agent_text = ""
        if text:
            await self._add("agent", text)

    async def _add(self, role: str, text: str, tool_name: str = "", args=None) -> None:
        await asyncio.to_thread(store.add_message, self.id, role, text, tool_name, args)

    def _read_order(self) -> None:
        # Keep the last known values: cancel_order clears the phone
        order = current_order.get(None)
        if not order:
            return
        self.name = order.name or self.name
        self.phone = order.phone or self.phone
        if order.confirmed:
            self.outcome = "confirmed"

    async def _save_customer_details(self) -> None:
        before = (self.name, self.phone, self.outcome)
        self._read_order()
        if (self.name, self.phone, self.outcome) != before:
            await asyncio.to_thread(
                store.update_conversation, self.id, self.name, self.phone, self.outcome
            )
