"""Skills: one folder per skill, each with a SKILL.md playbook.

Format follows the open agentskills.io convention: YAML-ish frontmatter
(name, description) between --- lines, then markdown instructions the
agent follows when the skill applies. A skill is just files — no code
to install, no network needed.
"""

import os


class Skill:
    def __init__(self, name, description, body, path):
        self.name = name
        self.description = description
        self.body = body
        self.path = path


def parse_skill_file(path):
    """Parse one SKILL.md file into a Skill. No frontmatter = plain doc."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    name = os.path.basename(os.path.dirname(path))
    description = ""
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[3:end]
            body = text[end + 4:].lstrip("\n")
            for line in front.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip().strip('"').strip("'")
                    if key == "name":
                        name = value
                    elif key == "description":
                        description = value
    return Skill(name=name, description=description, body=body, path=path)


def load_skills(skills_dir):
    """Load every skills/*/SKILL.md under skills_dir, sorted by name."""
    found = []
    if not os.path.isdir(skills_dir):
        return found
    for entry in sorted(os.listdir(skills_dir)):
        skill_file = os.path.join(skills_dir, entry, "SKILL.md")
        if os.path.isfile(skill_file):
            found.append(parse_skill_file(skill_file))
    found.sort(key=lambda skill: skill.name)
    return found


def skills_index(skills):
    """One-line index (name + description) for the system prompt."""
    lines = []
    for skill in skills:
        line = "- %s" % skill.name
        if skill.description:
            line += ": %s" % skill.description
        lines.append(line)
    return "\n".join(lines)


def skills_bodies(skills):
    """Full playbook text of every skill, for the system prompt."""
    parts = []
    for skill in skills:
        parts.append("### Skill: %s\n%s" % (skill.name, skill.body.strip()))
    return "\n\n".join(parts)
