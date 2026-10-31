"""Local-model client. Talks to Ollama on localhost only.

No internet is used: the default endpoint is http://localhost:11434 and
the client never contacts any other host. The model itself must already
be downloaded (one-time `ollama pull <model>`, which does need internet).
Standard library only.
"""

import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b"
CHAT_PATH = "/v1/chat/completions"


class ModelUnavailable(Exception):
    """Raised when no local model server answers."""


class OllamaClient:
    """Minimal chat-completions client for a local Ollama server."""

    def __init__(self, model=None, base_url=None, timeout=120):
        self.model = model or os.environ.get("AGENT_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL",
                                                    DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout

    def chat(self, messages, temperature=0.2):
        """Return the assistant's reply text for a list of messages."""
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + CHAT_PATH,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise ModelUnavailable(
                "No local model server answered at %s. Start Ollama "
                "(`ollama serve`) and pull a model once "
                "(`ollama pull %s`), then try again. Original error: %s"
                % (self.base_url, self.model, exc)
            ) from exc
        except (json.JSONDecodeError, KeyError) as exc:
            raise ModelUnavailable(
                "The local model server at %s gave an unreadable reply: %s"
                % (self.base_url, exc)
            ) from exc
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelUnavailable(
                "The local model server at %s gave an unexpected reply "
                "shape: %s" % (self.base_url, exc)
            ) from exc


class MockClient:
    """Scripted stand-in for the model, used by --demo and the tests.

    Returns the scripted replies in order, then repeats the last one.
    Makes no network calls at all.
    """

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat(self, messages, temperature=0.2):
        idx = min(self.calls, len(self.replies) - 1)
        self.calls += 1
        return self.replies[idx]
