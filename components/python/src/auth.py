"""
Desk login, users, roles and permissions.

Each user has one role, and a role is a set of permissions. Every page and
API call needs a login, except the login and logout pages and their assets.
The middleware in main.py calls `check_access` for every request: a page sends
visitors without a session to the login page, and the desk API also needs the
permission for the route. The voice agent (/ws) checks the session in
main.py, because the middleware doesn't see WebSocket connections.

The first start creates the user "admin" with the password "1234" and the
Admin role. Set a new password with `make set-admin-password` (terminal) or on
the desk (Account) after the first login.

Passwords are hashed with scrypt. A login sets a random session token in an
HttpOnly cookie; the store keeps only its SHA-256 hash.
"""

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.requests import HTTPConnection

import store

# What a role can allow. Each desk section has "view", and "edit" where staff
# can change something there.
PERMISSIONS: dict[str, str] = {
    "conversations.view": "See conversations",
    "customers.view": "See customers and their orders",
    "customers.edit": "Add and rename customers",
    "training.view": "See the knowledge modules and test questions",
    "training.edit": "Change the knowledge modules",
    "flow.view": "See the ordering flow",
    "flow.edit": "Change the ordering flow",
    "delivery.view": "See the delivery areas",
    "delivery.edit": "Change the delivery areas",
    "settings.view": "See the voice model and the voices",
    "settings.edit": "Change the voice model and the voices",
    "users.manage": "Manage users and roles",
}

ADMIN_ROLE = "Admin"

# Built-in roles, created on the first start. Admin always has every
# permission and can't be changed or deleted. The others can be edited.
BUILTIN_ROLES: dict[str, list[str]] = {
    ADMIN_ROLE: list(PERMISSIONS),
    "Manager": [p for p in PERMISSIONS if p != "users.manage"],
    "Staff": [
        "conversations.view",
        "customers.view",
        "customers.edit",
        "training.view",
        "flow.view",
        "delivery.view",
    ],
}

FIRST_USER = ("admin", "Administrator", "1234")

COOKIE = "desk_session"
SESSION_SECONDS = 7 * 24 * 3600

USERNAME = re.compile(r"[a-z0-9._-]{2,32}")
PASSWORD_MIN = 4
PASSWORD_MAX = 128
NAME_MAX = 60

# After this many failed logins for a username, wait LOCK_SECONDS
MAX_FAILURES = 5
LOCK_SECONDS = 60

# Desk API routes by their first path segment (/api/<segment>/...), and the
# desk section whose permissions they need. GET needs "<section>.view", other
# methods "<section>.edit". "users" needs "users.manage" for every method.
API_SECTIONS = {
    "conversations": "conversations",
    "customers": "customers",
    "modules": "training",
    "sections": "training",
    "knowledge": "training",
    "flow": "flow",
    "delivery": "delivery",
    "settings": "settings",
    "brand": "settings",
    "voices": "settings",
    "users": "users",
    "roles": "users",
}

# POST routes that only read, so "view" is enough
READ_ONLY_POSTS = [
    re.compile(r"/api/knowledge/test"),
    re.compile(r"/api/voices/\d+/preview"),
]

# Open to everyone: logging in and out (logout works with an ended session
# too), and the business name and logo, which the login page shows
PUBLIC_API = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/brand"),
    ("GET", "/api/brand/logo"),
}

# Pages and files open to everyone: the login and logout pages and the built
# scripts and styles they load
PUBLIC_PAGES = {"/login", "/login/", "/logout", "/logout/", "/favicon.ico"}
PUBLIC_PREFIXES = ("/login/", "/logout/", "/assets/")

# Any logged-in user: the order page header shows the voice model
LOGIN_ONLY_API = {("GET", "/api/settings")}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1
    )
    return hmac.compare_digest(candidate.hex(), digest)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def seed_roles() -> None:
    """Create the built-in roles. Admin gets any permission added since the
    last start."""
    for name, permissions in BUILTIN_ROLES.items():
        role = store.find_role(name)
        if not role:
            store.add_role(name, permissions, builtin=True)
        elif name == ADMIN_ROLE:
            store.update_role(role["id"], name, permissions)


def seed() -> None:
    """Create the built-in roles, and the first admin when there are no users."""
    seed_roles()
    if store.count_users() == 0:
        username, name, password = FIRST_USER
        role_id = store.find_role(ADMIN_ROLE)["id"]
        store.add_user(username, name, hash_password(password), role_id)
        print(f"Desk: created the first user '{username}' (password '{password}')")


def current_user(connection: HTTPConnection) -> dict | None:
    """The user of the session cookie, for a request or a WebSocket."""
    token = connection.cookies.get(COOKIE)
    return store.session_user(_token_hash(token)) if token else None


