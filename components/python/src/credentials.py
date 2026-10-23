"""
The Gemini API key, set on the desk (Settings → Gemini).

The key saved on the desk wins. Without one, GOOGLE_API_KEY (or
GEMINI_API_KEY) from .env is the fallback. The first start copies the .env key
to the desk, so after that .env doesn't need it.

The key is kept in the settings table of the SQLite store, as plain text: keep
components/python/data/ private. The desk API never sends the key back, only
its last four characters.
"""

import os

from google import genai
from google.genai import errors

import store

SETTING = "gemini_api_key"
IMPORTED = "gemini_api_key_imported"
KEY_MAX = 200


def _env_key() -> str:
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""


def import_env_key() -> None:
    """Copy the .env key to the desk on the first start."""
    if store.get_setting(IMPORTED) == "1":
        return
    if _env_key() and not store.get_setting(SETTING):
        store.set_setting(SETTING, _env_key())
        print("Desk: copied the Gemini API key from .env to Settings")
    store.set_setting(IMPORTED, "1")


def gemini_key() -> str:
    """The key to call Gemini with, or "" when none is set."""
    return store.get_setting(SETTING) or _env_key()


def gemini_status() -> dict:
    """What the desk shows: whether a key is set, where it comes from, and
    its last four characters."""
    saved = store.get_setting(SETTING) or ""
    key = saved or _env_key()
    return {
        "set": bool(key),
        "source": "desk" if saved else ("env" if key else ""),
        "hint": key[-4:] if len(key) > 8 else "",
    }


def check_gemini_key(key: str) -> None:
    """Ask Google whether the key works. Raises ValueError with a message for
    staff."""
    try:
        # Keep the client: it closes its connection when garbage collected
        client = genai.Client(api_key=key)
        next(iter(client.models.list(config={"page_size": 1})))
    except errors.ClientError as e:
        raise ValueError(f"Google refused this key. Check it and try again. ({e.code})")
    except StopIteration:
        pass
    except Exception as e:
        raise ValueError(f"Can't reach Google to check the key. ({e})")


def save_gemini_key(key: str) -> dict:
    key = key.strip()
    if not key:
        raise ValueError("Paste the API key.")
    if len(key) > KEY_MAX or any(c.isspace() for c in key):
        raise ValueError("This doesn't look like an API key.")
    check_gemini_key(key)
    store.set_setting(SETTING, key)
    return gemini_status()


def remove_gemini_key() -> dict:
    """Forget the desk key. The .env key, if any, is used again."""
    store.set_setting(SETTING, "")
    return gemini_status()
