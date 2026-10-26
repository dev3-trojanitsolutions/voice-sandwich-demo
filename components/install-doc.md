# Install, run and stop

This guide installs the voice agent on macOS, Ubuntu or Windows, sets the admin password, connects Gemini and the other services, and starts and stops the server.

## Disk space

Measured on a fresh install. The installer downloads the parts in the first three rows always, and the local LLM unless you skip it.

| Part | Size | When |
|------|------|------|
| Source code | 5 MB | Always |
| Web and TypeScript packages (`node_modules`) | 570 MB | Always |
| Python environment (`components/python/.venv`) | 400 MB | Always |
| Embedding model for the knowledge base (`~/.cache/chroma`) | 170 MB | First server start |
| Local LLM `qwen3.5:4b` (Ollama) | 4 GB | Unless `--no-llm` / `NO_LLM=1` |
| Voice service environment (`components/voice/.venv`) | 1.1 GB | Apple silicon only, unless `--no-voice` |
| Voice models (`~/.cache/huggingface`) | 4 GB | Apple silicon, first start of the voice service |

| Install | Total |
|---------|-------|
| Gemini only (`--no-llm`) | about 1.2 GB |
| With the local LLM (Ubuntu, Windows, Intel Mac) | about 5.2 GB |
| With the local LLM and voice service (Apple silicon Mac) | about 10.3 GB |

Memory: the `qwen3.5:4b` model needs about 8 GB of RAM. On a machine with less RAM, use `qwen3.5:2b` (set `OLLAMA_MODEL=qwen3.5:2b` in `.env`, then `make install-llm`).

## Install with one command

The command downloads the application into the folder `voice-sandwich-demo` in the current folder. It installs the tools that are missing (Git, Node.js, uv, pnpm, Ollama), the packages, the local LLM, and builds the web pages.

### macOS

```bash
curl -fsSL https://raw.githubusercontent.com/dev3-trojanitsolutions/voice-sandwich-demo/main/install.sh | bash
```

