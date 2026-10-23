# Ustad Hotel Voice Agent 🍛

A voice agent that takes food orders for Ustad Hotel. The customer talks in the browser. The agent answers menu questions, takes the name, address, items and payment method, and confirms the order with an OTP.

Shop staff use the **desk** to read every call transcript, see customers and their orders, edit what the agent knows, set the order steps, and choose the voice model.

## Pipelines

The Python backend has three pipelines. Choose the default with `PIPELINE` in `.env`, or switch on the desk.

| Pipeline | How it works | Notes |
|----------|-------------|-------|
| `realtime` (default) | Google Gemini Live hears the audio and speaks the reply | Fastest. The customer can interrupt the agent. |
| `ollama` | AssemblyAI STT → local model in Ollama → Cartesia TTS | The language model runs on this machine. Replies take 1–5 seconds. |
| `sandwich` | AssemblyAI STT → Claude Haiku (LangChain agent) → Cartesia TTS | The original pipeline of this demo. |

All three pipelines use the same order tools and the same knowledge base (Chroma RAG over the knowledge modules edited on the desk). They send the same events to the browser.

The TypeScript backend in `components/typescript` has only the `sandwich` pipeline and no RAG.

## Prerequisites

- Python 3.11+ with `uv`, and Node.js 18+ with `pnpm`
- For the `ollama` pipeline: [Ollama](https://ollama.com) running locally, with the model pulled (`ollama pull qwen3.5:4b`)

### API keys

Copy `.env.example` to `.env` and fill in the keys for the pipelines you use.

| Service | Variable | Needed by |
|---------|----------|-----------|
| Google | Desk: **Settings → Gemini** (or `GOOGLE_API_KEY`) | `realtime` |
| AssemblyAI | `ASSEMBLYAI_API_KEY` | `ollama`, `sandwich` |
| Cartesia | `CARTESIA_API_KEY` | `ollama`, `sandwich` |
| Anthropic | `ANTHROPIC_API_KEY` | `sandwich` |

## Quick start

Run these from the repository root.

```bash
make bootstrap   # install all dependencies
make dev-py      # start the Python server with reload
```

Open these pages:

- Order page: `http://localhost:8000`
- Desk: `http://localhost:8000/desk/`
- Log in: `http://localhost:8000/login/`
- Log out: `http://localhost:8000/logout/`

Every page needs a login, also the order page and the voice agent. The first start creates the user `admin` with the password `1234`. Log in, then change the password in **Account**.

## Desk

- **Conversations:** every call, newest first, with its outcome (Live, Ordered, Cancelled or No order). Select a call to read the transcript and the tools the agent used. Search by name, phone number or words.
- **Customers:** add a customer, and see each customer's orders and calls.
- **Training:** the knowledge modules: Menu, FAQ, Allergens and any module you add. Edit sections, and test a question to see what the agent finds. Every voice model uses a change from the next question, with no restart.
- **Flow:** the steps the agent asks for, in order. Move a step, change what the agent asks, or add a custom step such as "Spice level" with choices.
- **Users:** add, edit, deactivate and delete desk users, and reset their passwords. Make roles and choose the permissions of each role. The built-in roles are Admin (every permission, can't be changed), Manager (everything except users) and Staff (view only, plus adding customers). Only users with the "Manage users and roles" permission see this section.
- **Account:** your name and role, change your password, and log out. **Log Out** is also in the sidebar and on the order page.
- **Settings:** set the business name, description, city, phone, email, address, icon and logo. The order page, the desk and the login page show the name and logo, and the agent says the name in its greeting and gives the contact details when asked. Add or change the Gemini API key: the server checks it with Google before saving, and only the last four characters are ever shown. The first start copies `GOOGLE_API_KEY` from `.env` here. Also switch the voice model between Gemini and Local. Record your own voice, make accent versions of it, and choose the voice for calls. This needs the local voice service: run `make install-voice` once. `make dev-py` then starts it. See [voice-doc.md](components/voice-doc.md).

Each user sees only the desk sections their role allows, and the server checks the permission on every desk API call (`components/python/src/auth.py`). Customers, orders, transcripts, knowledge modules, the flow, the chosen mode, and the desk users, roles and login sessions are kept in SQLite at `components/python/data/shop.db`.

## Project structure

```
components/
├── web/                     # Svelte client, shared by both backends
│   ├── index.html           # Order page
│   ├── desk/index.html      # Desk page
│   ├── login/index.html     # Login page
│   ├── logout/index.html    # Logout page
│   └── src/lib/desk/        # Desk sections
├── python/
│   ├── knowledge/           # Seed files for the knowledge modules (first start only)
│   └── src/
│       ├── main.py              # Server, /ws endpoint, /api routes, pipeline selection
│       ├── gemini_live.py       # realtime pipeline
│       ├── ollama_harness.py    # ollama pipeline agent
│       ├── orders.py            # Order state and order tools
│       ├── flow.py              # Ordering flow: steps, checks, prompt text
│       ├── knowledge_base.py    # Chroma ingest and search
│       ├── store.py             # SQLite store
│       ├── conversation_log.py  # Saves call transcripts
│       ├── assemblyai_stt.py    # STT client
│       └── cartesia_tts.py      # TTS client
├── voice/                   # Local voice service: cloned voices and accents (OmniVoice, Pocket TTS)
└── typescript/              # Node.js backend (sandwich pipeline only)
```

## Documentation

| Document | Contents |
|----------|----------|
| [functional-doc.md](components/functional-doc.md) | What the agent and the desk do, for staff and customers |
| [architecture.md](components/architecture.md) | Parts of the system, pipelines, state and events |
| [technical-doc.md](components/technical-doc.md) | Code, configuration, API and known limits |
| [rag_doc.md](components/rag_doc.md) | The knowledge base and retrieval |
| [training-doc.md](components/training-doc.md) | The desk Training and Flow sections: summary, simple explanation, architecture and technical details |
| [voice-doc.md](components/voice-doc.md) | Your own voice and its accents: how to record, the voice service, architecture and technical details |
