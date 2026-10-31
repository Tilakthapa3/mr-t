# Mr T — offline personal agent

A personal AI agent that runs fully offline on your own machine:
persistent memory, markdown skills, local tools, and a chat loop —
the same architecture as Hermes Agent, built small and understandable.

Nothing leaves the machine. No accounts, no API keys, no cloud.

## How it works

- **Local model** — talks to Ollama on `localhost:11434` only. The
  client never contacts any other host (see `model_client.py`).
- **Memory** — `SOUL.md` (persona), `USER.md` (about you), and
  `MEMORY.md` (durable facts) are loaded into every session, capped
  so the prompt stays small.
- **Skills** — one folder per skill under `skills/`, each with a
  `SKILL.md` playbook (name + description frontmatter, then markdown
  instructions). Adding a skill is adding a folder.
- **Tools** — `read_file` / `write_file` confined to the workspace,
  and `run_shell` which asks before running anything that is not
  read-only, unless you pass `--yes`.
- **Reply format** — the model answers in plain text, or with one
  fenced JSON block naming a tool call. The harness runs the tool and
  feeds the result back, up to 8 steps per turn.

## Requirements

- A computer (not a phone): roughly 8 GB of free RAM for a 7B model,
  about 5 GB of disk for the model file, Python 3.10+.
- Ollama: https://ollama.com — install it, then pull a model **once**
  (this one download needs internet):

```bash
ollama pull qwen2.5:7b
ollama serve
```

Any chat model works. Pick another with `AGENT_MODEL=<name>` or
`--model <name>`. After the download, you can disconnect from the
internet entirely and the agent keeps working.

## Run it

```bash
# Interactive chat in the terminal
python3 agent.py

# One instruction, non-interactive (this is what cron will call later)
python3 agent.py --task "Write a system status report." --yes

# Scripted demo: no model, no network, proves the loop end to end
python3 agent.py --demo
```

## What works offline — and what does not

Works offline: chat, memory, skills, local files, shell commands,
scheduled one-shot `--task` runs via the system cron.

Does not work offline: web search, and any messaging gateway
(Telegram, WhatsApp) — those need internet by definition, and are
planned as an optional later step, not part of the offline core.

## Tests

Standard library only, no model, no network:

```bash
python3 -m unittest discover -s tests -v
```

## Telegram gateway (step 2, optional, needs internet)

Mr T himself stays offline-first. The gateway in
`telegram_gateway.py` is the one part that uses the network: it polls
Telegram and carries messages to the local agent loop. Run it on a
machine that stays on (for example the same VM that runs Ollama).

Safety, by design:

- **Owner-only.** Only the chat id in `MR_T_OWNER_CHAT_ID` is served.
  Everyone else is ignored: no reply, no tool runs.
- **Token via environment, never in the repo.** Copy `.env.example`
  to `.env` on the host and fill it in. Make a **new** bot with
  [@BotFather](https://t.me/BotFather) for Mr T — do not reuse another
  project's bot.
- **Shell/file tools need `--yes`.** Without it, Mr T chats and reads
  files over Telegram but cannot run commands or write files.

```bash
# 1. Make a new bot with @BotFather, copy the token.
# 2. Message @userinfobot for your chat id.
# 3. On the host, next to telegram_gateway.py:
cp .env.example .env   # then fill in MR_T_BOT_TOKEN and MR_T_OWNER_CHAT_ID

# 4. Run it (Ollama must be running on the same machine):
python3 telegram_gateway.py --yes

# Scripted demo: no token, no network, proves the owner gate
python3 telegram_gateway.py --demo
```

Commands in chat: `/start` for a greeting, `/reset` to clear the
conversation. Conversation history is capped at the last 20 messages
plus the system prompt.

Run it persistently with systemd (sample unit — adjust paths):

```ini
[Unit]
Description=Mr T Telegram gateway
After=network-online.target ollama.service

[Service]
WorkingDirectory=/home/<you>/mr-t
ExecStart=/usr/bin/python3 telegram_gateway.py --yes
Restart=always
EnvironmentFile=/home/<you>/mr-t/.env

[Install]
WantedBy=multi-user.target
```

## Roadmap

- Step 3: built-in scheduler + skill learning (save a successful run
  as a new skill file, the Hermes learning loop)

## License

MIT — see `LICENSE`.
