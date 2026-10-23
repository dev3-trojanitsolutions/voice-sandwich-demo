"""
Persistent shop data: desk settings, customers, their orders, every
conversation with the agent, the knowledge modules the agent answers from, and
the ordering flow it follows, and the areas the shop delivers to. Staff edit
the last three on the desk. Also the desk users, their roles and their login
sessions (see auth.py).

Stored in a SQLite file at components/python/data/shop.db, so it survives
server restarts. Each call opens its own connection, because the order tools
call in from worker threads.
"""

import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

# SHOP_DB_PATH overrides the location, for example to test with a scratch file
DB_PATH = Path(
    os.getenv("SHOP_DB_PATH", Path(__file__).parent.parent / "data" / "shop.db")
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    phone TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL REFERENCES customers(phone),
    address TEXT NOT NULL,
    items TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    status TEXT NOT NULL,
    channel TEXT NOT NULL,
    created_at REAL NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    total INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    started_at REAL NOT NULL,
    ended_at REAL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    tool_name TEXT NOT NULL DEFAULT '',
    tool_args TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_by_conversation ON messages(conversation_id);
CREATE TABLE IF NOT EXISTS modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'notes',
    intro TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER NOT NULL REFERENCES modules(id),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    position INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sections_by_module ON sections(module_id);
CREATE TABLE IF NOT EXISTS flow_steps (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    ask TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    required INTEGER NOT NULL DEFAULT 1,
    choices TEXT NOT NULL DEFAULT '[]',
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS delivery_cities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS delivery_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER NOT NULL REFERENCES delivery_cities(id),
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS delivery_pincodes (
    pincode TEXT PRIMARY KEY,
    zone_id INTEGER NOT NULL REFERENCES delivery_zones(id),
    areas TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS pincodes_by_zone ON delivery_pincodes(zone_id);
CREATE TABLE IF NOT EXISTS voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    accent TEXT NOT NULL DEFAULT '',
    parent_id INTEGER REFERENCES voices(id) ON DELETE CASCADE,
    ref_text TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    permissions TEXT NOT NULL DEFAULT '[]',
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role_id INTEGER NOT NULL REFERENCES roles(id),
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    last_login_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_by_user ON sessions(user_id);
"""

# Voice samples (WAV files), named <voice id>.wav
VOICES_DIR = DB_PATH.parent / "voices"

_migrated = False


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a database from an older version up to SCHEMA."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
    if "details" not in columns:
        # Answers to custom flow steps, as a JSON object
        conn.execute("ALTER TABLE orders ADD COLUMN details TEXT NOT NULL DEFAULT '{}'")
    if "total" not in columns:
        # Order total in rupees; 0 for orders saved before prices
        conn.execute("ALTER TABLE orders ADD COLUMN total INTEGER NOT NULL DEFAULT 0")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    global _migrated
    if not _migrated:
        with conn:
            _migrate(conn)
        _migrated = True
    return conn


def get_setting(key: str) -> str | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def save_customer(phone: str, name: str) -> None:
    """Create the customer, or update the name if the phone is already known."""
    now = time.time()
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO customers (phone, name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(phone) DO UPDATE SET "
            "name = excluded.name, updated_at = excluded.updated_at",
            (phone, name, now, now),
        )


def save_order(
    phone: str,
    address: str,
    items: list[tuple[str, int, int]],
    payment_method: str,
    status: str,
    channel: str,
    details: dict[str, str] | None = None,
    total: int = 0,
) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO orders "
            "(phone, address, items, payment_method, status, channel, created_at, "
            "details, total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                phone,
                address,
                json.dumps(
                    [
                        {"item": item, "quantity": qty, "price": price}
                        for item, qty, price in items
                    ]
                ),
                payment_method,
                status,
                channel,
                time.time(),
                json.dumps(details or {}),
                total,
            ),
        )


def list_customers() -> list[dict]:
    """All customers, most recently active first, each with their orders."""
    with closing(_connect()) as conn:
        customers = conn.execute(
            "SELECT phone, name, created_at, updated_at FROM customers"
        ).fetchall()
        orders = conn.execute(
            "SELECT id, phone, address, items, payment_method, status, channel, "
            "created_at, details, total FROM orders ORDER BY created_at DESC"
        ).fetchall()

    by_phone: dict[str, list[dict]] = {}
    for row in orders:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        order["details"] = json.loads(order["details"] or "{}")
        by_phone.setdefault(order.pop("phone"), []).append(order)

    result = []
    for row in customers:
        customer = dict(row)
        customer["orders"] = by_phone.get(customer["phone"], [])
        last_order = customer["orders"][0]["created_at"] if customer["orders"] else 0
        customer["last_active"] = max(customer["updated_at"], last_order)
        result.append(customer)
    return sorted(result, key=lambda c: c["last_active"], reverse=True)


# Conversations: one row per voice session, with its messages in order.
# role is "customer", "agent" or "tool". A tool message keeps the tool name,
# its arguments as JSON and the result as text.


def start_conversation(channel: str) -> int:
    with closing(_connect()) as conn, conn:
        cursor = conn.execute(
            "INSERT INTO conversations (channel, started_at) VALUES (?, ?)",
            (channel, time.time()),
        )
    return cursor.lastrowid


def add_message(
    conversation_id: int,
    role: str,
    text: str,
    tool_name: str = "",
    tool_args: dict | None = None,
) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO messages "
            "(conversation_id, role, text, tool_name, tool_args, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                text,
                tool_name,
                json.dumps(tool_args) if tool_args is not None else "",
                time.time(),
            ),
        )


def update_conversation(
    conversation_id: int, name: str, phone: str, outcome: str, ended: bool = False
) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE conversations SET name = ?, phone = ?, outcome = ?, "
            "ended_at = CASE WHEN ? THEN ? ELSE ended_at END WHERE id = ?",
            (name, phone, outcome, ended, time.time(), conversation_id),
        )


def delete_conversation(conversation_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))


def end_open_conversations() -> None:
    """Close sessions left open by a server stop, so they don't show as live."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE conversations SET ended_at = ("
            "  SELECT COALESCE(MAX(created_at), conversations.started_at) "
            "  FROM messages WHERE conversation_id = conversations.id"
            ") WHERE ended_at IS NULL"
        )


def list_conversations(limit: int = 200) -> list[dict]:
    """The latest conversations, newest first, with the first thing the customer said."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT c.id, c.channel, c.name, c.phone, c.outcome, c.started_at, "
            "c.ended_at, "
            "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id "
            " AND m.role != 'tool') AS message_count, "
            "(SELECT text FROM messages m WHERE m.conversation_id = c.id "
            " AND m.role = 'customer' ORDER BY m.id LIMIT 1) AS preview "
            "FROM conversations c ORDER BY c.started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) | {"preview": row["preview"] or ""} for row in rows]


def get_conversation(conversation_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, channel, name, phone, outcome, started_at, ended_at "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            return None
        messages = conn.execute(
            "SELECT id, role, text, tool_name, tool_args, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()

    result = dict(row)
    result["messages"] = [
        dict(m) | {"tool_args": json.loads(m["tool_args"]) if m["tool_args"] else None}
        for m in messages
    ]
    return result



# Knowledge modules: the menu, the FAQ and any module staff add. Each module
# has sections in order. kind is "menu", "notes" or "qa" (question and answer).
# The knowledge base indexes every section.

MODULE_COLUMNS = "id, name, kind, intro, position, created_at, updated_at"
SECTION_COLUMNS = "id, module_id, title, body, position, created_at, updated_at"


def list_modules() -> list[dict]:
    """All modules in order, each with its sections in order."""
    with closing(_connect()) as conn:
        modules = conn.execute(
            f"SELECT {MODULE_COLUMNS} FROM modules ORDER BY position, id"
        ).fetchall()
        sections = conn.execute(
            f"SELECT {SECTION_COLUMNS} FROM sections ORDER BY position, id"
        ).fetchall()
    by_module: dict[int, list[dict]] = {}
    for row in sections:
        by_module.setdefault(row["module_id"], []).append(dict(row))
    return [dict(m) | {"sections": by_module.get(m["id"], [])} for m in modules]


def get_module(module_id: int) -> dict | None:
    return next((m for m in list_modules() if m["id"] == module_id), None)


def add_module(name: str, kind: str, intro: str) -> dict:
    now = time.time()
    with closing(_connect()) as conn, conn:
        position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM modules"
        ).fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO modules (name, kind, intro, position, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, kind, intro, position, now, now),
        )
    return get_module(cursor.lastrowid)


def update_module(module_id: int, name: str, kind: str, intro: str) -> dict | None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE modules SET name = ?, kind = ?, intro = ?, updated_at = ? "
            "WHERE id = ?",
            (name, kind, intro, time.time(), module_id),
        )
    return get_module(module_id)


def delete_module(module_id: int) -> bool:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM sections WHERE module_id = ?", (module_id,))
        cursor = conn.execute("DELETE FROM modules WHERE id = ?", (module_id,))
    return cursor.rowcount > 0


def reorder_modules(ids: list[int]) -> None:
    with closing(_connect()) as conn, conn:
        conn.executemany(
            "UPDATE modules SET position = ? WHERE id = ?", list(enumerate(ids))
        )


def get_section(section_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {SECTION_COLUMNS} FROM sections WHERE id = ?", (section_id,)
        ).fetchone()
    return dict(row) if row else None


def add_section(module_id: int, title: str, body: str) -> dict:
    now = time.time()
    with closing(_connect()) as conn, conn:
        position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM sections WHERE module_id = ?",
            (module_id,),
        ).fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO sections "
            "(module_id, title, body, position, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (module_id, title, body, position, now, now),
        )
        conn.execute("UPDATE modules SET updated_at = ? WHERE id = ?", (now, module_id))
    return get_section(cursor.lastrowid)


def update_section(section_id: int, title: str, body: str) -> dict | None:
    now = time.time()
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE sections SET title = ?, body = ?, updated_at = ? WHERE id = ?",
            (title, body, now, section_id),
        )
        conn.execute(
            "UPDATE modules SET updated_at = ? WHERE id = "
            "(SELECT module_id FROM sections WHERE id = ?)",
            (now, section_id),
        )
    return get_section(section_id)


def delete_section(section_id: int) -> bool:
    with closing(_connect()) as conn, conn:
        cursor = conn.execute("DELETE FROM sections WHERE id = ?", (section_id,))
    return cursor.rowcount > 0


def reorder_sections(module_id: int, ids: list[int]) -> None:
    with closing(_connect()) as conn, conn:
        conn.executemany(
            "UPDATE sections SET position = ? WHERE id = ? AND module_id = ?",
            [(position, sid, module_id) for position, sid in enumerate(ids)],
        )


def pop_legacy_training() -> list[dict]:
    """Rows of the old training table, which is then dropped. The first version
    of the desk Training section kept question and answer pairs there."""
    with closing(_connect()) as conn, conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'training'"
        ).fetchone()
        if not exists:
            return []
        rows = conn.execute("SELECT question, answer FROM training ORDER BY id").fetchall()
        conn.execute("DROP TABLE training")
    return [dict(row) for row in rows]


# Flow: the steps the agent asks for, in order. An empty table means the
# default flow in flow.py.


def list_flow_steps() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT key, kind, label, ask, notes, required, choices FROM flow_steps "
            "ORDER BY position"
        ).fetchall()
    return [
        dict(row) | {"required": bool(row["required"]), "choices": json.loads(row["choices"])}
        for row in rows
    ]


def replace_flow_steps(steps: list[dict]) -> None:
    """Save the whole flow in this order. An empty list restores the default."""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM flow_steps")
        conn.executemany(
            "INSERT INTO flow_steps "
            "(key, kind, label, ask, notes, required, choices, position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    step["key"],
                    step["kind"],
                    step["label"],
                    step["ask"],
                    step["notes"],
                    int(step["required"]),
                    json.dumps(step["choices"]),
                    position,
                )
                for position, step in enumerate(steps)
            ],
        )


def _voice_row(row: sqlite3.Row) -> dict:
    return dict(row) | {"file": str(VOICES_DIR / f"{row['id']}.wav")}


def list_voices() -> list[dict]:
    """Every voice: originals (parent_id is None) and their accent versions."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM voices ORDER BY created_at").fetchall()
    return [_voice_row(row) for row in rows]


def get_voice(voice_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
    return _voice_row(row) if row else None


def add_voice(name: str, ref_text: str, accent: str = "", parent_id: int | None = None) -> dict:
    """Add a voice row. The caller writes the sample to the returned 'file'."""
    with closing(_connect()) as conn, conn:
        cursor = conn.execute(
            "INSERT INTO voices (name, accent, parent_id, ref_text, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, accent, parent_id, ref_text, time.time()),
        )
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    return get_voice(cursor.lastrowid)


def delete_voice(voice_id: int) -> list[int]:
    """Delete a voice and its accent versions, with their samples. Returns
    the deleted IDs."""
    with closing(_connect()) as conn, conn:
        ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM voices WHERE id = ? OR parent_id = ?", (voice_id, voice_id)
            )
        ]
        conn.executemany("DELETE FROM voices WHERE id = ?", [(i,) for i in ids])
    for i in ids:
        (VOICES_DIR / f"{i}.wav").unlink(missing_ok=True)
    return ids


