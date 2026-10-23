# Technical documentation

This document describes the Python backend code, its configuration and how to run it. For the system view, see [architecture.md](architecture.md). For RAG, see [rag_doc.md](rag_doc.md).

## Stack

| Layer | Technology |
|-------|-----------|
| Server | Python 3.11+, FastAPI, uvicorn, managed with `uv` |
| Realtime voice | Google Gemini Live (`google-genai`), model `gemini-3.8-live`, voice `Kore`, language `en-IN` |
| Sandwich STT | AssemblyAI streaming v3 over WebSocket |
| Sandwich agent | LangChain `create_agent` with LangGraph `InMemorySaver` |
| Sandwich LLM | `anthropic:claude-haiku-4-5` or Ollama (`langchain-ollama`) |
| Sandwich TTS | Cartesia `sonic-3` over WebSocket |
| Ollama agent | `ollama` Python client, local model `qwen3.5:4b` by default |
| Knowledge base | Chroma (`chromadb`), persistent, default embedding model |
| Web client | Svelte, Vite, Tailwind, built to `components/web/dist` |

## Source files

All paths are in `components/python/src/`.

| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI app, `/ws` endpoint, system prompt (`build_shop_prompt`), tool list, pipeline selection, sandwich stages, desk API |
| `flow.py` | The ordering flow: default steps, checks, prompt text |
| `gemini_live.py` | `GeminiLiveAgent` (realtime pipeline) and `IdleWatch` (greeting and idle check-in) |
| `orders.py` | `Order` dataclass, per-session `ContextVar`, order tools, `order_stage` |
| `store.py` | SQLite store: settings, customers, orders, conversations, messages, knowledge modules and the flow |
| `conversation_log.py` | `ConversationLog`: saves each call's transcript for the desk |
| `knowledge_base.py` | Module seeding, Chroma ingest, re-index and search, menu overview |
| `ollama_harness.py` | `OllamaHarness` (ollama pipeline agent), `warm_up` |
| `events.py` | Event dataclasses and `event_to_dict` |
| `assemblyai_stt.py` | AssemblyAI WebSocket client |
| `cartesia_tts.py` | Cartesia WebSocket client |
| `local_tts.py` | `LocalTTS`: speech in a desk voice, through the local voice service |
| `voices.py` | Desk voices: recordings, accent versions, the voice in use. See [voice-doc.md](voice-doc.md). |
| `elevenlabs_tts.py` | ElevenLabs WebSocket client (not used by `main.py`) |
| `cartesia_prompts.py` | Prompt rules for text that a TTS engine speaks |
| `utils.py` | `merge_async_iters` |

## Configuration

The server reads `.env` with `python-dotenv`. See `.env.example`.

| Variable | Default | Used by | Purpose |
|----------|---------|---------|---------|
| `PIPELINE` | `realtime` | `main.py` | Default mode: `realtime`, `sandwich` or `ollama`. Any other value stops the server. A mode saved on the desk overrides it. |
| `SHOP_DB_PATH` | `components/python/data/shop.db` | `store.py` | SQLite file for settings, customers, orders and transcripts |
| `GOOGLE_API_KEY` | none | realtime | Gemini Live access |
| `ASSEMBLYAI_API_KEY` | none | sandwich | STT |
| `CARTESIA_API_KEY` | none | sandwich | TTS |
| `CARTESIA_VOICE_ID` | Cartesia default | sandwich, ollama | Cartesia voice when no desk voice is in use |
| `LOCAL_VOICE_URL` | `http://127.0.0.1:8001` | sandwich, ollama | Local voice service for desk voices |
| `LOCAL_VOICE_PORT` | `8001` | voice service | Port of the local voice service |
| `LOCAL_ACCENT_MODEL` | `mlx-community/OmniVoice-bf16` | voice service | Model for accent versions |
| `ANTHROPIC_API_KEY` | none | sandwich | Claude, when `LLM_PROVIDER=anthropic` |
| `LLM_PROVIDER` | `anthropic` | sandwich | `anthropic` or `ollama` |
| `OLLAMA_MODEL` | `qwen3.5:4b` | sandwich, ollama | Local model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | sandwich, ollama | Ollama server |
| `ASSEMBLYAI_END_OF_TURN_CONFIDENCE` | `0.4` | sandwich, ollama | Confidence needed to end a turn early |
| `ASSEMBLYAI_MIN_TURN_SILENCE_MS` | `300` | sandwich, ollama | Silence that ends a turn when confident |
| `ASSEMBLYAI_MAX_TURN_SILENCE_MS` | `1000` | sandwich, ollama | Silence that always ends a turn |
| `GEMINI_VAD_SILENCE_MS` | `700` | realtime | Silence before Gemini ends the user turn |
| `GEMINI_VAD_PREFIX_PADDING_MS` | `200` | realtime | Audio kept before detected speech |
| `GEMINI_IDLE_SECONDS` | `8` | realtime | Silence before the agent asks "Hello, are you there?" |

