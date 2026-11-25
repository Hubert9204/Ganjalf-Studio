---
name: init
description: Only when the user types /init - explore the project folder and write AGENTS.md, the project guide every new chat reads first. Italiano - /init, crea AGENTS.md.
allowed-tools: glob grep read_file terminal edit_file todo_write run_agent
metadata:
  auto-load: "false"
---

# /init: write the project guide

AGENTS.md in the project folder is read at the start of every chat in this project (CLAUDE.md is read the same way). A good one saves each new chat the exploration you are about to do. Write it for a later run of yourself that knows nothing about this project.

## 1. Explore (read only)
- `glob` the tree (skip `node_modules`, `.git`, `dist`, `build`, virtual envs). In a big project hand the survey to `run_agent` with agent `explore`.
- Read what defines the project: `package.json` / `pyproject.toml` / `Cargo.toml` / `go.mod` / `Makefile`, the README, config files (`vite.config.*`, `tsconfig.json`, lint and test configs), and the entry points.
- Find the real commands: install, dev server, build, test, lint, typecheck. Prefer the ones in scripts/Makefile over guesses.
- If an AGENTS.md or CLAUDE.md already exists, read it: you will improve it, keeping what the user wrote.

## 2. Check the commands
Run the cheap ones once (typecheck, lint, the test command with a narrow target). Write only commands you saw work, or mark them "not checked".

## 3. Write AGENTS.md (with `edit_file`, in the project folder)
Keep it under about 120 lines. Sections, in this order, only those with real content:
- **What this is**: one or two sentences.
- **Commands**: install, dev (and its address), build, test, lint, typecheck, each as a code span.
- **Layout**: the folders that matter and what lives in each; the entry points.
- **Conventions**: language/framework versions, code style, naming, how modules talk to each other, anything a newcomer would get wrong.
- **Checks before saying done**: the exact commands and, for a web app, `check_page` on the page.
- **Gotchas**: things that broke before or that are easy to break.

Facts only, no marketing and no generic advice ("write clean code"). Prefer "run `npx tsc --noEmit`, zero errors" over "make sure types are correct".

## 4. Report
Tell the user in two or three lines what the file covers and which commands you could not check. Do not paste the whole file in the reply.
