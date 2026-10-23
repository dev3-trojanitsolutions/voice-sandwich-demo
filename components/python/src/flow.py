"""
The ordering flow: the steps the agent asks for, in order.

Staff set the flow on the desk. It is saved in the store, and each new
session reads it once (orders.start_order), so a change applies to the next
call. Every pipeline builds its instructions from the same flow:
- Gemini and Claude get the numbered steps in the system prompt (steps_prompt).
- The local model gets one step at a time (stage_note in ollama_harness).

There are two kinds of step:
- Built-in steps (name, address, items, payment, phone, otp) have their own
  tool and checks in orders.py. Staff can reorder them and change what the
  agent says, but not remove them. "otp" confirms the order, so it is always
  last. "phone" can go anywhere before it.
- Custom steps ask one more thing, for example a spice level. The agent saves
  the answer with save_order_detail. A custom step can be optional and can
  have a fixed list of choices.
"""

import re
from dataclasses import asdict, dataclass, field

import brand
import store

BUILTIN_KEYS = ("name", "address", "items", "payment", "phone", "otp")
LAST_KEY = "otp"
# Flows saved before phone and OTP were split had one "confirm" step
LEGACY_KEYS = {"confirm": ("phone", "otp")}
MAX_STEPS = 12
MAX_CHOICES = 10

# The tools each built-in step uses. Custom steps use save_order_detail.
STEP_TOOLS = {
    "name": ["save_customer_name"],
    "address": ["save_delivery_address"],
    "items": ["add_to_order", "get_order_total"],
    "payment": ["get_order_total", "set_payment_method"],
    "phone": ["save_phone_number"],
    "otp": ["send_otp", "verify_otp"],
}
CUSTOM_TOOL = "save_order_detail"


@dataclass
class Step:
    key: str
    kind: str  # "builtin" or "custom"
    label: str
    ask: str
    notes: str = ""
    required: bool = True
    choices: list[str] = field(default_factory=list)

    def tools(self) -> list[str]:
        return STEP_TOOLS[self.key] if self.kind == "builtin" else [CUSTOM_TOOL]


DEFAULT_FLOW = [
    Step(
        key="name",
        kind="builtin",
        label="Name",
        ask="May I know your name, please?",
    ),
    Step(
        key="address",
        kind="builtin",
        label="Delivery address",
        ask=(
            "What's the delivery address? Please tell me the door number, street "
            "and pincode."
        ),
        notes=(
            "If they want to give it later, explain kindly that we first need to "
            "check we deliver to their pincode, so their time is not wasted. Move "
            "on only once the tool confirms we deliver."
        ),
    ),
    Step(
        key="items",
        kind="builtin",
        label="Order items",
        ask="What would you like to order?",
        notes=(
            "Tell them about the starters first, then the meals. If they ask what "
            "is best, recommend our specials: Chicken 65 among the starters, and "
            "Chicken Mandi or Mutton Biriyani among the meals. When they are done, "
            "read back the order and say: Please note, once the order is placed it "
            "cannot be cancelled. Would you like to change anything?"
        ),
    ),
    Step(
        key="payment",
        kind="builtin",
        label="Payment method",
        ask="Would you like to pay by UPI or Credit Card?",
        notes="We accept only UPI or Credit Card.",
    ),
    Step(
        key="phone",
        kind="builtin",
        label="Phone number",
        ask="May I have your 10-digit phone number?",
    ),
    Step(
        key="otp",
        kind="builtin",
        label="OTP",
        ask="Please read out the 4-digit OTP we just sent to your phone.",
        notes=(
            "The order is confirmed only when verify_otp says so. Then thank "
            "them by name."
        ),
    ),
]


# Default texts of earlier versions, by step key. A saved step that still has
# one gets the current default, so staff edits are kept but old defaults move on.
OLD_DEFAULTS = {
    "address": {
        "ask": "What is your delivery address and city?",
        "notes": (
            "If they want to give it later, explain kindly that we first need to "
            "check we deliver to their location, so their time is not wasted. Move "
            "on only once the tool confirms we deliver. We deliver only in Bangalore."
        ),
    },
}


def load_flow() -> list[Step]:
    """The saved flow, or the default flow if none is saved."""
    rows = store.list_flow_steps()
    if not rows:
        return [Step(**asdict(step)) for step in DEFAULT_FLOW]
    steps = []
    for row in rows:
        if row["key"] in LEGACY_KEYS and row["kind"] == "builtin":
            steps += [Step(**asdict(default_step(k))) for k in LEGACY_KEYS[row["key"]]]
            continue
        if row["kind"] == "builtin":
            for name, old in OLD_DEFAULTS.get(row["key"], {}).items():
                if row[name] == old:
                    row[name] = getattr(default_step(row["key"]), name)
        steps.append(Step(**row))
    return steps


