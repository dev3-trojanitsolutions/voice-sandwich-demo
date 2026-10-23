"""
Knowledge base for retrieval-augmented generation (RAG).

The knowledge lives in modules in the SQLite store: the menu, the FAQ, the
allergens and any module staff add on the desk. Each module has an intro and
sections. Each section becomes one chunk in a local Chroma vector database.

On the first start, the modules are seeded from the Markdown files in
components/python/knowledge/ (one module per file, one section per "## "
heading). After that, the desk is where the knowledge is edited.

The agent queries the database through the search_knowledge tool to answer
questions about the menu, allergens and shop policies.

The server rebuilds the database on every start. A change on the desk
re-indexes the one module it touches, so the next question already finds it.
"""

import difflib
import re
from pathlib import Path

import chromadb
from chromadb.errors import NotFoundError

import store

ROOT = Path(__file__).parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
DB_DIR = ROOT / ".chroma"
COLLECTION_NAME = "shop_knowledge"

# Module kinds. A menu module also feeds the dish list in the agent's prompt.
MODULE_KINDS = ("menu", "notes", "qa")
# Seed order for the files, and the kind each one gets
SEED_FILES = {"menu.md": "menu", "faq.md": "notes", "allergens.md": "notes"}
LEGACY_TRAINING_MODULE = "Questions & Answers"

_client = chromadb.PersistentClient(path=str(DB_DIR))
_collection = _client.get_or_create_collection(COLLECTION_NAME)


