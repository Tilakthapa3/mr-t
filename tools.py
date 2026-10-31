"""Local tools. Everything runs on this machine; nothing is uploaded.

- read_file / write_file are confined to the workspace directory.
- run_shell asks the user before running anything that is not on the
  read-only allowlist, unless --yes was passed. Read-only commands
  (uptime, df, free, ls, ...) run without asking.
"""

import os
import shlex
import subprocess

READ_ONLY_PREFIXES = (
    "uptime", "df", "free", "ls", "cat", "head", "tail", "wc",
    "whoami", "hostname", "date", "pwd", "du", "ps", "uname",
)


def _inside_workspace(workspace, path):
    workspace = os.path.realpath(workspace)
    target = os.path.realpath(os.path.join(workspace, path))
    return target, target == workspace or target.startswith(workspace + os.sep)


def read_file(workspace, path):
    target, ok = _inside_workspace(workspace, path)
    if not ok:
        return "Error: path %r is outside the workspace." % path
    if not os.path.isfile(target):
        return "Error: no such file: %s" % path
    try:
        with open(target, encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        return "Error reading %s: %s" % (path, exc)


def write_file(workspace, path, content):
    target, ok = _inside_workspace(workspace, path)
    if not ok:
        return "Error: path %r is outside the workspace." % path
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(content)
        return "Wrote %d bytes to %s." % (len(content), path)
    except OSError as exc:
        return "Error writing %s: %s" % (path, exc)


def is_read_only(command):
    """True when the command starts with a read-only program name."""
    try:
        first = shlex.split(command.strip())[0]
    except (IndexError, ValueError):
        return False
    first = os.path.basename(first)
    return first in READ_ONLY_PREFIXES


def run_shell(command, auto_approve=False, confirm=None, timeout=60):
    """Run one shell command, asking first unless it is read-only.

    confirm, when given, is called with the command text and must
    return True to proceed. Returns combined stdout+stderr text.
    """
    if not auto_approve and not is_read_only(command):
        if confirm is not None and not confirm(command):
            return "Command not run: user declined."
        if confirm is None:
            return "Command not run: approval required (pass --yes or approve)."
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return "Error: command timed out after %ds." % timeout
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        return "Exit %d:\n%s" % (result.returncode, output or "(no output)")
    return output or "(no output)"


TOOLS = {
    "read_file": {
        "description": "Read a text file inside the workspace. Args: path.",
        "args": ["path"],
    },
    "write_file": {
        "description": "Write text to a file inside the workspace. Args: path, content.",
        "args": ["path", "content"],
    },
    "run_shell": {
        "description": "Run one shell command on this machine. Args: command.",
        "args": ["command"],
    },
}


def tools_schema():
    """One-line-per-tool schema text for the system prompt."""
    lines = []
    for name, spec in TOOLS.items():
        lines.append("- %s(%s): %s"
                     % (name, ", ".join(spec["args"]), spec["description"]))
    return "\n".join(lines)


def execute_tool(workspace, name, args, auto_approve=False, confirm=None):
    """Dispatch one validated tool call; returns result text."""
    if name == "read_file":
        return read_file(workspace, args.get("path", ""))
    if name == "write_file":
        return write_file(workspace, args.get("path", ""),
                          args.get("content", ""))
    if name == "run_shell":
        return run_shell(args.get("command", ""), auto_approve=auto_approve,
                         confirm=confirm)
    return "Error: unknown tool %r." % name