def default_step(key: str) -> Step:
    return next(step for step in DEFAULT_FLOW if step.key == key)


def slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40]


def validate(raw_steps: list[dict]) -> list[Step]:
    """Check a flow sent from the desk and return it as steps. Raises
    ValueError with a message for staff."""
    if len(raw_steps) > MAX_STEPS:
        raise ValueError(f"A flow can have at most {MAX_STEPS} steps.")

    steps: list[Step] = []
    seen: set[str] = set()
    for raw in raw_steps:
        label = " ".join(str(raw.get("label", "")).split())
        ask = " ".join(str(raw.get("ask", "")).split())
        notes = str(raw.get("notes", "")).strip()
        if not label:
            raise ValueError("Every step needs a name.")
        if not ask:
            raise ValueError(f"Enter what the agent asks for the step “{label}”.")

        if raw.get("kind") == "builtin":
            key = str(raw.get("key", ""))
            if key not in BUILTIN_KEYS:
                raise ValueError(f"Unknown built-in step '{key}'.")
            step = Step(key=key, kind="builtin", label=label, ask=ask, notes=notes)
        else:
            key = str(raw.get("key") or "") or slugify(label)
            if not re.fullmatch(r"[a-z0-9_]+", key) or key in BUILTIN_KEYS:
                key = slugify(label)
            if not key or key in BUILTIN_KEYS:
                raise ValueError(f"Choose another name for the step “{label}”.")
            choices = [" ".join(str(c).split()) for c in raw.get("choices") or []]
            choices = [c for c in choices if c]
            if len(choices) > MAX_CHOICES:
                raise ValueError(f"A step can have at most {MAX_CHOICES} choices.")
            step = Step(
                key=key,
                kind="custom",
                label=label,
                ask=ask,
                notes=notes,
                required=bool(raw.get("required", True)),
                choices=choices,
            )

        if step.key in seen:
            raise ValueError(f"Two steps are called “{label}”. Give each step its own name.")
        seen.add(step.key)
        steps.append(step)

    missing = [k for k in BUILTIN_KEYS if k not in seen]
    if missing:
        names = ", ".join(default_step(k).label for k in missing)
        raise ValueError(f"The flow must keep the built-in steps: {names}.")
    if steps[-1].key != LAST_KEY:
        raise ValueError(f"“{default_step(LAST_KEY).label}” must be the last step.")
    return steps


def save_flow(steps: list[Step]) -> None:
    store.replace_flow_steps([asdict(step) for step in steps])


def reset_flow() -> None:
    store.replace_flow_steps([])


def greeting(steps: list[Step]) -> str:
    """The agent's first line: a welcome and the first step's question."""
    return f"Welcome to {brand.get()['name']}! {steps[0].ask}"


def step_instruction(step: Step) -> str:
    """What the agent must do in one step, in one paragraph."""
    parts = [f"{step.label}: ask \"{step.ask}\""]
    if step.notes:
        parts.append(step.notes)
    if step.kind == "custom":
        if step.choices:
            parts.append(f"The choices are: {', '.join(step.choices)}.")
        if not step.required:
            parts.append('This step is optional. If they do not want to answer, save "none".')
        parts.append(f'Call save_order_detail with step "{step.key}" and their answer.')
    elif step.key == "name":
        parts.append("Call save_customer_name.")
    elif step.key == "address":
        parts.append(
            "Get the door number, street and 6-digit pincode. Call "
            "save_delivery_address with the parts they said, even if some are "
            "missing: the result says what to ask next."
        )
    elif step.key == "items":
        parts.append(
            "Call add_to_order for every item they order and tell them its price."
        )
    elif step.key == "payment":
        parts.append(
            "First call get_order_total and tell them the total. "
            "Then call set_payment_method."
        )
    elif step.key == "phone":
        parts.append("Call save_phone_number.")
    elif step.key == "otp":
        # The OTP must be sent before the agent asks for it
        parts[0] = f"{step.label}: call send_otp, then ask \"{step.ask}\""
        parts.append("Call verify_otp with the OTP they read out.")
    return " ".join(parts)


def steps_prompt(steps: list[Step]) -> str:
    """The numbered steps for the system prompt of Gemini and Claude."""
    lines = ["Follow these steps in order:"]
    for number, step in enumerate(steps, 1):
        lines.append(f"{number}. {step_instruction(step)}")
    return "\n".join(lines)


def to_dict(step: Step) -> dict:
    return asdict(step) | {"tools": step.tools()}
