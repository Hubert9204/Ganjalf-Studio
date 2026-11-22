---
name: coding-agent
description: Work on code in a project folder. Explore files, read large files in chunks, fix bugs and compile errors, edit source code, build, run programs and verify the result. Use for debugging, programming, scripts, refactoring, crashes and broken builds. Italiano - codice, programma, errore, bug, correggere, compilare, progetto, file di sorgente.
---

# Coding agent

Use this when the task is about code, a project folder, a failing build, a crash or a bug.

## Before touching anything
1. List the project folder and read the README or the build file (Makefile, package.json, pyproject.toml, CMakeLists.txt). Do not open every file.
2. Reproduce the problem first. Run the program, the build or the tests and keep the output short with `| head -40` or `| tail -40`. Quote the exact error text.

## Reading files without flooding the context
- Never `cat` a file you have not measured. Run `wc -l FILE` first.
- Find the place with `grep -n "word" FILE`, then read only that part with `sed -n 'START,ENDp' FILE`, 80 to 150 lines at a time.
- If a result says the output is too large or truncated, do not repeat the same command. Narrow the range or the pattern.

## Changing code
- Say in one sentence what you think is wrong and which line shows it, before editing.
- Change as little as possible. Edit the specific lines instead of rewriting a whole file.
- Rebuild or rerun after every change and compare with the earlier output.
- If the same approach fails twice, switch: a smaller step, a different tool, or one precise question to the user.

## Packaged apps
If an AppImage, installer or container misbehaves, run the plain binary or script first. If that works, the bug is in the packaging; if not, it is in the code. For OpenGL, check the shader compile logs, glGetError and the number of vertices passed to the draw call.

## Staying on task
- Do not open skills or run web research that have nothing to do with the code at hand.
- Keep a short checklist of the steps and tick them off.
- Finish with: what was wrong, which files and lines changed, how you verified it, what is still open.
