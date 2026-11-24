---
name: skill-creator
description: Create or improve a reusable skill when the user asks to save, teach or turn a workflow into a skill, or when a long task just solved is worth repeating. Italiano - crea una skill, salva come skill, impara questa procedura, migliora la skill.
allowed-tools: create_skill read_skill
---

# Create a skill

A skill is a procedure that a later run of you follows without this conversation. It says **how** to do a kind of work, in order, with the commands and checks that worked. It is not a description of a project or a feature list: "Systems to implement: 1. Camera 2. Combat" tells a later run nothing it could not guess, while "Phase 2: add the camera, run `npx tsc --noEmit`, zero errors before Phase 3" saves it an hour.

## 1. Gather before writing
- **The job and the trigger.** One kind of work per skill. When the work was one project (a game, an app), write the method for building that kind of project, with this project as the example.
- **What this conversation proved.** The commands that worked (exact, with versions), every error that was hit and the fix, what the user corrected or asked for, and how the result was verified. These are the most valuable lines in the skill.
- **Existing skills.** Check the catalog. To improve one you created, call `create_skill` with `replace: true` instead of making a near-copy under a new name.
- Ask the user only about details that change the procedure.

## 2. Write SKILL.md (the `instructions` field)
Keep it under about 300 lines; move long material into files (section 3). Use this layout:

1. **Goal and done.** One paragraph: what the skill produces and the exact condition for "done" (for example "builds with zero errors, `check_page dist/index.html` shows no errors and the HUD").
2. **When to use / when not.**
3. **Inputs.** What to ask or detect first, with defaults.
4. **Procedure.** Numbered phases, each small enough to verify. Every phase gives the exact commands or files to write and ends with a **checkpoint**: the command to run and what success looks like. Put something runnable early (the smallest working slice), then add one system per phase.
5. **Rules.** Working habits that save calls: one install command, change files with `edit_file` (never rewrite a whole file to fix an error), read big files in ranges, background servers with `nohup … &`, for web pages `check_page` on the built page.
6. **Pitfalls.** A short table: symptom, cause, fix. Fill it from this conversation.
7. **Verification.** The tests or self-test flag to run, and what to check by eye (screenshot, output).
8. **Final report.** What the answer to the user must contain: what was built, how to run it, what was verified, what is still open.
9. **Files in this skill.** Each extra file with when to read, copy or run it.

Write imperative and concrete sentences: "Run `npm run build`; fix every error before continuing" beats "ensure the build works". Give the reason for a rule that is not obvious, in one clause. Write the body in English (models follow it more reliably) and keep the user's language for the trigger words in the description. Use relative paths; never include secrets, tokens, user names or paths from this machine.

## 3. Extra files (`files` field)
Long or reusable material goes in files that a later run opens only when a phase needs it:
- `references/*.md`: formulas, data tables, specifications, API notes (for example damage formulas, stat tables, a palette).
- `templates/*`: starter files to copy into a project (configs, an index.html, a minimal main file).
- `scripts/*`: helpers that do deterministic work (scaffold, self-test, check).
- `examples/*`: one good input and output.

Only include templates and scripts that ran and worked in this conversation. In the procedure, name the file at the step that uses it, for example: "Phase 1: copy the configs with `read_skill name=<skill> resource=templates/vite.config.ts copy_to=vite.config.ts`". `copy_to` writes the file straight into the project without passing it through the conversation, so a template costs no context. Use `read_skill` with only `resource` to read a reference.

## 4. The description (it decides when the skill loads)
Say what the skill does and when to use it, with the concrete words a user would type: the domain, the stack, the file types, and the same words in the user's language. 1 to 1024 characters. Not "A skill for X".

## 5. Check, then create
Answer yes to all before calling the tool:
- Could a run that never saw this conversation follow it from the first step to "done"?
- Does every phase end with a command that proves it worked?
- Are the errors and fixes from this conversation in the pitfalls?
- Is it a procedure (verbs, commands, checkpoints), not a list of features?
- Is every extra file named at the step that uses it?

Call `create_skill` once with `name`, `description`, `instructions` and `files` (and `replace: true` for a new version of your own skill). If it returns an error, fix what it names and call again; never repeat the same call unchanged. Then read the skill back with `read_skill` to check it, and tell the user its name, what it covers, its files, and that it is used automatically or with `@name`.