# Delivery areas: cities → zones → pincodes. A pincode belongs to one zone.
# It is delivered to only when it, its zone and its city are all active.


def _pincode_row(row: sqlite3.Row) -> dict:
    return {
        "pincode": row["pincode"],
        "areas": json.loads(row["areas"]),
        "active": bool(row["active"]),
    }


def list_delivery() -> list[dict]:
    """Every city with its zones and their pincodes, in order."""
    with closing(_connect()) as conn:
        cities = conn.execute(
            "SELECT * FROM delivery_cities ORDER BY position, id"
        ).fetchall()
        zones = conn.execute(
            "SELECT * FROM delivery_zones ORDER BY position, id"
        ).fetchall()
        pincodes = conn.execute(
            "SELECT * FROM delivery_pincodes ORDER BY pincode"
        ).fetchall()
    by_zone: dict[int, list[dict]] = {}
    for row in pincodes:
        by_zone.setdefault(row["zone_id"], []).append(_pincode_row(row))
    by_city: dict[int, list[dict]] = {}
    for row in zones:
        by_city.setdefault(row["city_id"], []).append(
            {
                "id": row["id"],
                "name": row["name"],
                "active": bool(row["active"]),
                "pincodes": by_zone.get(row["id"], []),
            }
        )
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "aliases": json.loads(row["aliases"]),
            "active": bool(row["active"]),
            "zones": by_city.get(row["id"], []),
        }
        for row in cities
    ]


