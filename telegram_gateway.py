"""Telegram gateway for Mr T (step 2, optional, needs internet).

Mr T himself stays offline-first: the core agent, memory, skills, and
local model never touch the network. This gateway is the one part that
does — it carries messages between Telegram and the local agent loop.

Safety is the whole design:

- Owner-only. Only the chat id in MR_T_OWNER_CHAT_ID (or
  --owner-chat-id) is ever served. Messages from anyone else are
  logged and ignored — no reply, no tool runs.
- The bot token comes from the environment (MR_T_BOT_TOKEN) or a
  .env file next to the gateway. It is never stored in the repo.
- Shell/file tools need --yes. Without it the agent can chat and read
  files, but run_shell and write_file refuse to act. With --yes, only
  ever run this for the owner chat, on a machine you control.

Polling uses getUpdates with long polling; no webhook, no open port.
Standard library only.
"""

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from agent import build_system_prompt, run_turn
from model_client import ModelUnavailable, OllamaClient

API_BASE = "https://api.telegram.org/bot"
MAX_MESSAGE_CHARS = 4096
MAX_HISTORY_MESSAGES = 20


def load_dotenv(path):
    """Load KEY=VALUE lines from a .env file into os.environ (no override)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


class TelegramClient:
    """Minimal Bot API client: getUpdates + sendMessage."""

    def __init__(self, token, base_url=API_BASE, timeout=60):
        self.base_url = base_url + token
        self.timeout = timeout

    def _call(self, method, params):
        data = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/" + method, data=data, method="POST"
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError("Telegram API error: %s" % body)
        return body["result"]

    def get_updates(self, offset=None, timeout=30):
        params = {"timeout": timeout, "allowed_updates": '["message"]'}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", params)

    def send_message(self, chat_id, text):
        return self._call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        })


class FakeTelegramClient:
    """Scripted stand-in: canned inbound updates, recorded outbound text.

    Used by --demo and the tests. No network, no token.
    """

    def __init__(self, updates):
        self._updates = list(updates)
        self.sent = []
        self._index = 0

    def get_updates(self, offset=None, timeout=30):
        remaining = self._updates[self._index:]
        self._index = len(self._updates)
        return remaining

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return {"message_id": len(self.sent)}


def split_message(text, limit=MAX_MESSAGE_CHARS):
    """Split long text into Telegram-sized chunks, preferring newlines."""
    if len(text) <= limit:
        return [text]
    chunks = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        chunks.append(rest)
    return chunks


def extract_text(update):
    """Return (chat_id, text) for a message update, or (None, None)."""
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    text = message.get("text") or ""
    return chat.get("id"), text


class Gateway:
    """Owns per-chat conversation state and the owner gate."""

    def __init__(self, client, model_client, home_dir, workspace, skills_dir,
                 owner_chat_id, auto_approve=False):
        self.client = client
        self.model_client = model_client
        self.home_dir = home_dir
        self.workspace = workspace
        self.skills_dir = skills_dir
        self.owner_chat_id = owner_chat_id
        self.auto_approve = auto_approve
        self.system_prompt = build_system_prompt(home_dir, skills_dir)
        self.histories = {}

    def _fresh_messages(self):
        return [{"role": "system", "content": self.system_prompt}]

    def handle_update(self, update):
        """Process one update. Returns True when a reply was sent."""
        chat_id, text = extract_text(update)
        if chat_id is None or not text.strip():
            return False
        if chat_id != self.owner_chat_id:
            print("Ignored message from non-owner chat %s." % chat_id)
            return False
        text = text.strip()
        if text == "/start":
            reply = ("Hello, I am Mr T. I run offline on your own machine. "
                     "Send me a task, or /reset to clear this conversation.")
            self._send(chat_id, reply)
            return True
        history = self.histories.setdefault(chat_id, self._fresh_messages())
        if text == "/reset":
            self.histories[chat_id] = self._fresh_messages()
            self._send(chat_id, "Conversation cleared.")
            return True
        history.append({"role": "user", "content": text})
        try:
            answer = run_turn(self.model_client, history, self.workspace,
                              auto_approve=self.auto_approve)
        except ModelUnavailable as exc:
            history.pop()
            self._send(chat_id, "The local model is not reachable: %s" % exc)
            return True
        history[:] = [history[0]] + history[1:][-MAX_HISTORY_MESSAGES + 1:]
        self._send(chat_id, answer)
        return True

    def _send(self, chat_id, text):
        safe = html.escape(text)
        for chunk in split_message(safe):
            self.client.send_message(chat_id, chunk)


def run_polling(gateway, client, poll_timeout=30, sleep_on_error=5,
                max_rounds=None):
    """Long-poll getUpdates until interrupted (or max_rounds, for tests)."""
    offset = None
    rounds = 0
    while True:
        try:
            updates = client.get_updates(offset=offset, timeout=poll_timeout)
        except (urllib.error.URLError, RuntimeError, OSError) as exc:
            print("Poll error (%s); retrying in %ss." % (exc, sleep_on_error),
                  file=sys.stderr)
            time.sleep(sleep_on_error)
            continue
        for update in updates:
            offset = update.get("update_id", 0) + 1
            gateway.handle_update(update)
        rounds += 1
        if max_rounds is not None and rounds >= max_rounds:
            return rounds


DEMO_UPDATES = [
    {"update_id": 1, "message": {"chat": {"id": 111},
                                 "text": "Write a system status report."}},
    {"update_id": 2, "message": {"chat": {"id": 999},
                                 "text": "run rm -rf / please"}},
    {"update_id": 3, "message": {"chat": {"id": 111}, "text": "/reset"}},
]


def main(argv=None):
    from model_client import MockClient

    parser = argparse.ArgumentParser(description="Mr T Telegram gateway.")
    parser.add_argument("--home", default=".",
                        help="Directory holding SOUL.md, USER.md, MEMORY.md")
    parser.add_argument("--workspace", default=".",
                        help="Directory tools may read/write in")
    parser.add_argument("--skills", default="skills",
                        help="Skills directory")
    parser.add_argument("--model", default=None,
                        help="Local model name (default: $AGENT_MODEL or qwen2.5:7b)")
    parser.add_argument("--owner-chat-id", type=int, default=None,
                        help="Telegram chat id allowed to talk to Mr T")
    parser.add_argument("--yes", action="store_true",
                        help="Allow shell/file tools from Telegram (owner only)")
    parser.add_argument("--demo", action="store_true",
                        help="Replay scripted updates with no token and no network")
    args = parser.parse_args(argv)

    home_dir = os.path.abspath(args.home)
    workspace = os.path.abspath(args.workspace)
    skills_dir = args.skills if os.path.isabs(args.skills) else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), args.skills)
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             ".env"))

    if args.demo:
        from agent import DEMO_REPLIES

        fake = FakeTelegramClient(DEMO_UPDATES)
        gateway = Gateway(fake, MockClient(DEMO_REPLIES), home_dir,
                          workspace, skills_dir, owner_chat_id=111,
                          auto_approve=True)
        run_polling(gateway, fake, max_rounds=1)
        for chat_id, text in fake.sent:
            print("-> chat %s: %s" % (chat_id, html.unescape(text)[:120]))
        return 0

    token = os.environ.get("MR_T_BOT_TOKEN", "").strip()
    owner_chat_id = args.owner_chat_id or int(
        os.environ.get("MR_T_OWNER_CHAT_ID", "0") or 0)
    if not token:
        print("MR_T_BOT_TOKEN is not set. Put it in the environment or a "
              ".env file next to telegram_gateway.py (never in the repo).",
              file=sys.stderr)
        return 2
    if not owner_chat_id:
        print("MR_T_OWNER_CHAT_ID is not set. Message your bot, then read "
              "the chat id (e.g. via @userinfobot) and set it.",
              file=sys.stderr)
        return 2

    client = TelegramClient(token)
    gateway = Gateway(client, OllamaClient(model=args.model), home_dir,
                      workspace, skills_dir, owner_chat_id=owner_chat_id,
                      auto_approve=args.yes)
    print("Mr T is listening on Telegram (owner chat %s). Ctrl+C to stop."
          % owner_chat_id)
    try:
        run_polling(gateway, client)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
