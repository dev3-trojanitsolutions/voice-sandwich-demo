"""
Where the shop delivers: cities, their zones and the pincodes in each zone.

Staff edit the areas on the desk (Delivery). The first start copies them from
knowledge/delivery_areas.json, which scripts/fetch_pincodes.py builds from
India Post data. The agent checks the customer's pincode here
(orders.save_delivery_address). A change on the desk applies to the next
address the agent checks, with no restart.

A pincode is delivered to only when it, its zone and its city are all active,
so staff can pause a whole zone (for example the outskirts) in one switch.
"""

import json
import re
from pathlib import Path

import store

SEED_FILE = Path(__file__).parent.parent / "knowledge" / "delivery_areas.json"

NAME_MAX = 60
AREAS_MAX = 20
AREA_MAX = 80
PINCODE = re.compile(r"[1-9]\d{5}")


def seed() -> None:
    """Copy the seed file into the store on the first start."""
    if store.get_setting("delivery_seeded") == "1":
        return
    if SEED_FILE.exists():
        store.replace_delivery(json.loads(SEED_FILE.read_text())["cities"])
    store.set_setting("delivery_seeded", "1")


def reset() -> None:
    """Replace every area with the seed file. Staff edits are lost."""
    store.replace_delivery(json.loads(SEED_FILE.read_text())["cities"])


def check(pincode: str) -> dict | None:
    """The pincode's areas, zone and city, and 'delivers', or None if the
    pincode is not in any zone."""
    return store.find_pincode(pincode)


def pincodes_for_area(text: str) -> list[dict]:
    """Pincodes whose locality names appear in text, best match first. Lets the
    agent suggest a pincode when the customer only names their area."""
    words = _normalize(text)
    matches = []
    for city in store.list_delivery():
        for zone in city["zones"]:
            for pin in zone["pincodes"]:
                for area in pin["areas"]:
                    name = _normalize(area)
                    if len(name) >= 4 and re.search(rf"\b{re.escape(name)}\b", words):
                        matches.append((len(name), pin["pincode"], area))
    matches.sort(reverse=True)
    return [{"pincode": p, "area": a} for _, p, a in matches]


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


# Desk edits. Each raises ValueError with a message for staff.


def clean_name(name: str, what: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValueError(f"Enter a name for the {what}.")
    if len(name) > NAME_MAX:
        raise ValueError(f"A {what} name can have at most {NAME_MAX} characters.")
    return name


def clean_list(items: list[str], limit: int = AREAS_MAX) -> list[str]:
    items = [" ".join(str(i).split()) for i in items]
    items = list(dict.fromkeys(i for i in items if i))
    if len(items) > limit:
        raise ValueError(f"Enter at most {limit} names.")
    if any(len(i) > AREA_MAX for i in items):
        raise ValueError(f"A name can have at most {AREA_MAX} characters.")
    return items


def clean_pincode(pincode: str, old: str | None = None) -> str:
    """A valid 6-digit pincode that no other zone has yet."""
    pincode = re.sub(r"\s", "", pincode)
    if not PINCODE.fullmatch(pincode):
        raise ValueError("A pincode has 6 digits and does not start with 0.")
    if pincode != old and (taken := store.find_pincode(pincode)):
        raise ValueError(f"{pincode} is already in {taken['city']} · {taken['zone']}.")
    return pincode