def find_pincode(pincode: str) -> dict | None:
    """A pincode with its zone and city, and whether we deliver there."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT p.*, z.name AS zone, z.active AS zone_active, "
            "c.name AS city, c.active AS city_active "
            "FROM delivery_pincodes p "
            "JOIN delivery_zones z ON z.id = p.zone_id "
            "JOIN delivery_cities c ON c.id = z.city_id "
            "WHERE p.pincode = ?",
            (pincode,),
        ).fetchone()
    if not row:
        return None
    return _pincode_row(row) | {
        "zone_id": row["zone_id"],
        "zone": row["zone"],
        "city": row["city"],
        "delivers": bool(row["active"] and row["zone_active"] and row["city_active"]),
    }


def get_zone(zone_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM delivery_zones WHERE id = ?", (zone_id,)
        ).fetchone()
    return dict(row) if row else None


def get_city(city_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM delivery_cities WHERE id = ?", (city_id,)
        ).fetchone()
    return dict(row) if row else None


def add_city(name: str, aliases: list[str]) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO delivery_cities (name, aliases, position) "
            "VALUES (?, ?, "
            "(SELECT COALESCE(MAX(position), -1) + 1 FROM delivery_cities))",
            (name, json.dumps(aliases)),
        )


def update_city(city_id: int, name: str, aliases: list[str], active: bool) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE delivery_cities SET name = ?, aliases = ?, active = ? WHERE id = ?",
            (name, json.dumps(aliases), int(active), city_id),
        )


def delete_city(city_id: int) -> None:
    """Delete a city with its zones and their pincodes."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "DELETE FROM delivery_pincodes WHERE zone_id IN "
            "(SELECT id FROM delivery_zones WHERE city_id = ?)",
            (city_id,),
        )
        conn.execute("DELETE FROM delivery_zones WHERE city_id = ?", (city_id,))
        conn.execute("DELETE FROM delivery_cities WHERE id = ?", (city_id,))


