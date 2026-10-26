.PHONY: bootstrap install-all install-web install-ts install-py install-voice install-llm build-web dev-web start-ts start-py dev-ts dev-py dev-voice stop set-admin-password clean fetch-pincodes

##= Installation

bootstrap: install-web install-ts install-py

# Everything: all packages, the voice service on Apple silicon (NO_VOICE=1
# skips it), .env and the web build.
# install.sh runs this after the clone.
install-all: bootstrap
	@if [ -z "$(NO_VOICE)" ] && [ "$$(uname -sm)" = "Darwin arm64" ]; then $(MAKE) install-voice; \
		else echo "Skipping the voice service (Apple silicon only)"; fi
	@[ -f .env ] || (cp .env.example .env && echo "Created .env from .env.example")
	$(MAKE) build-web

install-web:
	cd components/web && pnpm install

install-ts:
	cd components/typescript && pnpm install

install-py:
	cd components/python && uv sync --dev

# Local cloned voices (MLX, Apple silicon only). The models download on first start.
install-voice:
	uv sync --project components/voice

# Local LLM for the ollama pipeline. Ollama must be installed and running.
OLLAMA_MODEL ?= $(or $(shell sed -n 's/^OLLAMA_MODEL=//p' .env 2>/dev/null),qwen3.5:4b)

install-llm:
	ollama pull $(OLLAMA_MODEL)

##= Web Build

build-web:
	cd components/web && pnpm build

# Watch mode for web - rebuilds on changes
dev-web:
	cd components/web && pnpm build --watch

##= Development (web watch + server)

# TypeScript server with web watch
dev-ts:
	@echo "Starting web build watcher and TypeScript server..."
	@trap 'kill 0' EXIT; \
		(cd components/web && pnpm build --watch) & \
		sleep 2 && cd components/typescript && pnpm run server

# Python server with web watch. Also starts the local voice service when it
# is installed (make install-voice) and not already running.
dev-py:
	@echo "Starting web build watcher and Python server..."
	@trap 'kill 0' EXIT; \
		(cd components/web && pnpm build --watch) & \
		if [ -d components/voice/.venv ] && ! lsof -nP -iTCP:8001 -sTCP:LISTEN >/dev/null 2>&1; then \
			uv run --project components/voice python components/voice/server.py & \
		fi; \
		sleep 2 && cd components/python && uv run src/main.py

# Local voice service for cloned voices and accents, on port 8001
dev-voice:
	uv run --project components/voice python components/voice/server.py

##= Server Only (no web watch - use pre-built assets)

start-ts: build-web
	cd components/typescript && pnpm run server

start-py: build-web
	cd components/python && uv run src/main.py

# Stop a server, voice service or web watcher left running (Ctrl+C also stops them)
stop:
	@for port in 8000 8001; do \
		pids=$$(lsof -ti tcp:$$port -sTCP:LISTEN 2>/dev/null); \
		if [ -n "$$pids" ]; then kill $$pids && echo "Stopped port $$port"; \
		elif command -v fuser >/dev/null && fuser -k $$port/tcp 2>/dev/null; then echo "Stopped port $$port"; fi; \
	done
	@pkill -f "vite build --watch" 2>/dev/null && echo "Stopped the web watcher" || true

##= Utilities

# Set or reset a desk admin password (asks for it). ADMIN_USER=... for another user.
ADMIN_USER ?= admin

set-admin-password:
	@uv run --project components/python python components/python/scripts/set_admin_password.py $(ADMIN_USER)

# Rebuild the delivery areas the desk starts with, from India Post data
fetch-pincodes:
	uv run --project components/python python components/python/scripts/fetch_pincodes.py

clean:
	rm -rf components/web/dist
	rm -rf components/web/node_modules
	rm -rf components/typescript/node_modules
	rm -rf components/python/.venv
	rm -rf components/python/.chroma

# Type checking
check-web:
	cd components/web && pnpm check

check-ts:
	cd components/typescript && pnpm run typecheck

check: check-web check-ts