You need the Xcode command line tools (`xcode-select --install`). With [Homebrew](https://brew.sh), the script also installs Node.js and Ollama. On Apple silicon, it also installs the local voice service.

### Ubuntu (and Debian)

```bash
curl -fsSL https://raw.githubusercontent.com/dev3-trojanitsolutions/voice-sandwich-demo/main/install.sh | bash
```

The script asks for your `sudo` password to install packages with `apt-get` and Node.js from NodeSource.

### Windows 10 and 11

Open **PowerShell** and run:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/dev3-trojanitsolutions/voice-sandwich-demo/main/install.ps1 | iex"
```

The script installs Git, Node.js and Ollama with `winget`. The local voice service is not available on Windows.

### Options

| Option | macOS / Ubuntu | Windows |
|--------|----------------|---------|
| Skip the local LLM (Ollama, 4 GB) | `... \| bash -s -- --no-llm` | `$env:NO_LLM=1` before the command |
| Skip the voice service | `... \| bash -s -- --no-voice` | (never installed) |
| Install into another folder | `INSTALL_DIR=~/apps/agent` before `bash` | `$env:INSTALL_DIR="C:\apps\agent"` |

Run the same command again to update an existing install.

## Install by hand

1. Install the tools: Git, Node.js 18 or newer, [uv](https://docs.astral.sh/uv/getting-started/installation/), pnpm (`corepack enable pnpm`), and, for the local LLM, [Ollama](https://ollama.com/download).
2. Download the code:
   ```bash
   git clone https://github.com/dev3-trojanitsolutions/voice-sandwich-demo.git
   cd voice-sandwich-demo
   ```
3. Install the packages, create `.env` and build the web pages:
   - macOS and Ubuntu: `make install-all`
   - Windows: `.\run.ps1 update`, then `copy .env.example .env`
4. Download the local LLM (optional): `make install-llm`, or `ollama pull qwen3.5:4b`.

## Set the admin password

The desk needs a login. Set the password of the user `admin` in the terminal:

```bash
make set-admin-password                    # macOS, Ubuntu
.\run.ps1 set-admin-password               # Windows
```

The command asks for the password two times and doesn't show it. It works while the server runs. Use it also when an admin forgets the password: it sets the new password, gives the user the Admin role, activates the user, and closes all of its logins.

For another user: `make set-admin-password ADMIN_USER=priya` or `.\run.ps1 set-admin-password priya`. If the user doesn't exist, the command creates it.

If you don't set a password, the first start creates `admin` with the password `1234`.

## Connect Gemini and the other services

Add the API keys on the desk: log in at `http://localhost:8000/desk/`, open **Settings → API Keys**, select **Add** next to the service, and paste the key. The server checks the key with the service before it saves it. You can also put the keys in `.env` before the first start; the first start copies them to the desk.

| Service | Get a key | Variable in `.env` | Needed by |
|---------|-----------|--------------------|-----------|
| Google Gemini | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | `GOOGLE_API_KEY` | Gemini mode (`realtime`, the default) |
| AssemblyAI (speech to text) | [assemblyai.com/dashboard](https://www.assemblyai.com/dashboard) | `ASSEMBLYAI_API_KEY` | Local mode without the voice service, `sandwich` |
| Cartesia (text to speech) | [play.cartesia.ai/keys](https://play.cartesia.ai/keys) | `CARTESIA_API_KEY` | Local mode without the voice service, `sandwich` |
| Anthropic (Claude) | [console.anthropic.com](https://console.anthropic.com/settings/keys) | `ANTHROPIC_API_KEY` | `sandwich` |

### Gemini (fastest, needs only one key)

1. Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. On the desk, open **Settings → API Keys** and add it next to **Gemini**.
3. Under **Voice Model**, select **Gemini**.
4. Open `http://localhost:8000` and start a call.

### Local LLM (Ollama)

1. Make sure Ollama runs: `ollama list` shows the model. If not, start the Ollama app, or run `ollama serve`.
2. Make sure the model is downloaded: `make install-llm` (or `ollama pull qwen3.5:4b`).
3. On the desk, under **Voice Model**, select **Local**. Or set `PIPELINE=ollama` in `.env`.
4. Speech: on an Apple silicon Mac, the voice service listens and speaks on the machine. On other machines, add the AssemblyAI and Cartesia keys.

Other settings in `.env`: `OLLAMA_MODEL` (the model name), `OLLAMA_BASE_URL` (default `http://localhost:11434`, change it to use Ollama on another machine).

### Claude (`sandwich`)

Add the AssemblyAI, Cartesia and Anthropic keys, then set `PIPELINE=sandwich` in `.env` and restart the server. The desk has no button for this mode.

## Run

| | macOS / Ubuntu | Windows |
|---|---|---|
| Start (normal use) | `make start-py` | `.\run.ps1 start` |
| Start for development (reload on changes, web watcher, voice service) | `make dev-py` | — |

Then open:

- Order page: `http://localhost:8000`
- Desk: `http://localhost:8000/desk/`

The first start takes longer: it downloads the embedding model and builds the knowledge base.

## Stop

- Press **Ctrl+C** in the terminal that runs the server.
- If a server stays in the background (for example after you close the terminal): `make stop` (macOS, Ubuntu) or `.\run.ps1 stop` (Windows). This stops the processes on ports 8000 and 8001 and the web watcher.
- To free the memory of the local LLM: `ollama stop qwen3.5:4b`. On Ubuntu, Ollama runs as a service: `sudo systemctl stop ollama`. On macOS with Homebrew: `brew services stop ollama`.

## Update

Run the install command again, or:

- macOS and Ubuntu: `git pull && make install-all`
- Windows: `.\run.ps1 update`

## Uninstall

1. Stop the server.
2. Delete the folder `voice-sandwich-demo`. This also deletes the data (`components/python/data/shop.db`).
3. Delete the model: `ollama rm qwen3.5:4b`.
4. Delete the downloaded models in `~/.cache/chroma` and `~/.cache/huggingface` if no other application uses them.

## Problems

| Problem | Fix |
|---------|-----|
| `uv`, `pnpm` or `ollama`: command not found after the install | Open a new terminal, so it reads the new `PATH`. |
| `Address already in use` on port 8000 | A server already runs. Stop it with `make stop` or `.\run.ps1 stop`. |
| Windows: "running scripts is disabled on this system" | Run `powershell -ExecutionPolicy Bypass -File .\run.ps1 start`. |
| The Local mode doesn't answer | Ollama doesn't run, or the model is missing. Run `ollama list`, and `make install-llm`. |
| The desk says a key is not valid | Copy the key again from the service, with no spaces. |
| `ERR_PNPM_IGNORED_BUILDS` | Use the current code: `allowBuilds` in `components/*/pnpm-workspace.yaml` must be `true`. |
