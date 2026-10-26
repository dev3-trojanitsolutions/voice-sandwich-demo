"""
The API keys for the cloud services, set on the desk (Settings → API Keys).

The key saved on the desk wins. Without one, the key from .env is the
fallback. The first start copies each .env key to the desk, so after that
.env doesn't need it.

The keys are kept in the settings table of the SQLite store, as plain text:
keep components/python/data/ private. The desk API never sends a key back,
only its last four characters.
"""

import os
from dataclasses import dataclass
from typing import Callable

import anthropic
import httpx
from google import genai
from google.genai import errors

import store

KEY_MAX = 200
TIMEOUT = 10


def _check_gemini(key: str) -> None:
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


def _check_http(company: str, url: str, headers: dict) -> None:
    try:
        response = httpx.get(url, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise ValueError(f"Can't reach {company} to check the key. ({e})")
    if response.status_code in (401, 403):
        raise ValueError(
            f"{company} refused this key. Check it and try again. "
            f"({response.status_code})"
        )
    if response.status_code >= 400:
        raise ValueError(
            f"{company} couldn't check the key. Try again. ({response.status_code})"
        )


def _check_assemblyai(key: str) -> None:
    _check_http(
        "AssemblyAI",
        "https://api.assemblyai.com/v2/transcript?limit=1",
        {"Authorization": key},
    )


def _check_cartesia(key: str) -> None:
    _check_http(
        "Cartesia",
        "https://api.cartesia.ai/voices?limit=1",
        {"X-API-Key": key, "Cartesia-Version": "2025-04-16"},
    )


def _check_anthropic(key: str) -> None:
    try:
        anthropic.Anthropic(api_key=key, timeout=TIMEOUT).models.list(limit=1)
    except anthropic.AuthenticationError as e:
        raise ValueError(
            f"Anthropic refused this key. Check it and try again. ({e.status_code})"
        )
    except anthropic.APIStatusError as e:
        raise ValueError(
            f"Anthropic couldn't check the key. Try again. ({e.status_code})"
        )
    except anthropic.APIError as e:
        raise ValueError(f"Can't reach Anthropic to check the key. ({e})")


@dataclass(frozen=True)
class Provider:
    name: str
    env: tuple[str, ...]
    check: Callable[[str], None]

    @property
    def setting(self) -> str:
        return f"{self.id}_api_key"

    @property
    def id(self) -> str:
        return self.name.lower()


PROVIDERS = {
    p.id: p
    for p in (
        Provider("Gemini", ("GOOGLE_API_KEY", "GEMINI_API_KEY"), _check_gemini),
        Provider("AssemblyAI", ("ASSEMBLYAI_API_KEY",), _check_assemblyai),
        Provider("Cartesia", ("CARTESIA_API_KEY",), _check_cartesia),
        Provider("Anthropic", ("ANTHROPIC_API_KEY",), _check_anthropic),
    )
}


def provider(provider_id: str) -> Provider:
    """The provider, or KeyError for an unknown id."""
    return PROVIDERS[provider_id]


def _env_key(p: Provider) -> str:
    return next((os.getenv(name) for name in p.env if os.getenv(name)), "")


def import_env_keys() -> None:
    """Copy each .env key to the desk on the first start."""
    for p in PROVIDERS.values():
        imported = f"{p.setting}_imported"
        if store.get_setting(imported) == "1":
            continue
        if _env_key(p) and not store.get_setting(p.setting):
            store.set_setting(p.setting, _env_key(p))
            print(f"Desk: copied the {p.name} API key from .env to Settings")
        store.set_setting(imported, "1")


def key(provider_id: str) -> str:
    """The key to call the service with, or "" when none is set."""
    p = provider(provider_id)
    return store.get_setting(p.setting) or _env_key(p)


def gemini_key() -> str:
    return key("gemini")


def status(provider_id: str) -> dict:
    """What the desk shows: whether a key is set, where it comes from, and
    its last four characters."""
    p = provider(provider_id)
    saved = store.get_setting(p.setting) or ""
    found = saved or _env_key(p)
    return {
        "id": p.id,
        "name": p.name,
        "env": p.env[0],
        "set": bool(found),
        "source": "desk" if saved else ("env" if found else ""),
        "hint": found[-4:] if len(found) > 8 else "",
    }


def all_status() -> list[dict]:
    return [status(p) for p in PROVIDERS]


def save(provider_id: str, new_key: str) -> dict:
    """Check the key with the service, then save it. Raises ValueError with a
    message for staff."""
    p = provider(provider_id)
    new_key = new_key.strip()
    if not new_key:
        raise ValueError("Paste the API key.")
    if len(new_key) > KEY_MAX or any(c.isspace() for c in new_key):
        raise ValueError("This doesn't look like an API key.")
    p.check(new_key)
    store.set_setting(p.setting, new_key)
    return status(provider_id)


def remove(provider_id: str) -> dict:
    """Forget the desk key. The .env key, if any, is used again."""
    store.set_setting(provider(provider_id).setting, "")
    return status(provider_id)
