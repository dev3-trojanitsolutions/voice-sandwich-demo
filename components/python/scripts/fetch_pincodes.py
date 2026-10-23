"""
Builds knowledge/delivery_areas.json, the delivery areas the desk starts with.

The data comes from India Post through api.postalpincode.in (free, no key).
It is the same data as the All India Pincode Directory on data.gov.in. Each
pincode has its post offices (the locality names) and its postal division,
which this script uses as the zone.

Run from the project root:

    make fetch-pincodes

The result only seeds an empty database. After the first start, staff edit
the areas on the desk (Delivery). To load a new file into an existing
database, use "Reset to India Post data" on the desk.
"""

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUT = Path(__file__).parent.parent / "knowledge" / "delivery_areas.json"
API = "https://api.postalpincode.in/pincode/{}"

CITY = "Bengaluru"
ALIASES = ["bengaluru", "bangalore", "blr"]
# Bengaluru city pincodes are 560001–560300. Some outer areas (Sarjapura,
# Anekal, the airport) have 562xxx pincodes in the Bangalore district.
CITY_PINCODES = [f"560{n:03d}" for n in range(1, 301)]
OUTER_PINCODES = [f"562{n:03d}" for n in range(101, 200)]
DISTRICT = "Bangalore"

# Postal division → zone name. Pincodes in other divisions go to Outskirts.
ZONES = {
    "Bangalore GPO": "Central",
    "Bangalore East": "East",
    "Bangalore West": "West",
    "Bangalore North": "North",
    "Bangalore South": "South",
}
OUTSKIRTS = "Outskirts"
# Zones that start switched off: far from the restaurant
INACTIVE_ZONES = {OUTSKIRTS}


def fetch(pincode: str) -> list[dict]:
    """The post offices of a pincode, or [] if it does not exist."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(API.format(pincode), timeout=20) as response:
                data = json.load(response)[0]
            if data["Status"] != "Success":
                return []
            return data["PostOffice"] or []
        except OSError:
            time.sleep(1 + attempt)
    raise RuntimeError(f"Can't fetch pincode {pincode}")


def zone_of(offices: list[dict]) -> str:
    """The zone of the post office that delivers, else of the first office."""
    delivering = [o for o in offices if o["DeliveryStatus"] == "Delivery"] or offices
    return ZONES.get(delivering[0]["Division"], OUTSKIRTS)


def areas_of(offices: list[dict]) -> list[str]:
    """Locality names, the post offices that deliver first."""
    ordered = sorted(offices, key=lambda o: o["DeliveryStatus"] != "Delivery")
    return list(dict.fromkeys(o["Name"].strip() for o in ordered))


def main() -> None:
    pincodes = CITY_PINCODES + OUTER_PINCODES
    with ThreadPoolExecutor(6) as pool:
        results = dict(zip(pincodes, pool.map(fetch, pincodes)))

    zones: dict[str, list[dict]] = {name: [] for name in [*ZONES.values(), OUTSKIRTS]}
    for pincode, offices in results.items():
        if not offices:
            continue
        if pincode in OUTER_PINCODES and offices[0]["District"] != DISTRICT:
            continue
        zones[zone_of(offices)].append({"pincode": pincode, "areas": areas_of(offices)})

    city = {
        "name": CITY,
        "aliases": ALIASES,
        "zones": [
            {"name": name, "active": name not in INACTIVE_ZONES, "pincodes": pins}
            for name, pins in zones.items()
            if pins
        ],
    }
    data = {
        "source": "India Post, via api.postalpincode.in",
        "fetched": time.strftime("%Y-%m-%d"),
        "cities": [city],
    }
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    counts = ", ".join(f"{z['name']} {len(z['pincodes'])}" for z in city["zones"])
    print(f"Wrote {OUT}: {counts}")


if __name__ == "__main__":
    main()
