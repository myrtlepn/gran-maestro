---
name: "_shared"
description: "Internal shared include material for Gran Maestro skills. This is not a user-invocable workflow."
user-invocable: false
argument-hint: ""
---

# mst:_shared

This directory contains shared Markdown fragments used by the public Gran Maestro skills.
It is present only so plugin validators that scan direct `skills/` children can identify the
directory as intentional metadata instead of a malformed skill.

Do not invoke this entry as a workflow. Use `/mst:list` to find user-facing Gran Maestro skills.
