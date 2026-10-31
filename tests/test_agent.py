"""Tests for the offline agent — standard library only.

Run from the repo root:

    python3 -m unittest discover -s tests -v

No model, no network: the model is always a MockClient here, and the
offline guarantee is asserted at the client configuration level.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent
import memory
import skills
import tools
from model_client import DEFAULT_BASE_URL, MockClient, OllamaClient

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSkills(unittest.TestCase):
    def test_frontmatter_parsed(self):
        path = os.path.join(REPO_ROOT, "skills", "system-report", "SKILL.md")
        skill = skills.parse_skill_file(path)
        self.assertEqual(skill.name, "system-report")
        self.assertIn("system status report", skill.description)
        self.assertIn("uptime", skill.body)

    def test_load_skills_sorted(self):
        found = skills.load_skills(os.path.join(REPO_ROOT, "skills"))
        names = [s.name for s in found]
        self.assertEqual(names, ["remember", "system-report"])
        self.assertIn("remember", skills.skills_index(found))

    def test_missing_skills_dir_is_empty(self):
        self.assertEqual(skills.load_skills("/nonexistent-dir"), [])


class TestMemory(unittest.TestCase):
    def test_load_missing_files_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(memory.load_memory(tmp), "")

    def test_load_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "MEMORY.md"), "w") as handle:
                handle.write("x" * 5000)
            brief = memory.load_memory(tmp, budget=100)
            self.assertLessEqual(len(brief), 200)
            self.assertIn("truncated", brief)

    def test_append_memory_dated_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = memory.append_memory(tmp, "likes dark mode")
            with open(os.path.join(tmp, "MEMORY.md")) as handle:
                content = handle.read()
            self.assertIn("likes dark mode", content)
            self.assertTrue(line.startswith("- 2026"))


class TestToolCalls(unittest.TestCase):
    def test_plain_text_is_not_a_call(self):
        name, args = agent.parse_tool_call("Hello, here is your answer.")
        self.assertIsNone(name)
        self.assertIsNone(args)

    def test_valid_fenced_call(self):
        reply = '```json\n{"tool": "run_shell", "arguments": {"command": "uptime"}}\n```'
        name, args = agent.parse_tool_call(reply)
        self.assertEqual(name, "run_shell")
        self.assertEqual(args, {"command": "uptime"})

    def test_broken_json_is_error(self):
        name, _ = agent.parse_tool_call('```json\n{"tool": "run_shell",\n```')
        self.assertEqual(name, "__error__")

    def test_unknown_tool_is_error(self):
        reply = '```json\n{"tool": "browse_web", "arguments": {}}\n```'
        name, _ = agent.parse_tool_call(reply)
        self.assertEqual(name, "__error__")


class TestTools(unittest.TestCase):
    def test_write_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("Wrote", tools.write_file(tmp, "a/b.txt", "hi"))
            self.assertEqual(tools.read_file(tmp, "a/b.txt"), "hi")

    def test_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("outside", tools.write_file(tmp, "../evil.txt", "x"))
            self.assertIn("outside", tools.read_file(tmp, "../evil.txt"))

    def test_read_only_commands_run_unapproved(self):
        self.assertIn("load average", tools.run_shell("uptime"))

    def test_write_command_needs_approval(self):
        result = tools.run_shell("echo hi", auto_approve=False, confirm=None)
        self.assertIn("not run", result)

    def test_declined_command_does_not_run(self):
        result = tools.run_shell("echo hi", confirm=lambda cmd: False)
        self.assertIn("declined", result)

    def test_unknown_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = tools.execute_tool(tmp, "browse_web", {})
            self.assertIn("unknown tool", result)


class TestLoop(unittest.TestCase):
    def test_loop_executes_tool_and_returns_answer(self):
        client = MockClient([
            '```json\n{"tool": "run_shell", "arguments": {"command": "echo hello"}}\n```',
            "The command printed hello.",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            messages = [{"role": "user", "content": "run echo"}]
            answer = agent.run_turn(client, messages, tmp, auto_approve=True)
        self.assertEqual(answer, "The command printed hello.")
        self.assertEqual(client.calls, 2)

    def test_loop_stops_after_max_steps(self):
        client = MockClient([
            '```json\n{"tool": "run_shell", "arguments": {"command": "echo hi"}}\n```'
        ])
        with tempfile.TemporaryDirectory() as tmp:
            answer = agent.run_turn(client, [{"role": "user", "content": "go"}],
                                    tmp, auto_approve=True)
        self.assertIn("stopped after", answer)

    def test_demo_writes_report_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = agent.main(["--home", tmp, "--workspace", tmp, "--demo"])
            self.assertEqual(rc, 0)
            report = os.path.join(tmp, "reports", "system-report.md")
            self.assertTrue(os.path.isfile(report))
            with open(report) as handle:
                self.assertIn("System report", handle.read())


class TestOfflineConfig(unittest.TestCase):
    def test_default_endpoint_is_localhost(self):
        client = OllamaClient()
        self.assertTrue(client.base_url.startswith("http://localhost"))
        self.assertEqual(DEFAULT_BASE_URL, "http://localhost:11434")

    def test_system_prompt_mentions_offline(self):
        prompt = agent.build_system_prompt(REPO_ROOT,
                                           os.path.join(REPO_ROOT, "skills"))
        self.assertIn("offline", prompt.lower())
        self.assertIn("system-report", prompt)


if __name__ == "__main__":
    unittest.main()