## Server start sequence

1. Load `.env`.
2. Call `seed_modules()`: on the first start, copy `knowledge/*.md` into modules. Then call `ingest()` and print the chunk count.
3. Make sure `components/web/dist` exists. If it does not, raise `RuntimeError`.
4. Create the FastAPI app with open CORS.
5. Build the tool list: `TOOLS = [*ORDER_TOOLS, search_knowledge]`.
6. Get the mode with `current_pipeline()`: the mode saved on the desk, or else `PIPELINE`. For `ollama`, call `warm_up()` to load the model and fill its prompt cache. The Gemini and LangChain agents are built on first use and cached by prompt (`realtime_agent(prompt, greeting)`, `sandwich_agent(prompt)`).
7. Close conversations left open by the last stop (`store.end_open_conversations()`).
8. Register the desk API under `/api`.
8. Mount the web build at `/`.

## WebSocket session

`websocket_endpoint` in `main.py` does these steps for each connection:

1. Accept the connection.
2. Read the mode with `current_pipeline()`. A mode change on the desk applies to the next connection, not to open ones.
3. Call `start_order(channel=mode)` to give the session a new `Order`.
4. Wrap incoming binary frames in an async generator of audio bytes.
5. Pass the generator to the selected pipeline.
6. Send each event to the client with `websocket.send_json(event_to_dict(event))`.

The client sends 16-bit PCM, mono, 16 kHz. The server sends `tts_chunk` audio as 16-bit PCM, mono, 24 kHz, in base64.

## Realtime pipeline: `GeminiLiveAgent`

### Session configuration

- Response modality: audio.
- Input and output transcription on, language `en-IN`.
- Automatic voice activity detection with LOW start and end sensitivity. LOW sensitivity stops the agent from replying during short pauses in a barge-in.
- Tools: each function becomes a declaration through `FunctionDeclaration.from_callable_with_api_option`.

### Stream loop

`stream()` opens a Gemini Live session and starts two background tasks:

- `send_audio` forwards microphone audio. When the client stream ends, it closes the session.
- `watch_idle` checks every 0.5 s. If `IdleWatch.should_nudge()` is true, it sends `IDLE_PROMPT` as text.

Before the tasks start, the agent sends `GREETING_PROMPT` with the flow's greeting, so it speaks first.

### Message mapping

`_receive_events` translates Gemini server messages:

| Gemini message | Events |
|----------------|--------|
| `input_transcription` | `stt_chunk` (accumulated text) |
| First model output in a turn | `stt_output` (final user text) |
| `output_transcription` | `agent_chunk` |
| `model_turn` audio | `tts_chunk` |
| `tool_call` | `tool_call`, then `tool_result` for each call |
| `tool_call_cancellation` | Cancelled call IDs are skipped |
| `interrupted` | `interrupted`, then `agent_end` |
| `turn_complete` | `agent_end` |

### Tool execution

`_run_tools` runs each tool with `asyncio.to_thread`. A tool error becomes the result text `Error running <name>: <error>`. An unknown tool name becomes `Unknown tool: <name>`. All results go back to Gemini in one `send_tool_response`.

### Idle check-in

`IdleWatch` tracks:

- the time of the last user speech,
- the estimated end of agent playback (audio length divided by 48,000 bytes per second),
- whether the agent owes a reply.

The agent checks in once per silence. User speech resets the check.

## Sandwich pipeline