@dataclass
class Access:
    """The result of check_access: allowed, or the reason it isn't."""

    allowed: bool
    status: int = 200
    detail: str = ""
    redirect: str = ""


def _required_permission(method: str, path: str) -> str | None:
    """The permission an /api route needs, or None for an unknown route."""
    segment = path.removeprefix("/api/").split("/")[0]
    section = API_SECTIONS.get(segment)
    if section is None:
        return None
    if section == "users":
        return "users.manage"
    reads = method in ("GET", "HEAD") or (
        method == "POST" and any(p.fullmatch(path) for p in READ_ONLY_POSTS)
    )
    return f"{section}.{'view' if reads else 'edit'}"


def check_access(request: Request) -> Access:
    """Whether the request may go on. Sets request.state.user."""
    method, path = request.method, request.url.path
    request.state.user = None
    if (
        method == "OPTIONS"
        or (method, path) in PUBLIC_API
        or path in PUBLIC_PAGES
        or path.startswith(PUBLIC_PREFIXES)
    ):
        return Access(True)

    is_api = path.startswith("/api/")
    user = current_user(request)
    request.state.user = user
    if not user:
        if not is_api:
            # Come back to this page after the login
            return Access(False, redirect=f"/login/?next={quote(path)}")
        return Access(False, 401, "Log in first.")
    if not is_api or path.startswith("/api/auth/") or (method, path) in LOGIN_ONLY_API:
        return Access(True)

    permission = _required_permission(method, path)
    if permission is None or permission not in user["permissions"]:
        return Access(False, 403, "Your role doesn't allow this. Ask an admin.")
    return Access(True)


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "name": user["name"],
        "role_id": user["role_id"],
        "role_name": user["role_name"],
        "permissions": user["permissions"],
        "active": user["active"],
        "created_at": user["created_at"],
        "last_login_at": user["last_login_at"],
    }


def _clean_username(username: str) -> str:
    username = username.strip().lower()
    if not USERNAME.fullmatch(username):
        raise HTTPException(
            400,
            "Use 2–32 lowercase letters, digits, dots, dashes or underscores "
            "for the username.",
        )
    return username


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise HTTPException(400, "Enter the user's name.")
    if len(name) > NAME_MAX:
        raise HTTPException(400, f"Keep the name under {NAME_MAX} characters.")
    return name


def _check_password(password: str) -> str:
    if len(password) < PASSWORD_MIN:
        raise HTTPException(
            400, f"Use a password of at least {PASSWORD_MIN} characters."
        )
    if len(password) > PASSWORD_MAX:
        raise HTTPException(400, f"Keep the password under {PASSWORD_MAX} characters.")
    return password


def _role_or_400(role_id: int) -> dict:
    role = store.get_role(role_id)
    if not role:
        raise HTTPException(400, "Choose a role.")
    return role


def _user_or_404(user_id: int) -> dict:
    user = store.get_user(user_id)
    if not user:
        raise HTTPException(404, "This user no longer exists.")
    return user


def _check_manager_remains(users: list[dict]) -> None:
    """Refuse a change that leaves no active user who can manage users."""
    if not any(u["active"] and "users.manage" in u["permissions"] for u in users):
        raise HTTPException(400, "Keep at least one active user who can manage users.")


router = APIRouter()

# username → (failure count, time of the last failure)
_failures: dict[str, tuple[int, float]] = {}


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    current: str
    new: str


class UserIn(BaseModel):
    username: str
    name: str
    role_id: int
    active: bool = True
    # Required for a new user. On an edit, empty keeps the password.
    password: str = ""


class RoleIn(BaseModel):
    name: str
    permissions: list[str]


@router.post("/api/auth/login")
def login(credentials: LoginIn, request: Request, response: Response):
    username = credentials.username.strip().lower()
    count, last = _failures.get(username, (0, 0.0))
    if count >= MAX_FAILURES and time.time() - last < LOCK_SECONDS:
        raise HTTPException(429, "Too many failed logins. Wait a minute and try again.")

    found = store.find_user_login(username)
    if not found or not verify_password(credentials.password, found[1]):
        _failures[username] = (count + 1, time.time())
        raise HTTPException(401, "The username or password is wrong.")
    user_id, _, active = found
    if not active:
        raise HTTPException(403, "This user is deactivated. Ask an admin.")

    _failures.pop(username, None)
    token = secrets.token_urlsafe(32)
    store.add_session(_token_hash(token), user_id, time.time() + SESSION_SECONDS)
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    print(f"Desk: {username} logged in")
    return _public_user(store.get_user(user_id))


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        store.delete_session(_token_hash(token))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request):
    return _public_user(request.state.user)


