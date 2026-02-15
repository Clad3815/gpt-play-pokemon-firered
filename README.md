# GPT Plays Pokemon FireRed

> An autonomous AI agent that plays Pokemon FireRed in real time, powered by OpenAI's LLM — with a live web dashboard for monitoring.

---

## Overview

This project connects a large language model (LLM) to a running instance of **Pokemon FireRed** through a multi-layered architecture:

| Layer | Component | Role |
|-------|-----------|------|
| **Emulator** | mGBA + Lua script | Runs the game and exposes a socket bridge |
| **Bridge** | `firered_mgba_bridge.py` (FastAPI) | Reads game memory and sends inputs to the emulator |
| **Agent** | `server/index.js` (Node.js) | Runs the AI decision loop, chooses actions, manages state |
| **Dashboard** | `frontend/` (HTML/CSS/JS) | Live monitoring UI — logs, minimap, inventory, team, objectives |

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.10+ |
| Node.js | 18+ |
| mGBA | With Lua scripting support enabled |
| Pokemon FireRed ROM | `.gba` file (not included) |
| OpenAI API key | Set as `OPENAI_API_KEY` |

---

## Project Structure

```
├── firered_mgba_bridge.py      # FastAPI bridge — reads game state, sends commands
├── firered_bridge/             # Memory reading logic, game state, minimap, fog of war
├── mgba/scripts/
│   └── FireRedBridgeSocketServer.lua  # Lua script to load inside mGBA
├── server/                     # AI agent loop + WebSocket + runtime persistence
│   └── prompts/                # Prompts used by the AI agent
├── frontend/                   # Static HTML/CSS/JS monitoring dashboard
├── .env.example                # Environment template (bridge / mGBA)
└── server/.env.example         # Environment template (agent / OpenAI)
```

---

## Getting Started

### 1. Clone the repository

```bash
git clone <repo-url>
cd gpt-play-pokemon-firered-open-source
```

If you use the `pokefirered` submodule:

```bash
git submodule update --init --recursive
```

### 2. Create environment files

<details>
<summary><strong>macOS / Linux</strong></summary>

```bash
cp .env.example .env
cp server/.env.example server/.env
```

</details>

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

```powershell
Copy-Item .env.example .env
Copy-Item server/.env.example server/.env
```

</details>

### 3. Fill in the environment variables

**`server/.env`** (required):

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | Your OpenAI API key | *(required)* |
| `PYTHON_BASE_URL` | Bridge API URL | `http://127.0.0.1:8000` |
| `WS_PORT` | WebSocket port for the dashboard | `9885` |

**`.env`** (root — bridge & mGBA):

| Variable | Description | Default |
|----------|-------------|---------|
| `MGBA_TRANSPORT` | Transport mode | `socket` *(recommended)* |
| `MGBA_SOCKET_HOST` | mGBA socket host | `127.0.0.1` |
| `MGBA_SOCKET_PORT` | Starting port for mGBA socket | `8888` |
| `MGBA_SOCKET_PORT_MAX` | Max port to scan | `8896` |
| `FIRERED_GAME_DATA_DIR` | Game data directory | `game_data_firered` |
| `FIRERED_MINIMAPS_DIR` | Minimap output directory | `minimaps` |
| `FIRERED_SCREENSHOT_DIR` | Screenshot output directory | `tmp_screenshots` |

> **Note:** The Lua script in mGBA starts listening on port `8888` and increments if the port is busy. The Python bridge scans the range `MGBA_SOCKET_PORT` → `MGBA_SOCKET_PORT_MAX`. If mGBA listens outside this range, the connection will fail.

### 4. Install dependencies

From the project root:

```bash
python -m pip install -r requirements.txt
cd server && npm install && cd ..
```

---

## Running the Project

> **Important:** Components must be started **in this exact order**.

### Step 1 — Start mGBA + Lua script

1. Open **mGBA**
2. Load the **FireRed ROM**
3. Open the **Lua scripting window** (`Tools → Scripting`)
4. Load `mgba/scripts/FireRedBridgeSocketServer.lua`
5. Keep the script running

You should see a log message indicating the listening port (e.g. `Listening on port 8888`).

### Step 2 — Start the Python bridge

The bridge auto-loads the root `.env` file via `python-dotenv`.

```bash
python firered_mgba_bridge.py
```

The FastAPI server runs at `http://127.0.0.1:8000` by default and exposes:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/requestData` | GET | Fetch current game state |
| `/minimapSnapshot` | GET | Get the current minimap image |
| `/sendCommands` | POST | Send button inputs to the game |
| `/restartConsole` | POST | Restart the emulator bridge |

### Step 3 — Start the Node.js agent server

```bash
cd server
npm start
```

The server runs at `http://127.0.0.1:9885` (HTTP + WebSocket).

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |

For development with auto-reload:

```bash
npm run dev
```

