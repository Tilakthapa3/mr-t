"""Persistent memory: SOUL.md, USER.md, MEMORY.md.

The same three-file shape Hermes popularized: a persona file, a file
about the user, and a durable memory file. All plain markdown in the
agent's home directory, all local. The combined brief is capped so the
prompt stays small; the cap forces keeping only what is durable.
"""

import os

MEMORY_BUDGET_CHARS = 3500
MEMORY_FILES = ("SOUL.md", "USER.md", "MEMORY.md")


def load_memory(home_dir, budget=MEMORY_BUDGET_CHARS):
    """Return the memory brief: the three files, concatenated, capped.

    Files are read in order SOUL, USER, MEMORY. Missing files are
    skipped. If the total exceeds the budget, the oldest content
    (the tail of MEMORY.md) is dropped first and a note is added.
    """
    parts = []
    total = 0
    for name in MEMORY_FILES:
        path = os.path.join(home_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            text = handle.read().strip()
        if not text:
            continue
        parts.append("## %s\n%s" % (name, text))
        total += len(text)
    brief = "\n\n".join(parts)
    if len(brief) > budget:
        brief = brief[:budget].rstrip()
        brief += "\n\n[Memory brief truncated to %d chars.]" % budget
    return brief


def append_memory(home_dir, entry):
    """Append one dated line to MEMORY.md, creating the file if needed."""
    from datetime import date

    path = os.path.join(home_dir, "MEMORY.md")
    line = "- %s: %s\n" % (date.today().isoformat(), entry.strip())
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
    return line.strip()