`pipeline = RunnableGenerator(_stt_stream) | RunnableGenerator(_agent_stream) | RunnableGenerator(_tts_stream)`

- `_stt_stream`: a producer task sends audio to AssemblyAI. The consumer yields transcript events.
- `_agent_stream`: on `stt_output`, calls `agent.astream(..., stream_mode="messages")` with a thread ID for the connection. It maps `AIMessage` to `agent_chunk` and `tool_call`, and `ToolMessage` to `tool_result`.
- `_stt_stream`: AssemblyAI runs with `format_turns=false`. The final transcript is sent on `end_of_turn`, without the wait for punctuation.
- `_tts_stream`: connects to Cartesia when the session starts. It sends text at each sentence end, or at a clause end after 30 characters. All parts of a reply use one Cartesia context with `continue: true`, and `agent_end` closes the context. It merges upstream events and audio with `merge_async_iters`.

The system prompt is `build_shop_prompt(order.flow) + CARTESIA_TTS_SYSTEM_PROMPT`. `build_shop_prompt` fills the greeting, the numbered flow steps and the dish names of the Menu modules.

The Ollama model uses `reasoning=False`, `keep_alive=-1` and `num_ctx=4096` to keep the first word fast.

## Ollama pipeline: `OllamaHarness`

`websocket_endpoint` builds `_tts_stream(_ollama_agent_stream(_stt_stream(audio)))`. `_ollama_agent_stream` creates one `OllamaHarness` per connection, emits the flow's greeting, and calls `harness.respond(transcript)` on each `stt_output`.

### One turn

1. Add the user message to history.
2. If the transcript looks like a question, run `search(query, k=2)`. A follow-up with "it", "that" and similar words also uses the previous user message in the query.
3. **First request.** Send persona, history and a note on the last message: step instruction, order snapshot and shop info. Stream the text out as `agent_chunk`.
4. If the model called tools, check and run each one, then send a **second request** with a "reply now, do not call tools" note. Tool calls in the second request are ignored.
5. If the model said nothing, speak the fallback line. Emit `agent_end`.

### Tool checks

| Check | Result on failure |
|-------|-------------------|
| The tool belongs to the current step | `Error: ... cannot be used at this step` |
| Arguments bind to the signature. `int` and `str` are coerced. | `Error: bad arguments ...` |
| `save_phone_number`, `verify_otp`: the transcript has 4 or more spoken digits | `Error: the customer did not say the number ...` |
| `save_delivery_address`: if the user named Bangalore but the arguments do not, the city is set from the user's words | Repaired, no error |

The error text goes back to the model as the tool result.

### Request settings

`think=False`, `keep_alive=-1` (the model stays loaded), `num_ctx=8192`, `num_predict=120`, `temperature=0.3`. Text after a `<` is dropped, so markup such as `</think>` is never spoken.

### Prompt cache

The tool list and persona never change, and the note stays in history, so each request extends the previous one. History is cut from 20 to 8 messages in one step, so the cache misses only once per cut. The warm-up sends the persona and greeting, so the first turn also finds them in the cache.

### Measured latency (Apple M4, 16 GB, `qwen3.5:4b`)

| Turn type | Model time to first text |
|-----------|--------------------------|
| Question, no tool | about 0.3–2.5 s |
| Tool call (two requests) | about 3.5–4.5 s |

Add about 0.5–1.2 s for AssemblyAI end of turn and about 0.2 s for Cartesia. `qwen3.5:2b` is about two times faster on tool turns, but it answered 9 of 15 menu and allergen questions wrong in tests. Each turn logs `Turn latency: first text … ms, first audio … ms`.

## Order tools

`orders.py` keeps one `Order` per connection in `current_order: ContextVar[Order]`. Tools are plain functions that read this variable. `asyncio.to_thread` and LangChain copy the context into worker threads, so each tool sees the order of its own session.

