"""
The business details staff set on the desk (Settings → Business): name,
description, contact details, an icon emoji and a logo.

The order page, the desk and the login page show the name and the logo (or
the icon when there is no logo). The agent says the name in its greeting, and
the prompts tell it the description and the contact details, so it can answer
"what's your phone number?". A change applies to the next session.

The details are one JSON value in the settings table. The logo is a file in
components/python/data/brand/.
"""

import json
import re
import time

import store

DEFAULTS = {
    "name": "Ustad Hotel",
    "description": "an Indian restaurant",
    "city": "Bangalore",
    "phone": "",
    "email": "",
    "address": "",
    "icon": "🍛",
}

# Longest text for each field
LIMITS = {
    "name": 60,
    "description": 120,
    "city": 60,
    "phone": 30,
    "email": 120,
    "address": 300,
    "icon": 8,
}

LOGO_DIR = store.DB_PATH.parent / "brand"
LOGO_MAX_BYTES = 1024 * 1024

# Raster images only: an SVG can hold scripts. Each type by its first bytes.
LOGO_TYPES = {
    "image/png": lambda d: d.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda d: d.startswith(b"\xff\xd8\xff"),
    "image/gif": lambda d: d[:6] in (b"GIF87a", b"GIF89a"),
    "image/webp": lambda d: d[:4] == b"RIFF" and d[8:12] == b"WEBP",
}
EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _stored() -> dict:
    return json.loads(store.get_setting("brand") or "{}")


def get() -> dict:
    """The details, with defaults for fields never set, and the logo version
    (0 for no logo; it changes with each upload, for the browser cache)."""
    stored = _stored()
    details = {key: stored.get(key, default) for key, default in DEFAULTS.items()}
    details["logo_version"] = stored.get("logo_version", 0) if logo_file() else 0
    return details


def save(fields: dict[str, str]) -> dict:
    """Check and save the text fields. Raises ValueError with a message for
    staff."""
    clean = {}
    for key in DEFAULTS:
        value = " ".join(str(fields.get(key, "")).split())
        if len(value) > LIMITS[key]:
            raise ValueError(f"Keep the {key} under {LIMITS[key]} characters.")
        clean[key] = value
    if not clean["name"]:
        raise ValueError("Enter the business name.")
    if clean["email"] and not EMAIL.fullmatch(clean["email"]):
        raise ValueError("Enter a valid email address, or leave it empty.")
    store.set_setting("brand", json.dumps(_stored() | clean))
    return get()


def logo_file():
    """The saved logo and its media type, or None."""
    for media_type, extension in EXTENSIONS.items():
        path = LOGO_DIR / f"logo.{extension}"
        if path.exists():
            return path, media_type
    return None


def set_logo(data: bytes) -> dict:
    """Replace the logo. Raises ValueError for a file that isn't a PNG, JPEG,
    GIF or WebP image, or is too large."""
    if not data:
        raise ValueError("Choose an image file.")
    if len(data) > LOGO_MAX_BYTES:
        raise ValueError("Use a logo smaller than 1 MB.")
    media_type = next((t for t, matches in LOGO_TYPES.items() if matches(data)), None)
    if not media_type:
        raise ValueError("Use a PNG, JPEG, GIF or WebP image.")
    remove_logo()
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    (LOGO_DIR / f"logo.{EXTENSIONS[media_type]}").write_bytes(data)
    store.set_setting(
        "brand", json.dumps(_stored() | {"logo_version": int(time.time())})
    )
    return get()


def remove_logo() -> dict:
    for extension in EXTENSIONS.values():
        (LOGO_DIR / f"logo.{extension}").unlink(missing_ok=True)
    return get()


def shop() -> str:
    """The business for the prompts, e.g. "Ustad Hotel, an Indian restaurant in
    Bangalore"."""
    details = get()
    text = details["name"]
    if details["description"]:
        text += f", {details['description']}"
    if details["city"]:
        text += f" in {details['city']}"
    return text


def contact() -> str:
    """The contact details for the prompts, or "" when none are set."""
    details = get()
    parts = [
        f"{label}: {details[key]}"
        for key, label in (
            ("phone", "Phone"),
            ("email", "Email"),
            ("address", "Address"),
        )
        if details[key]
    ]
    return f"Shop contact details. {'. '.join(parts)}." if parts else ""