def _get_collection():
    """The collection, reopened if another process (e.g. a uvicorn reload) rebuilt it."""
    global _collection
    try:
        _collection.count()
    except NotFoundError:
        _collection = _client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def parse_markdown(text: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Split a knowledge file into its "# " title, the intro text before the
    first "## " heading, and (heading, body) pairs."""
    head, *parts = re.split(r"^## ", text, flags=re.MULTILINE)
    title_match = re.search(r"^# (.+)$", head, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else ""
    intro = re.sub(r"^# .+$", "", head, flags=re.MULTILINE).strip()
    sections = []
    for part in parts:
        heading, _, body = part.partition("\n")
        sections.append((heading.strip(), body.strip()))
    return title, intro, sections


def seed_modules() -> None:
    """On the first start, create modules from the knowledge files, and move
    question and answer pairs from the old training table into a module."""
    if store.get_setting("knowledge_seeded") != "1":
        if not store.list_modules():
            names = sorted(
                KNOWLEDGE_DIR.glob("*.md"),
                key=lambda p: (list(SEED_FILES).index(p.name) if p.name in SEED_FILES else 99, p.name),
            )
            for path in names:
                title, intro, sections = parse_markdown(path.read_text())
                module = store.add_module(
                    title or path.stem.title(), SEED_FILES.get(path.name, "notes"), intro
                )
                for heading, body in sections:
                    store.add_section(module["id"], heading, body)
        store.set_setting("knowledge_seeded", "1")

    legacy = store.pop_legacy_training()
    if legacy:
        module = store.add_module(LEGACY_TRAINING_MODULE, "qa", "")
        for row in legacy:
            store.add_section(module["id"], row["question"], row["answer"])


def _chunks(module: dict) -> tuple[list[str], list[str], list[dict]]:
    """The chunk IDs, texts and metadata for one module."""
    ids, docs, metas = [], [], []
    meta = {"source": module["name"], "module_id": module["id"]}
    if module["intro"]:
        ids.append(f"module-{module['id']}")
        docs.append(f"{module['name']}\n\n{module['intro']}")
        metas.append(meta)
    for section in module["sections"]:
        ids.append(f"section-{section['id']}")
        if module["kind"] == "qa":
            # The question alone matches the customer's words best
            docs.append(f"{section['title']}\n\n{section['body']}")
        else:
            docs.append(f"{module['name']}: {section['title']}\n\n{section['body']}")
        metas.append(meta)
    return ids, docs, metas


def ingest() -> int:
    """Rebuild the collection from all modules. Returns chunk count."""
    global _collection
    # Recreate the collection so edited or deleted sections don't linger
    _client.delete_collection(COLLECTION_NAME)
    _collection = _client.create_collection(COLLECTION_NAME)

    ids, docs, metas = [], [], []
    for module in store.list_modules():
        m_ids, m_docs, m_metas = _chunks(module)
        ids += m_ids
        docs += m_docs
        metas += m_metas

    if ids:
        _collection.add(ids=ids, documents=docs, metadatas=metas)
    return len(ids)


def remove_module(module_id: int) -> None:
    _get_collection().delete(where={"module_id": module_id})


def reindex_module(module_id: int) -> None:
    """Replace the chunks of one module after a change on the desk."""
    remove_module(module_id)
    module = store.get_module(module_id)
    if module:
        ids, docs, metas = _chunks(module)
        if ids:
            _get_collection().add(ids=ids, documents=docs, metadatas=metas)


def search_results(query: str, k: int = 3) -> list[dict]:
    """The k chunks most relevant to the query, each with its source and distance."""
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        return []
    result = collection.query(query_texts=[query], n_results=min(k, count))
    return [
        {
            "id": chunk_id,
            "source": meta["source"],
            "module_id": meta["module_id"],
            "text": doc,
            "distance": round(distance, 3),
        }
        for chunk_id, doc, meta, distance in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        )
    ]


def search(query: str, k: int = 3) -> str:
    """Return the k chunks most relevant to the query, joined into one string."""
    if _get_collection().count() == 0:
        return "No knowledge base documents found."
    documents = [r["text"] for r in search_results(query, k)]
    return "\n\n---\n\n".join(documents) or "No relevant information found."


def _dish_lines(body: str) -> list[tuple[str, str]]:
    """(name, rest of line) for each dish in a menu section body. A dish is a
    line that starts with "Name:"."""
    dishes = []
    for line in body.splitlines():
        name, sep, rest = line.partition(":")
        if sep and len(name) <= 40:
            dishes.append((name.strip(), rest))
    return dishes


def _menu_sections() -> list[dict]:
    return [
        section
        for module in store.list_modules()
        if module["kind"] == "menu"
        for section in module["sections"]
    ]


def menu_overview() -> str:
    """The dish names of every menu module, by section, for the agent's prompt."""
    parts = []
    for section in _menu_sections():
        dishes = [name for name, _ in _dish_lines(section["body"])]
        parts.append(f"{section['title']}: {', '.join(dishes)}" if dishes else section["title"])
    return ". ".join(parts)


def menu_prices() -> dict[str, int]:
    """The price in rupees of every dish in the menu modules, by dish name.
    The price is the last "₹<number>" on the dish line."""
    prices = {}
    for section in _menu_sections():
        for name, rest in _dish_lines(section["body"]):
            if amounts := re.findall(r"₹\s*([\d,]+)", rest):
                prices[name] = int(amounts[-1].replace(",", ""))
    return prices


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def match_menu_items(spoken: str) -> list[tuple[str, int]]:
    """(menu name, price) of the dishes that match what the customer said: one
    for a clear match, several when it is ambiguous ("chicken"), none if it is
    not on the menu. Text in parentheses is an alias: "Mutton Korma (khorma)"
    also matches "khorma"."""
    by_alias: dict[str, str] = {}
    prices = menu_prices()
    for name in prices:
        by_alias[_normalize(re.sub(r"\(.*?\)", "", name))] = name
        for alias in re.findall(r"\((.*?)\)", name):
            by_alias[_normalize(alias)] = name
    wanted = _normalize(spoken)
    if not wanted:
        return []
    if wanted in by_alias:
        names = [by_alias[wanted]]
    else:
        names = [n for a, n in by_alias.items() if a and (a in wanted or wanted in a)]
        if not names:
            close = difflib.get_close_matches(wanted, by_alias, n=1, cutoff=0.75)
            names = [by_alias[a] for a in close]
    return [(name, prices[name]) for name in dict.fromkeys(names)]