| Tool | Checks | Effect |
|------|--------|--------|
| `save_customer_name(name)` | none | Sets `name` |
| `save_delivery_address(address, city)` | Order not confirmed. Text contains `bangalore`, `bengaluru` or `blr`. | Sets `address`, `address_verified` |
| `add_to_order(item, quantity)` | Not confirmed. Required flow steps before `items` done. | Appends to `items` |
| `set_payment_method(method)` | Not confirmed. Method is UPI or card. | Sets `payment_method` |
| `save_order_detail(step, value)` | Not confirmed. `step` is a custom step of the flow. The value matches a choice, if the step has choices. "No thanks" skips an optional step. | Sets `details[step]` |
| `save_phone_number(phone_number)` | Not confirmed. 10 digits (`+91` removed). | Sets `phone`. A new number clears an OTP already sent. |
| `send_otp()` | Not confirmed. All required flow steps done, including the phone number. | Makes a 4-digit `otp` for the saved phone, prints it to the log |
| `verify_otp(otp)` | Not confirmed. OTP sent. Max 3 wrong tries. | Sets `confirmed`, prints the summary |
| `cancel_order()` | Not confirmed | Clears items, payment and OTP. Keeps the name, address and phone. |

Each tool returns an instruction for the model when a check fails. The prompt tells the model to follow tool results.

`start_order` gives each session an `Order` with the flow saved on the desk (`flow.load_flow()`). `order_stage(order)` returns the first step that is not done. See [training-doc.md](training-doc.md) for the flow rules.

There is no SMS provider. The OTP is printed to the server log.

## Desk API and store

`store.py` keeps settings, customers, orders, conversations, knowledge modules and the flow in SQLite (`SHOP_DB_PATH`). Each call opens its own connection, because order tools run in worker threads.

| Table | Key | Content |
|-------|-----|---------|
| `settings` | `key` | `pipeline`: the mode chosen on the desk |
| `customers` | `phone` (10 digits) | Name, created and updated times |
| `orders` | `id` | Phone, address, items (JSON), payment method, status (`confirmed` or `cancelled`), mode, time, answers to custom steps (`details`, JSON) |
| `conversations` | `id` | Mode, customer name and phone, outcome (`confirmed`, `cancelled` or empty), start and end times. `ended_at` is empty while the call is live. |
| `messages` | `id` | Conversation, role (`customer`, `agent` or `tool`), text, and for a tool its name and arguments (JSON) |
| `modules` | `id` | Name, type (`menu`, `notes` or `qa`), intro, position |
| `sections` | `id` | Module, title, body, position. Each section is one knowledge chunk. |
| `flow_steps` | `key` | Type (`builtin` or `custom`), name, question, extra instructions, required, choices (JSON), position. Empty means the default flow. |

The order tools write to it:

- `send_otp` saves the customer with `save_customer(phone, name)`. A known phone gets the new name.
- `verify_otp` saves the order as `confirmed`.
- `cancel_order` saves the order as `cancelled`, if the phone is known and the order has items.

`conversation_log.py` saves the transcripts. The WebSocket handler gives every event it sends to the browser to a `ConversationLog`, so all three modes are recorded the same way:

- `stt_output` is saved as a `customer` message.
- `agent_chunk` text collects until `agent_end`, a `tool_call` or the next `stt_output`. Then it is saved as one `agent` message.
- `tool_result` is saved as a `tool` message with the arguments from its `tool_call`.
- After each `agent_end`, the customer name, phone and outcome are copied from the order.
- When the connection closes, `finish()` sets `ended_at`. A conversation with no customer message is deleted.

A failed write is logged and does not stop the call.