### Step 4 — Open the dashboard *(optional but recommended)*

```bash
cd frontend
python -m http.server 5173
```

Then open **http://127.0.0.1:5173** in your browser.

The dashboard connects to WebSocket on port `9885` of the current hostname by default.

---

## Quick Health Check

Once everything is running, verify each layer:

| # | Component | How to verify |
|---|-----------|---------------|
| 1 | **mGBA + Lua** | Script is loaded, no socket errors in the Lua console |
| 2 | **Python bridge** | `GET http://127.0.0.1:8000/requestData` returns `{"ok": true, ...}` |
| 3 | **Node.js agent** | `GET http://127.0.0.1:9885/health` returns `{"ok": true, ...}` |
| 4 | **Dashboard** | Click **Connect** → logs and game state stream in via WebSocket |

---

## Environment Variables Reference

<details>
<summary><strong>Root <code>.env</code> — Python bridge / mGBA</strong></summary>

**Socket transport:**
- `MGBA_TRANSPORT` — `socket` *(recommended)* or `http`
- `MGBA_SOCKET_HOST`, `MGBA_SOCKET_PORT`, `MGBA_SOCKET_PORT_MAX`, `MGBA_SOCKET_TIMEOUT`

**HTTP transport (alternative):**
- `MGBA_API_URL`, `MGBA_HTTP_TIMEOUT`, `MGBA_READ_RANGE_CHUNK`

**Game data:**
- `FIRERED_GAME_DATA_DIR`, `FIRERED_MINIMAPS_DIR`, `FIRERED_SCREENSHOT_DIR`

**Savestate backups:**
- `FIRERED_SAVESTATE_BACKUP_*`

**Debug / advanced:**
- `FIRERED_SYM_PATH`, `FIRERED_BRIDGE_STRICT_SYMBOLS`, `FIRERED_BRIDGE_DEBUG_SAVE_INFO`
- `FIRERED_BENCHMARK`

</details>

<details>
<summary><strong><code>server/.env</code> — Node.js agent / OpenAI</strong></summary>

**Server:**
- `WS_PORT` — WebSocket port
- `PYTHON_BASE_URL` — Bridge API URL

**OpenAI:**
- `OPENAI_API_KEY` — API key *(required)*
- `OPENAI_MODEL`, `OPENAI_MODEL_PATHFINDING` — Model selection
- `OPENAI_REASONING_EFFORT*` — Reasoning effort settings
- `OPENAI_TOKEN_LIMIT`, `OPENAI_TIMEOUT_MS` — Limits
- `OPENAI_SERVICE_TIER*` — Service tier settings

</details>

---

## Runtime Data

The project generates the following files and directories during execution:

| Path | Contents |
|------|----------|
| `tmp_screenshots/` | In-game screenshots |
| `minimaps/` | Generated minimap images |
| `backup_saves/` | Automatic savestate backups |
| `server/gpt_data/` | AI agent persistent state (see below) |

**`server/gpt_data/` contents:**

- `history.json` — Conversation / action history
- `memory.json` — Agent long-term memory
- `objectives.json` — Current goals and objectives
- `markers.json` — Map markers set by the agent
- `counters.json` — Internal counters
- `summaries.json`, `all_summaries.json` — Session summaries
- `progress_steps.json` — Game progress tracking
- `map_visits.json` — Map visit log
- `badges_log.json` — Badge acquisition log
- `token_usage.json`, `time_usage.json` — Usage statistics
- `last_criticism.txt` — Latest self-critique

---

## Troubleshooting

<details>
<summary><strong>Python bridge can't connect to mGBA</strong></summary>

- Make sure the **Lua script is loaded and running** in mGBA
- Check the port range: `MGBA_SOCKET_PORT` → `MGBA_SOCKET_PORT_MAX` must cover the port mGBA is listening on
- Verify both processes are on the **same machine / network**

</details>

<details>
<summary><strong>Node.js agent keeps failing on Python calls</strong></summary>

- Confirm the Python bridge is running at the URL set in `PYTHON_BASE_URL`
- Test manually: `curl http://127.0.0.1:8000/requestData`

</details>

<details>
<summary><strong>Dashboard shows nothing</strong></summary>

- Check the **host and port** in the dashboard UI
- Make sure `WS_PORT` matches the Node.js server port
- Open the **browser console** and look for WebSocket errors

</details>

<details>
<summary><strong>OpenAI errors</strong></summary>

- Verify `OPENAI_API_KEY` is set correctly in `server/.env`
- **Restart the Node.js server** after any `.env` change

</details>

---

## Best Practices

- **Never commit** `.env` or `server/.env` — they contain secrets
- **Back up saves externally** if you want persistent savestate backups
- **Keep all components running on stable versions** during long play sessions to avoid mid-run breakage

---

## License

This project is open source. See [LICENSE](LICENSE) for details.
