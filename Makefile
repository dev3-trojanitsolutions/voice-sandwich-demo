.PHONY: bootstrap install-web install-ts install-py install-voice build-web dev-web start-ts start-py dev-ts dev-py dev-voice clean fetch-pincodes

##= Installation

bootstrap: install-web install-ts install-py

install-web:
	cd components/web && pnpm install

install-ts:
	cd components/typescript && pnpm install

install-py:
	cd components/python && uv sync --dev

# Local cloned voices (MLX, Apple silicon only). The models download on first start.
install-voice:
	uv sync --project components/voice

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

##= Utilities

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
