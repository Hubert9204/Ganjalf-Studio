---
name: git-workflow
description: Commit, branch, push and open pull requests with git and gh the careful way - read the changes first, write a clear commit message, never force or skip hooks, ask before anything others see. Italiano - fai un commit, salva su git, crea un branch, apri una pull request, push, conflitto di merge.
allowed-tools: terminal read_file grep glob edit_file
---

# Git: commit, branch, pull request

Work in the project folder with `terminal`. Pushing and opening a pull request show your work to other people, so Ganjalf asks the user before those commands run: that is expected, not an error.

## Commit
1. Look before you write, in one call: `git status --short && git diff --stat && git diff --cached --stat && git log -5 --oneline`. Read the actual diff of anything you did not write yourself in this chat (`git diff -- <file>`).
2. Stage on purpose: `git add <the files of this change>`. Not `git add -A` unless every changed file belongs to it. Never stage secrets (`.env`, keys, tokens, credentials) or build output (`dist/`, `node_modules/`): if one is not ignored, say so and add it to `.gitignore` instead.
3. Message in the style of `git log`: a summary line under 72 characters in the imperative ("Add the inventory window"), then, when the change is not obvious, a body that says **why**. Commit with `git commit -m "summary" -m "body"` (no heredocs, no editor).
4. Check: `git status --short` and `git log -1 --stat`. Report the commit hash and summary to the user.

## Branch
- Asked for a pull request while on `main`/`master`: create a branch first, `git switch -c <short-topic>` (kebab-case, what the change does).
- Never rewrite history the user did not ask to rewrite: no `git reset --hard`, `git push --force`, `git rebase` of pushed commits, `git commit --amend` of a pushed commit.

## Push and pull request
1. `git push -u origin <branch>` (the user approves it).
2. With `gh` installed and signed in (`gh auth status`): `gh pr create --title "<summary>" --body "<what changed, why, how it was checked>"`. Give the user the URL it prints. Without `gh`, give the user the compare link that `git push` printed.

## When something fails
- A pre-commit hook fails: read its output, fix the cause, stage again and make a **new** commit. Never `--no-verify`.
- A merge or pull conflict: `git status` lists the files; open each, resolve the `<<<<<<<` blocks with `edit_file` keeping both sides' intent, run the project's checks, then `git add` the files and `git commit`.
- Not a git repository: say so; run `git init` only if the user asks.
- Do not change `git config` (name, email, remotes) unless the user asks.