def add_zone(city_id: int, name: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO delivery_zones (city_id, name, position) VALUES (?, ?, "
            "(SELECT COALESCE(MAX(position), -1) + 1 "
            "FROM delivery_zones WHERE city_id = ?))",
            (city_id, name, city_id),
        )


def update_zone(zone_id: int, name: str, active: bool) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE delivery_zones SET name = ?, active = ? WHERE id = ?",
            (name, int(active), zone_id),
        )


def delete_zone(zone_id: int) -> None:
    """Delete a zone with its pincodes."""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM delivery_pincodes WHERE zone_id = ?", (zone_id,))
        conn.execute("DELETE FROM delivery_zones WHERE id = ?", (zone_id,))


def save_pincode(
    old: str | None, pincode: str, zone_id: int, areas: list[str], active: bool
) -> None:
    """Add a pincode (old is None) or change one, including its number."""
    with closing(_connect()) as conn, conn:
        if old is not None:
            conn.execute("DELETE FROM delivery_pincodes WHERE pincode = ?", (old,))
        conn.execute(
            "INSERT INTO delivery_pincodes (pincode, zone_id, areas, active) "
            "VALUES (?, ?, ?, ?)",
            (pincode, zone_id, json.dumps(areas), int(active)),
        )


def delete_pincode(pincode: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM delivery_pincodes WHERE pincode = ?", (pincode,))


def replace_delivery(cities: list[dict]) -> None:
    """Replace every delivery area with cities in the format of list_delivery
    (without ids). Used to seed and to reset."""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM delivery_pincodes")
        conn.execute("DELETE FROM delivery_zones")
        conn.execute("DELETE FROM delivery_cities")
        for city_pos, city in enumerate(cities):
            city_id = conn.execute(
                "INSERT INTO delivery_cities (name, aliases, active, position) "
                "VALUES (?, ?, ?, ?)",
                (
                    city["name"],
                    json.dumps(city.get("aliases", [])),
                    int(city.get("active", True)),
                    city_pos,
                ),
            ).lastrowid
            for zone_pos, zone in enumerate(city["zones"]):
                zone_id = conn.execute(
                    "INSERT INTO delivery_zones (city_id, name, active, position) "
                    "VALUES (?, ?, ?, ?)",
                    (city_id, zone["name"], int(zone.get("active", True)), zone_pos),
                ).lastrowid
                conn.executemany(
                    "INSERT OR REPLACE INTO delivery_pincodes "
                    "(pincode, zone_id, areas, active) VALUES (?, ?, ?, ?)",
                    [
                        (
                            p["pincode"],
                            zone_id,
                            json.dumps(p.get("areas", [])),
                            int(p.get("active", True)),
                        )
                        for p in zone["pincodes"]
                    ],
                )


# Desk users, roles and login sessions. auth.py hashes the passwords and the
# session tokens; only the hashes are stored.


def _role_row(row: sqlite3.Row) -> dict:
    role = dict(row)
    role["permissions"] = json.loads(role["permissions"])
    role["builtin"] = bool(role["builtin"])
    return role


def list_roles() -> list[dict]:
    """Every role, with the number of users that have it."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT roles.*, COUNT(users.id) AS user_count FROM roles "
            "LEFT JOIN users ON users.role_id = roles.id "
            "GROUP BY roles.id ORDER BY roles.builtin DESC, roles.name"
        ).fetchall()
    return [_role_row(row) for row in rows]


def get_role(role_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
    return _role_row(row) if row else None


def find_role(name: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM roles WHERE name = ?", (name,)).fetchone()
    return _role_row(row) if row else None


def add_role(name: str, permissions: list[str], builtin: bool = False) -> int:
    with closing(_connect()) as conn, conn:
        return conn.execute(
            "INSERT INTO roles (name, permissions, builtin, created_at) "
            "VALUES (?, ?, ?, ?)",
            (name, json.dumps(permissions), int(builtin), time.time()),
        ).lastrowid


def update_role(role_id: int, name: str, permissions: list[str]) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE roles SET name = ?, permissions = ? WHERE id = ?",
            (name, json.dumps(permissions), role_id),
        )


def delete_role(role_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))


_USER_COLUMNS = (
    "users.id, users.username, users.name, users.role_id, users.active, "
    "users.created_at, users.last_login_at, roles.name AS role_name, "
    "roles.permissions"
)


def _user_row(row: sqlite3.Row) -> dict:
    user = dict(row)
    user["active"] = bool(user["active"])
    user["permissions"] = json.loads(user["permissions"])
    return user


def count_users() -> int:
    with closing(_connect()) as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def list_users() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT {_USER_COLUMNS} FROM users "
            "JOIN roles ON roles.id = users.role_id ORDER BY users.name"
        ).fetchall()
    return [_user_row(row) for row in rows]


def get_user(user_id: int) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {_USER_COLUMNS} FROM users "
            "JOIN roles ON roles.id = users.role_id WHERE users.id = ?",
            (user_id,),
        ).fetchone()
    return _user_row(row) if row else None


def find_user_login(username: str) -> tuple[int, str, bool] | None:
    """(id, password hash, active) for the username, to check a login."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, password_hash, active FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return (row["id"], row["password_hash"], bool(row["active"])) if row else None


def get_password_hash(user_id: int) -> str | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return row["password_hash"] if row else None


def add_user(username: str, name: str, password_hash: str, role_id: int) -> int:
    with closing(_connect()) as conn, conn:
        return conn.execute(
            "INSERT INTO users (username, name, password_hash, role_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, name, password_hash, role_id, time.time()),
        ).lastrowid


def update_user(
    user_id: int, username: str, name: str, role_id: int, active: bool
) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET username = ?, name = ?, role_id = ?, active = ? "
            "WHERE id = ?",
            (username, name, role_id, int(active), user_id),
        )
        if not active:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def set_password_hash(user_id: int, password_hash: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
        )


def delete_user(user_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def add_session(token_hash: str, user_id: int, expires_at: float) -> None:
    now = time.time()
    with closing(_connect()) as conn, conn:
        # Expired sessions are cleared on each login
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now, expires_at),
        )
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user_id))


def session_user(token_hash: str) -> dict | None:
    """The active user of an unexpired session, or None."""
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {_USER_COLUMNS} FROM sessions "
            "JOIN users ON users.id = sessions.user_id "
            "JOIN roles ON roles.id = users.role_id "
            "WHERE sessions.token_hash = ? AND sessions.expires_at > ? "
            "AND users.active = 1",
            (token_hash, time.time()),
        ).fetchone()
    return _user_row(row) if row else None


def delete_session(token_hash: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_user_sessions(user_id: int, keep: str | None = None) -> None:
    """Log the user out everywhere, except the session `keep` (a token hash)."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
            (user_id, keep or ""),
        )
