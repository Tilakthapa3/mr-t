"""Offline personal agent: chat loop, memory, skills, local tools.

The model runs on this machine (Ollama on localhost) or not at all:
--demo replays scripted replies through the same loop with no model
and no network, which is how the tests exercise the agent too.

Reply format the model must follow: plain text for a final answer, or
exactly one fenced JSON block for a tool call:

    ```json
    {"tool": "run_shell", "arguments": {"command": "uptime"}}
    ```

Standard library only.
"""

import argparse
import json
import os
import sys

from memory import load_memory
from model_client import MockClient, ModelUnavailable, OllamaClient
from skills import load_skills, skills_bodies, skills_index
from tools import TOOLS, execute_tool

MAX_STEPS = 8

SYSTEM_TEMPLATE = """You are a personal agent running fully offline on the user's own machine. No internet is available. Answer from memory, skills, and local tools only. Never claim to have browsed the web or sent a message.

{persona}

## Memory
{memory}

## Skills
{skills_index}

{skills_bodies}

## Tools
{tools_schema}

## Reply format
- To use a tool, reply with ONLY one fenced JSON block: ```json {{"tool": "<name>", "arguments": {{...}}}} ```
- Otherwise reply in plain text. That plain-text reply ends your turn.
- Use the smallest number of tool calls that gets the job done.
- Shell commands and file writes stay inside the workspace. Ask nothing; approval is handled outside you.
"""

DEMO_REPLIES = [
    '```json\n{"tool": "run_shell", "arguments": {"command": "uptime && df -h / && free -h"}}\n```',
    '```json\n{"tool": "write_file", "arguments": {"path": "reports/system-report.md", "content": "# System report\\n\\nSee tool output.\\n"}}\n```',
    "Done. I gathered uptime, disk, and memory, and saved the report to reports/system-report.md.",
]


def build_system_prompt(home_dir, skills_dir):
    memory_brief = load_memory(home_dir)
    persona_path = os.path.join(home_dir, "SOUL.md")
    persona = ""
    if os.path.isfile(persona_path):
        with open(persona_path, encoding="utf-8") as handle:
            persona = handle.read().strip()
    skills = load_skills(skills_dir)
    from tools import tools_schema

    return SYSTEM_TEMPLATE.format(
        persona=persona,
        memory=memory_brief,
        skills_index=skills_index(skills),
        skills_bodies=skills_bodies(skills),
        tools_schema=tools_schema(),
    )


def parse_tool_call(text):
    """Extract a tool call from the model's reply.

    Returns (name, args) for a valid call, (None, None) when the reply
    is plain text, and ("__error__", message) for a broken call block.
    """
    start = text.rfind("```json")
    if start == -1:
        start = text.rfind("```")
        if start == -1:
            return None, None
        fence = text[start:]
        end = fence.find("```", 3)
        block = fence[3:end] if end != -1 else fence[3:]
    else:
        fence = text[start:]
        end = fence.find("```", len("```json"))
        block = fence[len("```json"):end] if end != -1 else fence[len("```json"):]
    block = block.strip()
    if not block.startswith("{"):
        return None, None
    try:
        call = json.loads(block)
    except json.JSONDecodeError as exc:
        return "__error__", "Tool call was not valid JSON: %s" % exc
    name = call.get("tool")
    args = call.get("arguments", {})
    if name not in TOOLS:
        return "__error__", "Unknown tool %r. Known tools: %s" % (
            name, ", ".join(sorted(TOOLS)))
    if not isinstance(args, dict):
        return "__error__", "Tool arguments must be a JSON object."
    return name, args


def run_turn(client, messages, workspace, auto_approve=False, confirm=None):
    """Run one user turn through the tool loop. Returns the final text."""
    for _ in range(MAX_STEPS):
        reply = client.chat(messages)
        messages.append({"role": "assistant", "content": reply})
        name, args = parse_tool_call(reply)
        if name is None:
            return reply
        if name == "__error__":
            result = args
        else:
            result = execute_tool(workspace, name, args,
                                  auto_approve=auto_approve, confirm=confirm)
        messages.append({"role": "user",
                         "content": "Tool %s returned:\n%s"
                         % (name, result)})
    return "I stopped after %d tool steps without finishing." % MAX_STEPS


def ask_confirm(command):
    answer = input("Run this command? [y/N] %s\n> " % command).strip().lower()
    return answer in ("y", "yes")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline personal agent.")
    parser.add_argument("--home", default=".",
                        help="Directory holding SOUL.md, USER.md, MEMORY.md")
    parser.add_argument("--workspace", default=".",
                        help="Directory tools may read/write in")
    parser.add_argument("--skills", default="skills",
                        help="Skills directory")
    parser.add_argument("--model", default=None,
                        help="Local model name (default: $AGENT_MODEL or qwen2.5:7b)")
    parser.add_argument("--task", default=None,
                        help="Run one instruction non-interactively and exit")
    parser.add_argument("--yes", action="store_true",
                        help="Approve shell commands without asking")
    parser.add_argument("--demo", action="store_true",
                        help="Run the scripted demo with no model and no network")
    args = parser.parse_args(argv)

    home_dir = os.path.abspath(args.home)
    workspace = os.path.abspath(args.workspace)
    skills_dir = args.skills if os.path.isabs(args.skills) else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), args.skills)
    system_prompt = build_system_prompt(home_dir, skills_dir)
    messages = [{"role": "system", "content": system_prompt}]

    if args.demo:
        client = MockClient(DEMO_REPLIES)
        task = args.task or "Write a system status report."
        messages.append({"role": "user", "content": task})
        print(run_turn(client, messages, workspace, auto_approve=True))
        return 0

    client = OllamaClient(model=args.model)
    confirm = None if args.yes else ask_confirm
    auto_approve = bool(args.yes)

    if args.task:
        messages.append({"role": "user", "content": args.task})
        try:
            print(run_turn(client, messages, workspace,
                           auto_approve=auto_approve, confirm=confirm))
        except ModelUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    print("Mr T is ready. Type 'quit' to exit.")
    while True:
        try:
            user_text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_text.lower() in ("quit", "exit"):
            break
        if not user_text:
            continue
        messages.append({"role": "user", "content": user_text})
        try:
            answer = run_turn(client, messages, workspace,
                              auto_approve=auto_approve, confirm=confirm)
        except ModelUnavailable as exc:
            print(str(exc), file=sys.stderr)
            messages.pop()
            continue
        print("\nAgent: %s" % answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
