---
name: openspec-propose
description: "Create a change proposal and generate all planning artifacts in one step via the OpenSpec CLI."
---

# openspec-propose

This skill runs the OpenSpec CLI command to propose a new change and generate the required planning artifacts (`proposal.md`, `design.md`, `specs/.../spec.md`, `tasks.md`).

## Usage
```
openspec propose <change-name>
```
- `<change-name>` must be kebab‑case (lowercase letters, numbers, and hyphens).
- The command creates the change directory under `openspec/changes/` and writes all required artifacts according to the project's workflow schema.

The skill does **not** perform any implementation; it only produces the planning artifacts. After the artifacts are ready, you should run `/opsx:apply <change-name>` to start the implementation phase.
