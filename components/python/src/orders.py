"""
Order state and order tools for one customer session.

Each WebSocket connection gets its own Order through a ContextVar, so the tool
functions stay plain functions (shared by both pipelines) but still see only
the current customer's order. Tools run in worker threads, which copy the
context, so they see the same Order object.

The order of the steps comes from the flow that staff set on the desk
(flow.py). The default is:
name → delivery address → items → payment method → phone + OTP → confirmed.
Each session keeps the flow it started with. The tools enforce two rules:
add_to_order needs the required steps before "items", and send_otp needs all
required steps, including the phone number. The customer can cancel any time before the OTP confirms the
order.
"""

import random
import re
from contextvars import ContextVar
from dataclasses import dataclass, field

import delivery
import store
from flow import Step, load_flow
from knowledge_base import match_menu_items

PAYMENT_METHODS = ("UPI", "Credit Card")
MAX_OTP_ATTEMPTS = 3
OTP_DIGITS = 4
# The address parts the agent asks for. Area is optional: the pincode gives it.
ADDRESS_PARTS = {"door_number": "door number", "street": "street", "pincode": "pincode"}

DIGIT_WORDS = {
    "zero": "0", "oh": "0", "o": "0",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
REPEAT_WORDS = {"double": 2, "triple": 3}
# How speech to text often hears "nine" after "double": "double n", "double line"
REPEATED_MISHEARS = {"n": "9", "nain": "9", "nein": "9", "line": "9"}
# Answers that skip an optional custom step
SKIP_WORDS = re.compile(r"\b(none|no|nope|skip|nothing|not needed|don'?t care)\b", re.IGNORECASE)


@dataclass
class Order:
    name: str = ""
    address: str = ""
    address_verified: bool = False
    # Parts said so far (door_number, street, area, pincode), so the customer
    # can give them over several turns
    address_parts: dict[str, str] = field(default_factory=dict)
    # (menu name, quantity, unit price in rupees)
    items: list[tuple[str, int, int]] = field(default_factory=list)
    payment_method: str = ""
    phone: str = ""
    otp: str = ""
    otp_attempts: int = 0
    confirmed: bool = False
    # Answers to custom flow steps, by step key
    details: dict[str, str] = field(default_factory=dict)
    # Which voice mode took the order, for the desk page
    channel: str = ""
    # The flow this session follows, read once when the session starts
    flow: list[Step] = field(default_factory=load_flow)

    def total(self) -> int:
        return sum(qty * price for _, qty, price in self.items)

    def items_text(self) -> str:
        return ", ".join(
            f"{qty} x {item} (₹{qty * price})" for item, qty, price in self.items
        )

    def summary(self) -> str:
        items = self.items_text()
        details = "".join(
            f" {step.label}: {self.details[step.key]}."
            for step in self.flow
            if step.key in self.details
        )
        return (
            f"Name: {self.name}. Address: {self.address}. Items: {items}. "
            f"Total: ₹{self.total()}. "
            f"Payment: {self.payment_method}.{details} Phone: {self.phone}."
        )


current_order: ContextVar[Order] = ContextVar("current_order")


def start_order(channel: str = "") -> None:
    """Give the current connection a fresh, empty order."""
    current_order.set(Order(channel=channel))


def _record_order(order: Order, status: str) -> None:
    store.save_order(
        order.phone,
        order.address,
        order.items,
        order.payment_method,
        status,
        order.channel,
        order.details,
        order.total(),
    )


def step_done(order: Order, step: Step) -> bool:
    """True when the order has what the step asks for."""
    if step.kind == "custom":
        return step.key in order.details
    return {
        "name": bool(order.name),
        "address": order.address_verified,
        "items": bool(order.items),
        "payment": bool(order.payment_method),
        "phone": bool(order.phone),
        "otp": order.confirmed,
    }[step.key]


def _step_started(order: Order, step: Step) -> bool:
    return step_done(order, step) or (step.key == "otp" and bool(order.otp))


def order_stage(order: Order) -> str:
    """The key of the next step of the flow, from what the order already has,
    or "confirmed"."""
    if order.confirmed:
        return "confirmed"
    for index, step in enumerate(order.flow):
        if step.key == "items" and order.items:
            # The customer may add more items until they answer a later step
            if any(_step_started(order, later) for later in order.flow[index + 1 :]):
                continue
            return "items"
        if not step_done(order, step):
            return step.key
    return "confirmed"


def _missing_before(order: Order, key: str | None) -> list[str]:
    """Labels of required steps before the step `key` (all steps for None)
    that the order does not have yet."""
    missing = []
    for step in order.flow:
        if step.key == key or step.key == "otp":
            break
        if step.required and not step_done(order, step):
            missing.append(step.label.lower())
    return missing


def spoken_digits(text: str) -> str:
    """
    The digits in text, as written or spoken. Customers in India say
    "double nine" for 99 and "triple zero" for 000. Other words are skipped.
    """
    tokens = re.findall(r"[a-z]+|\d+", text.lower())
    digits = ""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        repeat = REPEAT_WORDS.get(token)
        following = tokens[i + 1] if i + 1 < len(tokens) else ""
        if repeat and following:
            digit = DIGIT_WORDS.get(following) or REPEATED_MISHEARS.get(following)
            if following.isdigit():
                # "double 9" → 99. "double 99": the STT already wrote both.
                digit = following if len(following) > 1 else following * repeat
                repeat = 1
            if digit:
                digits += digit * repeat
                i += 2
                continue
        if token.isdigit():
            digits += token
        elif token in DIGIT_WORDS:
            digits += DIGIT_WORDS[token]
        i += 1
    return digits


def normalize_phone(text: str) -> str | None:
    """The 10-digit Indian mobile number in text, without +91, or None."""
    digits = spoken_digits(text)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits if len(digits) == 10 else None


def spoken_pincode(text: str) -> str | None:
    """A 6-digit pincode in text, written or spoken ("five six zero zero three
    four"), or None. Numbers apart from it, like the door number, are skipped
    when other words separate them."""
    tokens = re.findall(r"[a-z]+|\d+", text.lower())
    runs, run = [], []
    for token in tokens:
        if token.isdigit() or token in DIGIT_WORDS or token in REPEAT_WORDS:
            run.append(token)
        elif token in REPEATED_MISHEARS and run and run[-1] in REPEAT_WORDS:
            run.append(token)
        else:
            runs.append(run)
            run = []
    runs.append(run)
    for digits in (spoken_digits(" ".join(r)) for r in runs if r):
        if delivery.PINCODE.fullmatch(digits):
            return digits
    return None


def _closed_message(order: Order) -> str | None:
    if order.confirmed:
        return "This order is already confirmed and can no longer be changed."
    return None


def save_customer_name(name: str) -> str:
    """Save the customer's name. Call this as soon as the customer says it."""
    order = current_order.get()
    order.name = name.strip()
    return f"Saved customer name: {order.name}."


def save_delivery_address(
    door_number: str, street: str, pincode: str, area: str = ""
) -> str:
    """Check that we deliver to the customer's pincode and save the address.
    Call this before taking the order, with the parts the customer has said:
    door number (e.g. "12B"), street (e.g. "5th Cross, 4th Block"), 6-digit
    pincode, and area if they name it (e.g. "Koramangala"). Pass "" for parts
    they have not said yet: the result tells you what to ask for next."""
    order = current_order.get()
    if closed := _closed_message(order):
        return closed
    parts = order.address_parts
    for key, value in (
        ("door_number", door_number),
        ("street", street),
        ("area", area),
    ):
        if value := " ".join(str(value).split()):
            parts[key] = value

    if pincode := spoken_digits(str(pincode)):
        if not delivery.PINCODE.fullmatch(pincode):
            parts.pop("pincode", None)
            return f"{pincode} is not a 6-digit pincode. Ask for the pincode again."
        found = delivery.check(pincode)
        if not found or not found["delivers"]:
            # They will give another address, so nothing of this one is kept
            parts.clear()
            place = (
                f"{found['areas'][0]} ({pincode})"
                if found and found["areas"]
                else pincode
            )
            return (
                f"We don't deliver to {place}. Apologise, and ask if they have "
                "another address with a pincode we deliver to."
            )
        parts["pincode"] = pincode

    missing = [label for key, label in ADDRESS_PARTS.items() if not parts.get(key)]
    if missing:
        heard = ", ".join(f"{k}={v}" for k, v in parts.items()) or "nothing"
        hint = ""
        if "pincode" in missing and (guess := _guess_pincode(parts)):
            hint = (
                f" {guess['area']} is pincode {guess['pincode']}: check it with them."
            )
        ask = (
            "Ask for it."
            if len(missing) == 1
            else "Ask for them, one or two at a time."
        )
        return (
            f"Address so far: {heard}. Still needed: {', '.join(missing)}. {ask}{hint}"
        )

    found = delivery.check(parts["pincode"])
    area = parts.get("area") or (found["areas"][0] if found["areas"] else "")
    order.address = (
        ", ".join(p for p in (parts["door_number"], parts["street"], area) if p)
        + f", {found['city']} {parts['pincode']}"
    )
    order.address_verified = True
    return (
        f"We deliver there ({found['city']}, {found['zone']} zone). Address saved: "
        f"{order.address}. Continue to the next step."
    )


def _guess_pincode(parts: dict[str, str]) -> dict | None:
    """A pincode for the area or street the customer named, if one matches."""
    text = f"{parts.get('area', '')} {parts.get('street', '')}"
    matches = delivery.pincodes_for_area(text)
    return matches[0] if matches else None


def add_to_order(item: str, quantity: int) -> str:
    """Add an item from the menu to the customer's order. The result tells
    the item's price and the new order total."""
    order = current_order.get()
    if closed := _closed_message(order):
        return closed
    if missing := _missing_before(order, "items"):
        return f"Before taking items, ask for: {', '.join(missing)}."
    matches = match_menu_items(item)
    if not matches:
        return (
            f"'{item}' is not on the menu. Tell the customer and suggest dishes "
            "from the menu."
        )
    if len(matches) > 1:
        options = ", ".join(f"{name} (₹{price})" for name, price in matches)
        return f"'{item}' could be: {options}. Ask the customer which one they want."
    [(name, price)] = matches
    order.items.append((name, quantity, price))
    return (
        f"Added {quantity} x {name} at ₹{price} each. "
        f"Order total is now ₹{order.total()}."
    )


def get_order_total() -> str:
    """The items in the customer's order with their prices, and the total.
    Call this when the customer asks how much the order costs."""
    order = current_order.get()
    if not order.items:
        return "The order has no items yet."
    return f"Items: {order.items_text()}. Total: ₹{order.total()} including GST."


def set_payment_method(method: str) -> str:
    """Save the payment method the customer chose. Only "UPI" or "Credit Card"."""
    order = current_order.get()
    if closed := _closed_message(order):
        return closed
    normalized = method.strip().lower().replace("-", " ")
    if "upi" in normalized:
        order.payment_method = "UPI"
    elif "credit" in normalized or "card" in normalized:
        order.payment_method = "Credit Card"
    else:
        return (
            f"Unknown payment method '{method}'. "
            "Ask the customer to choose UPI or Credit Card."
        )
    return f"Payment method set to {order.payment_method}."


def save_phone_number(phone_number: str) -> str:
    """Save the customer's 10-digit mobile number. Call this as soon as the
    customer says it."""
    order = current_order.get()
    if closed := _closed_message(order):
        return closed
    digits = normalize_phone(phone_number)
    if not digits:
        return "Not a valid 10-digit phone number. Ask the customer to repeat it."
    if digits != order.phone:
        # An OTP sent to the old number no longer counts
        order.otp = ""
        order.otp_attempts = 0
    order.phone = digits
    return f"Saved phone number +91 {digits}."


def send_otp() -> str:
    """Send a one-time password (OTP) to the saved phone number. Call this when
    every other step is done, then ask the customer to read out the OTP."""
    order = current_order.get()
    if closed := _closed_message(order):
        return closed

    if missing := _missing_before(order, None):
        return f"Cannot send OTP yet. Still missing: {', '.join(missing)}."

    order.otp = f"{random.randrange(10**OTP_DIGITS):0{OTP_DIGITS}d}"
    order.otp_attempts = 0
    # The customer record is keyed by phone number
    store.save_customer(order.phone, order.name)
    # No SMS provider is wired up yet, so the OTP is printed to the server log
    print(f"OTP: sending {order.otp} to +91 {order.phone}")
    return (
        f"OTP sent to +91 {order.phone}. Ask the customer to read out the 4-digit OTP."
    )


def verify_otp(otp: str) -> str:
    """Check the OTP the customer read out. If it is correct, the order is
    confirmed and sent to the kitchen."""
    order = current_order.get()
    if closed := _closed_message(order):
        return closed
    if not order.otp:
        return "No OTP has been sent yet. Call send_otp first."

    if spoken_digits(otp) != order.otp:
        order.otp_attempts += 1
        if order.otp_attempts >= MAX_OTP_ATTEMPTS:
            order.otp = ""
            return "Wrong OTP too many times. Offer to send a new OTP."
        return "Wrong OTP. Ask the customer to check and read it again."

    order.confirmed = True
    _record_order(order, "confirmed")
    print(f"Order confirmed: {order.summary()}")
    return f"Order confirmed and sent to the kitchen. {order.summary()}"


def save_order_detail(step: str, value: str) -> str:
    """Save the customer's answer to a custom step of the ordering flow. `step`
    is the step key named in your instructions."""
    order = current_order.get()
    if closed := _closed_message(order):
        return closed
    target = next((s for s in order.flow if s.key == step and s.kind == "custom"), None)
    if target is None:
        keys = ", ".join(s.key for s in order.flow if s.kind == "custom") or "none"
        return f"Unknown step '{step}'. The custom steps are: {keys}."
    answer = value.strip()
    match = next((c for c in target.choices if c.lower() in answer.lower()), None)
    # A short "no thanks" or "skip" on an optional step, unless it names a choice
    declined = not answer or (
        match is None and len(answer.split()) <= 4 and SKIP_WORDS.search(answer)
    )
    if declined and not target.required:
        order.details[target.key] = "none"
        return f"{target.label}: skipped."
    if not answer:
        return f"Ask the customer: {target.ask}"
    if target.choices:
        if match is None:
            return (
                f"'{value}' is not one of the choices for {target.label}. "
                f"Ask the customer to choose: {', '.join(target.choices)}."
            )
        answer = match
    order.details[target.key] = answer
    return f"Saved {target.label}: {answer}."


def cancel_order() -> str:
    """Cancel the customer's order. Only possible before the order is confirmed."""
    order = current_order.get()
    if order.confirmed:
        return "This order is already confirmed and can no longer be cancelled."
    if order.phone and order.items:
        _record_order(order, "cancelled")
    order.items.clear()
    order.payment_method = ""
    # The phone number stays: it is the customer's, not the order's
    order.otp = ""
    print(f"Order cancelled for {order.name or 'customer'}")
    return "Order cancelled. The customer can start a new order if they want."


ORDER_TOOLS = [
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