@router.put("/api/auth/password")
def change_password(change: PasswordIn, request: Request):
    user = request.state.user
    if not verify_password(change.current, store.get_password_hash(user["id"])):
        raise HTTPException(400, "The current password is wrong.")
    store.set_password_hash(user["id"], hash_password(_check_password(change.new)))
    # Log out other devices; this one stays logged in
    token = request.cookies.get(COOKIE, "")
    store.delete_user_sessions(user["id"], keep=_token_hash(token))
    return {"ok": True}


@router.get("/api/users")
def get_users():
    return [_public_user(u) for u in store.list_users()]


@router.post("/api/users", status_code=201)
def create_user(user: UserIn):
    username = _clean_username(user.username)
    name = _clean_name(user.name)
    _role_or_400(user.role_id)
    if not user.password:
        raise HTTPException(400, "Enter a password for the new user.")
    if store.find_user_login(username):
        raise HTTPException(400, f"The username '{username}' is taken.")
    user_id = store.add_user(
        username, name, hash_password(_check_password(user.password)), user.role_id
    )
    if not user.active:
        store.update_user(user_id, username, name, user.role_id, False)
    return _public_user(store.get_user(user_id))


@router.put("/api/users/{user_id}")
def edit_user(user_id: int, user: UserIn, request: Request):
    _user_or_404(user_id)
    username = _clean_username(user.username)
    name = _clean_name(user.name)
    role = _role_or_400(user.role_id)
    other = store.find_user_login(username)
    if other and other[0] != user_id:
        raise HTTPException(400, f"The username '{username}' is taken.")
    if user_id == request.state.user["id"] and not user.active:
        raise HTTPException(400, "You can't deactivate yourself.")

    after = [
        u | {"active": user.active, "permissions": role["permissions"]}
        if u["id"] == user_id
        else u
        for u in store.list_users()
    ]
    _check_manager_remains(after)

    store.update_user(user_id, username, name, user.role_id, user.active)
    if user.password:
        store.set_password_hash(user_id, hash_password(_check_password(user.password)))
        if user_id != request.state.user["id"]:
            store.delete_user_sessions(user_id)
    return _public_user(store.get_user(user_id))


@router.delete("/api/users/{user_id}", status_code=204)
def remove_user(user_id: int, request: Request):
    _user_or_404(user_id)
    if user_id == request.state.user["id"]:
        raise HTTPException(400, "You can't delete yourself.")
    _check_manager_remains([u for u in store.list_users() if u["id"] != user_id])
    store.delete_user(user_id)


def _roles_response() -> dict:
    return {
        "roles": store.list_roles(),
        "permissions": [{"id": k, "label": v} for k, v in PERMISSIONS.items()],
    }


def _clean_role(role: RoleIn) -> tuple[str, list[str]]:
    name = " ".join(role.name.split())
    if not name:
        raise HTTPException(400, "Enter a name for the role.")
    if len(name) > NAME_MAX:
        raise HTTPException(400, f"Keep the role name under {NAME_MAX} characters.")
    unknown = [p for p in role.permissions if p not in PERMISSIONS]
    if unknown:
        raise HTTPException(400, f"Unknown permission '{unknown[0]}'.")
    # Keep the order of PERMISSIONS, without duplicates
    return name, [p for p in PERMISSIONS if p in role.permissions]


def _editable_role(role_id: int) -> dict:
    role = store.get_role(role_id)
    if not role:
        raise HTTPException(404, "This role no longer exists.")
    if role["name"] == ADMIN_ROLE and role["builtin"]:
        raise HTTPException(400, "The Admin role always has every permission.")
    return role


@router.get("/api/roles")
def get_roles():
    return _roles_response()


@router.post("/api/roles", status_code=201)
def create_role(role: RoleIn):
    name, permissions = _clean_role(role)
    if store.find_role(name):
        raise HTTPException(400, f"A role named '{name}' already exists.")
    store.add_role(name, permissions)
    return _roles_response()


@router.put("/api/roles/{role_id}")
def edit_role(role_id: int, role: RoleIn):
    _editable_role(role_id)
    name, permissions = _clean_role(role)
    other = store.find_role(name)
    if other and other["id"] != role_id:
        raise HTTPException(400, f"A role named '{name}' already exists.")
    _check_manager_remains(
        [
            u | {"permissions": permissions} if u["role_id"] == role_id else u
            for u in store.list_users()
        ]
    )
    store.update_role(role_id, name, permissions)
    return _roles_response()


@router.delete("/api/roles/{role_id}")
def remove_role(role_id: int):
    role = _editable_role(role_id)
    if any(u["role_id"] == role_id for u in store.list_users()):
        raise HTTPException(
            400, f"Give the users with '{role['name']}' another role first."
        )
    store.delete_role(role_id)
    return _roles_response()
