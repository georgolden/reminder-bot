# reminder-bot

Telegram reminder bot built with PocketFlow + APScheduler.

## Safety (must-read)
- **Never commit secrets.** No `.env` files are loaded by code in this repo.
- **Never commit user data.** Runtime storage lives under `data/` and is gitignored.

## Requirements
- Python 3.13+
- Poetry

## Setup

### 1) Set environment variables
You provide these locally (shell, systemd, your own `.env` tooling, etc.):

- `TELEGRAM_BOT_TOKEN` (required)
- `DEEPSEEK_API_KEY` (required; used by the agent LLM calls)

Optional:
- `DEFAULT_TIMEZONE` (defaults to UTC if you don’t set a user timezone)

### 2) Install deps

```bash
poetry install --no-root
```

### 3) Run

```bash
poetry run python main.py
```

## Running in Production

### Systemd Service (Linux)

1) Create an env file (recommended):

Create `/etc/reminder-bot.env` (permissions `0600`) with:

```bash
TELEGRAM_BOT_TOKEN=...   # required
DEEPSEEK_API_KEY=...     # required
# DEFAULT_TIMEZONE=UTC   # optional
```

2) Create the systemd unit:

Create `/etc/systemd/system/reminder-bot.service`:

```ini
[Unit]
Description=Telegram Reminder Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/reminder-bot
EnvironmentFile=/etc/reminder-bot.env
ExecStart=/path/to/poetry run python main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3) Enable + start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable reminder-bot
sudo systemctl start reminder-bot

# logs
journalctl -u reminder-bot -f
```

Notes:
- Ensure `WorkingDirectory` points at the repo root so relative paths (like `data/`) resolve correctly.
- Keep secrets out of the unit file; use `EnvironmentFile=`.

## Project structure
- `main.py` — Telegram bot entry point
- `flow.py` / `nodes.py` / `tools.py` — PocketFlow agent logic
- `utils/` — scheduler + storage
- `utlis/` — LLM call helper (kept to match superhuman naming)
- `data/` — runtime storage (gitignored)

## Notes
- Storage files are created at runtime under `data/`.
- If you deploy this, ensure the working directory is the repo root so relative paths resolve correctly.
