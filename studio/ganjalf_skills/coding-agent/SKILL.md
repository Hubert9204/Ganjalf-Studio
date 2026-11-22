---
name: coding-agent
description: Create, write or fix code in a project folder. Build programs, games, apps, websites and scripts, explore files, read large files in chunks, fix bugs and compile errors, run and verify the result. Use for coding, debugging, refactoring, crashes and broken builds. Italiano - crea, creami, scrivi, sviluppa un gioco, un programma, un sito web, un'applicazione, uno script; codice, errore, bug, correggere, compilare, cartella, progetto, file di sorgente.
---

# Coding agent

Use this when the task is about code, a project folder, a failing build, a crash or a bug, or when asked to build a program, game, app or script.

## Choosing the approach
- Look at what is already installed before choosing a stack (`python3 -c "import X"`, `node --version`).
- If no stack is named, prefer a result with no dependencies (a game or small tool can be one HTML file with a canvas). Try to install a missing package at most once; if it fails, switch approach instead of retrying, and tell the user why.

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

## Writing and checking new code
- Write the file once, then run or open it and fix what breaks. Do not rewrite a working file wholesale to make it "more robust"; change the lines that are wrong.
- To check something visual (a canvas, a window, a web page) take a real screenshot, or run it and read the console errors. A page snapshot, or a process that merely starts, proves little.
- Try at least one real input (a key press, a click, a command) and say what you saw.
- If you start a server or any background process, stop it when you are done, or tell the user it is still running and how to stop it.
- Report only what you verified, and say plainly what you did not test.

## Packaged apps
If an AppImage, installer or container misbehaves, run the plain binary or script first. If that works, the bug is in the packaging; if not, it is in the code. For OpenGL, check the shader compile logs, glGetError and the number of vertices passed to the draw call.

## Staying on task
- Do not open skills or run web research that have nothing to do with the code at hand.
- Keep a short checklist of the steps and tick them off.
- Finish with: what was wrong or what was built, which files and lines changed, how you verified it, what is still open.