| Route | Action |
|-------|--------|
| `GET /api/settings` | Current mode, local model name, and whether a Gemini key is set |
| `PUT /api/settings` | Body `{"pipeline": "realtime"\|"ollama"\|"sandwich"}`. For `ollama` it loads the model first and returns 503 if Ollama is not running. For `realtime` it returns 400 without a Gemini key. |
| `GET /api/customers` | All customers with their orders, most recently active first |
| `POST /api/customers` | Body `{"name", "phone"}`. Creates or renames a customer. Returns 400 for an empty name or a phone that is not 10 digits (`+91` is accepted). |
| `GET /api/conversations` | The latest 200 conversations, newest first, with message count and the first customer message |
| `GET /api/conversations/{id}` | One conversation with all its messages. Returns 404 for an unknown ID. |
| `GET`, `POST /api/modules` | List modules with their sections, or create a module (`{"name", "kind", "intro"}`) |
| `PUT`, `DELETE /api/modules/{id}` | Change or delete a module. The module is re-indexed or removed from Chroma. |
| `POST /api/modules/reorder` | Body `{"ids"}`. Sets the module order. |
| `POST /api/modules/{id}/sections` | Body `{"title", "body"}`. Adds a section. |
| `POST /api/modules/{id}/sections/reorder` | Body `{"ids"}`. Sets the section order. |
| `PUT`, `DELETE /api/sections/{id}` | Change or delete a section |
| `POST /api/knowledge/test` | Body `{"question"}`. Returns the top 3 knowledge matches with module and distance. |
| `GET`, `PUT /api/flow` | Read the flow with its greeting and prompt text, or save a flow (`{"steps"}`). Returns 400 with the reason for an invalid flow. |
| `POST /api/flow/reset` | Restores the default flow |

[training-doc.md](training-doc.md) has the bodies, limits and errors.

The API has no login.

## Knowledge base

See [rag_doc.md](rag_doc.md). In short: `ingest()` runs on start, `search(query, k=3)` returns the top 3 chunks, and `search_knowledge` exposes it as a tool.

The index holds the sections of the modules in the store. The first start copies `knowledge/*.md` into modules. After that, a desk change re-indexes its module with `reindex_module`, with no restart. See [training-doc.md](training-doc.md).

## Web client changes

- `types.ts` adds the `interrupted` event type.
- `websocket.ts` handles `interrupted`: it stops audio playback, clears the TTS finish timer and closes the current turn.
- The title and header show "Ustad Hotel" with the 🍛 icon.
- The web client has two pages, both built by Vite (`build.rollupOptions.input` in `vite.config.ts`):
  - `index.html` → `src/main.ts` → `App.svelte`: the order page at `/`. The header shows the current mode and links to the desk. The old `#/admin` URL redirects to `/desk/`.
  - `desk/index.html` → `src/desk.ts` → `lib/desk/Desk.svelte`: the desk at `/desk/`. Hash routes pick the section: `#conversations`, `#conversations/<id>`, `#conversations?q=<search>`, `#customers`, `#training`, `#training/<module id>`, `#flow` and `#settings`. Settings also holds the Voices part (`VoicesSection.svelte`). Each section is its own component in `lib/desk/`.
- `api.ts` calls the desk API. In dev, Vite proxies `/api` to port 8000.
- `app.css` defines color tokens for light and dark mode, following the system setting. The Tailwind gray scale and `white` map to these tokens, so existing components adapt. `.palette-light` keeps the original grays inside the dark pipeline card. The accent color (saffron) marks primary actions and the selected mode only.

## Commands

Run these from the repository root.

| Command | Action |
|---------|--------|
| `make bootstrap` | Install web, TypeScript and Python dependencies |
| `make dev-py` | Build the web client in watch mode and start the Python server with reload. Also starts the local voice service, if it is installed and not running. |
| `make start-py` | Build the web client once and start the Python server |
| `make install-voice` | Install the local voice service (Apple silicon) |
| `make dev-voice` | Start the local voice service on port 8001 |
| `make check` | Type-check the web client and the TypeScript backend |
| `make clean` | Delete builds, `node_modules`, `.venv` and `.chroma` |

The app runs at `http://localhost:8000`.

## Known limits

- Orders in progress and the model's conversation history are in memory. A restart loses them. Customers, finished orders and transcripts are kept in SQLite.
- Transcripts are kept forever. There is no delete or retention limit.
- Knowledge sections are not checked against each other. Two sections that disagree are not flagged.
- After the first start, edits to `knowledge/*.md` have no effect. The modules in the store are the source.
- The flow and modules have no edit history or undo.
- The desk and `/api` have no login. Anyone who can reach the server can read customer phone numbers and transcripts, change the mode, and change what the agent knows and asks.
- There is no kitchen or payment integration.
- The delivery check is a text match on the city name.
- CORS allows all origins.
- There are no automated tests for the Python backend.
- The `ollama` and `sandwich` pipelines have no barge-in and no idle check-in.
- If Cartesia rejects the connection (for example, out of credits), the session ends with an error.
