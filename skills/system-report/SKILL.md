---
name: system-report
description: Write a short system status report (uptime, disk, memory) to reports/system-report.md
---

When the user asks for a system status report:

1. Run one read-only shell command gathering uptime, disk, and memory:
   `uptime && df -h / && free -h`
2. Write the results as markdown to `reports/system-report.md`, with
   one section per area and the exact command output in fenced blocks.
3. Reply with the report's path and a one-line summary of each area.

Never include anything that did not come from the command output.
