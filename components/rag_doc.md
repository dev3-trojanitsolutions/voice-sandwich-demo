# RAG in the voice agent: what is built

This document describes the retrieval-augmented generation (RAG) that the Python backend uses now. RAG lets the agent answer questions about the menu, prices, allergens and shop policies from documents, instead of from the system prompt.

For the full system, see [architecture.md](architecture.md), [technical-doc.md](technical-doc.md) and [functional-doc.md](functional-doc.md).

## How it works

The agent has one tool for RAG: `search_knowledge(query)`. The model decides when to call it. The tool searches a local Chroma vector database and returns the three best-matching text chunks. The model then speaks an answer from those chunks.

```
User speaks → agent (Gemini Live or Claude) → search_knowledge("is chicken 65 gluten free")
           → Chroma returns the top 3 chunks → agent speaks the answer from them
```

The same tool works in both pipelines (`realtime` and `sandwich`). The web client needs no change, because the tool call and its result already show as `tool_call` and `tool_result` events in the activity panel.

## What was added

| Item | Location | Purpose |
|------|----------|---------|
| `chromadb` dependency | `components/python/pyproject.toml` | Local vector database with a built-in embedding model. It needs no API key. |
| Knowledge documents | `components/python/knowledge/` | Seed text. The first start copies it into modules in SQLite. |
| Knowledge modules | `modules` and `sections` tables in `store.py` | The text the agent searches. Staff edit it in the desk Training section. |
| Knowledge base module | `components/python/src/knowledge_base.py` | Splits the documents into chunks, stores them, and searches them. |
| Ingest on start | `components/python/src/main.py` | Rebuilds the database each time the server starts. |
| `search_knowledge` tool | `components/python/src/main.py` | Exposes search to the agent. |
| Prompt rule | `SHOP_PROMPT` in `main.py` | Tells the agent to search before it answers fact questions. |
| Threaded tool calls | `_run_tools` in `gemini_live.py` | Runs tools in a worker thread so a search does not block audio. |
| `.chroma/` ignore | `.gitignore` | Keeps the generated database out of git. |
| `make clean` | `Makefile` | Deletes `components/python/.chroma`. |

## Knowledge documents

There are three Markdown files in `components/python/knowledge/`. On the first start, `seed_modules()` copies each file into one module: the `# ` title is the module name, the text before the first `## ` is the intro, and each `## ` heading is a section. After that, the desk is the source and the files are not read again.

- `menu.md`: dishes, descriptions and prices in rupees (Biriyani, Mandi, Starters, Curries, Breads, Sandwiches, Cheeses, Toppings).
- `allergens.md`: gluten, dairy, eggs, nuts and soy, per dish.
- `faq.md`: opening hours, delivery area and cost, payment and OTP rules, refunds.

Each section becomes one chunk, and a module intro becomes one more chunk. Keep each section short and about one topic.

## Knowledge base module

`components/python/src/knowledge_base.py` has these main functions.

**`ingest() -> int`**

1. Deletes the `shop_knowledge` collection and creates it again. This removes sections that were edited or deleted.
2. Reads every module and its sections from the store.
3. Adds one chunk per section with the ID `section-<id>`, and one per intro with the ID `module-<id>`. The metadata is `{"source": "<module name>", "module_id": <id>}`.
4. Returns the number of chunks.

**`reindex_module(module_id)`** replaces the chunks of one module after a desk change. **`remove_module(module_id)`** deletes them.

**`search_results(query, k=3) -> list`** returns each match with its ID, module name, module ID, text and distance. The desk test box uses it.

**`search(query, k=3) -> str`**

1. If the collection is empty, returns `"No knowledge base documents found."`.
2. Queries Chroma for the `k` chunks nearest to the query.
3. Joins the chunks with `\n\n---\n\n` and returns one string.
4. If there is no result, returns `"No relevant information found."`.

The database is stored on disk in `components/python/.chroma/`. The client and the collection are module-level objects, so all WebSocket sessions share one database.

## Ingest on server start

`main.py` calls `ingest()` once at import time and prints the result:

```
Knowledge base: 20 chunks
```

Before that, `seed_modules()` creates the modules from the files on the first start. A desk change does not need a restart: the API route re-indexes the module at once.

## The tool

```python
def search_knowledge(query: str) -> str:
    """Search the shop's menu, prices, allergen info and FAQ (hours, delivery,
    payment, refunds). Use this before answering any question about these."""
    return search(query)


TOOLS = [*ORDER_TOOLS, search_knowledge]
```

Both pipelines get the same `TOOLS` list:

- **Realtime:** `GeminiLiveAgent` turns the function name, docstring and type hints into a Gemini function declaration.
- **Sandwich:** LangChain `create_agent` turns the function into a tool for Claude or Ollama.

The model reads the docstring to decide when to call the tool. Change the docstring with care.

In the `ollama` pipeline, `OllamaHarness` also searches before the model runs. If the transcript looks like a question, it calls `search(query, k=2)` and adds the chunks to the request. The small model then answers without a `search_knowledge` round trip. See [technical-doc.md](technical-doc.md).

## Prompt rule

`SHOP_PROMPT` contains this rule:

> For any question about prices, ingredients, allergens, hours, delivery, payment or refunds, call search_knowledge first and answer only from its result. If it does not contain the answer, say you don't know.

This rule stops the agent from inventing prices or allergen facts. The prompt still lists the dish names from the Menu modules (`menu_overview()`), so the agent can describe the menu without a search. The specials are in the Order items step of the flow.

## Non-blocking tool calls

In the realtime pipeline, tools run inside the async loop that receives Gemini audio. An embedding plus a Chroma query takes about 10 to 100 ms. To keep audio smooth, `_run_tools` runs each tool in a worker thread:

```python
result = await asyncio.to_thread(tool, **args) if tool else f"Unknown tool: {call.name}"
```

`asyncio.to_thread` copies the context, so the order tools still see the `current_order` of the session.

## How to change the knowledge

1. Open the desk at `http://localhost:8000/desk/#training`.
2. Choose a module, or choose **+ New Module**.
3. Add, edit or delete a section.
4. In **Test a Question**, make sure the search finds the new text.

See [training-doc.md](training-doc.md) for the full description.

To load the files in `knowledge/` again, stop the server and delete `components/python/data/shop.db`. This also deletes customers, orders and transcripts.

## How to test

1. Start the server with `make dev-py`. The log must show `Knowledge base: N chunks` with N greater than 0.
2. Test search without voice. From `components/python/`, run:
   ```bash
   uv run python -c "import sys; sys.path.insert(0,'src'); from knowledge_base import search; print(search('is chicken 65 gluten free'))"
   ```
   The output must contain the `Gluten` chunk from `allergens.md`.
3. Open `http://localhost:8000` and ask "How much is the Mutton Biriyani?". The activity panel must show `search_knowledge` and a result that contains `₹350`.
4. Ask a question that the documents do not answer. The agent must say that it does not know.

## Limits and next steps

- **No similarity threshold.** `search` always returns `k` chunks, even when they do not match well. You can filter on `result["distances"]`.
- **Default embedding model.** Chroma uses its built-in model. If retrieval quality is poor, try `gemini-embedding-001` through the `google-genai` client.
- **Full rebuild on each start.** This is fast for 20 chunks. For a large document set, use `upsert` and rebuild only the changed files.
- **Python only.** The TypeScript backend (`components/typescript`) has no RAG.
- **No source in the answer.** `search_results` returns the source, but `search` gives the agent only the text.
