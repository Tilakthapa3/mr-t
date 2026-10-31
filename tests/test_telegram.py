"""Tests for the Telegram gateway — standard library only.

No token, no network: the Telegram API is always the fake client and
the model is always a MockClient.
"""

import html
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import DEMO_REPLIES
from model_client import MockClient
from telegram_gateway import (
    FakeTelegramClient,
    Gateway,
    extract_text,
    split_message,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")


def make_gateway(sent_updates, replies, owner=111, tmp=None):
    fake = FakeTelegramClient(sent_updates)
    gateway = Gateway(fake, MockClient(replies), tmp, tmp, SKILLS_DIR,
                      owner_chat_id=owner, auto_approve=True)
    return fake, gateway


class TestExtract(unittest.TestCase):
    def test_message_text(self):
        update = {"message": {"chat": {"id": 7}, "text": "hi"}}
        self.assertEqual(extract_text(update), (7, "hi"))

    def test_non_message_update_ignored(self):
        self.assertEqual(extract_text({"edited_message": {}}), (None, ""))


class TestSplit(unittest.TestCase):
    def test_short_message_unsplit(self):
        self.assertEqual(split_message("hello"), ["hello"])

    def test_long_message_split_within_limit(self):
        chunks = split_message("a" * 9000)
        self.assertTrue(all(len(c) <= 4096 for c in chunks))
        self.assertEqual("".join(chunks), "a" * 9000)

    def test_split_prefers_newlines(self):
        text = "line1\n" + "b" * 5000
        chunks = split_message(text, limit=100)
        self.assertEqual(chunks[0], "line1")


class TestGate(unittest.TestCase):
    def test_non_owner_gets_no_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, gateway = make_gateway([], ["answer"], tmp=tmp)
            update = {"update_id": 1,
                      "message": {"chat": {"id": 999}, "text": "do evil"}}
            self.assertFalse(gateway.handle_update(update))
            self.assertEqual(fake.sent, [])

    def test_owner_gets_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, gateway = make_gateway([], ["hello back"], tmp=tmp)
            update = {"update_id": 1,
                      "message": {"chat": {"id": 111}, "text": "hi"}}
            self.assertTrue(gateway.handle_update(update))
            self.assertEqual(len(fake.sent), 1)
            self.assertIn("hello back", html.unescape(fake.sent[0][1]))

    def test_start_and_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake, gateway = make_gateway([], ["answer"], tmp=tmp)
            gateway.handle_update({"update_id": 1, "message": {"chat": {"id": 111}, "text": "/start"}})
            self.assertIn("Mr T", html.unescape(fake.sent[0][1]))
            gateway.handle_update({"update_id": 2, "message": {"chat": {"id": 111}, "text": "hi"}})
            gateway.handle_update({"update_id": 3, "message": {"chat": {"id": 111}, "text": "/reset"}})
            self.assertIn("cleared", html.unescape(fake.sent[-1][1]).lower())
            self.assertEqual(len(gateway.histories[111]), 1)

    def test_history_capped_with_system_kept_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            replies = ["ok"] * 40
            fake, gateway = make_gateway([], replies, tmp=tmp)
            for i in range(30):
                gateway.handle_update(
                    {"update_id": i, "message": {"chat": {"id": 111},
                                                "text": "ping %d" % i}})
            history = gateway.histories[111]
            systems = [m for m in history if m["role"] == "system"]
            self.assertEqual(len(systems), 1)
            self.assertLessEqual(len(history), 21)


class TestDemoFlow(unittest.TestCase):
    def test_demo_replies_and_ignores_stranger(self):
        import telegram_gateway

        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeTelegramClient(telegram_gateway.DEMO_UPDATES)
            gateway = Gateway(fake, MockClient(DEMO_REPLIES), tmp, tmp,
                              SKILLS_DIR, owner_chat_id=111,
                              auto_approve=True)
            telegram_gateway.run_polling(gateway, fake, max_rounds=1)
        sent_chats = [chat for chat, _ in fake.sent]
        self.assertNotIn(999, sent_chats)
        self.assertIn(111, sent_chats)
        texts = " ".join(html.unescape(t) for _, t in fake.sent)
        self.assertIn("Conversation cleared", texts)


if __name__ == "__main__":
    unittest.main()
