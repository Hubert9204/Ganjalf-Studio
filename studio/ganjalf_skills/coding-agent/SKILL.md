---
name: coding-agent
description: Create, write or fix code in a project folder. Build programs, games, apps, websites and scripts, explore files, read large files in chunks, fix bugs and compile errors, run and verify the result. Use for coding, debugging, refactoring, crashes and broken builds. Italiano - crea, creami, scrivi, sviluppa un gioco, un programma, un sito web, un'applicazione, uno script; codice, errore, bug, correggere, compilare, cartella, progetto, file di sorgente.
---

# Coding agent

Use this for code in a project folder: building a program, game, app or script, or fixing a bug, a failing build or a crash.

## Your limits here
- Tool calls per message may be capped (in Ganjalf there is no cap unless the user sets one; a run stops after 8 failed calls in a row). Spend at most 4 on checking the environment, put several commands in one call (`a && b && c`), and keep calls in reserve for testing and fixes. With a cap, when about 10 calls are left, stop adding features: run what exists and write the summary (what works, what fails, the next step). The user continues with a new message.
- Tool calls run in a sandbox unless the user turned it off. System folders are read-only and there is no root, so `sudo`, `dnf install` and `apt install` cannot work: do not try them. There is no GPU and no screen, so a window or OpenGL program cannot be run or seen. A background process dies when its call ends unless started as `nohup CMD > out.log 2>&1 &`, and `/tmp` is emptied after each call.
- `pip install` works and lands in the project folder. For a missing C or C++ library, use what is installed, put a single-header library in the project, or use the standard library only. If a system package is really needed, give the user the exact command and carry on with a fallback.

## Choosing the approach
- Look at what is installed before choosing a stack (`python3 -c "import X"`, `g++ --version`, `node --version`).
- With no stack named, prefer no dependencies. For a game, keep the rules and state apart from the drawing, so the rules can be tested without a screen.
- Try to install a missing package at most once; if it fails, switch approach and say why.

## Reading files without flooding the context
- Never `cat` a file you have not measured. Run `wc -l FILE` first, find the place with `grep -n "word" FILE`, then read only that part with `sed -n 'START,ENDp' FILE`, 80 to 150 lines at a time.
- If a result says the output is too large or truncated, do not repeat the same command. Narrow the range or the pattern.
- List the project folder and read the README or build file first (Makefile, package.json, pyproject.toml, CMakeLists.txt). Do not open every file.

## Writing and changing code
- Build a large project in slices: first the smallest version that runs (for a game: one scene, the player, one enemy, the HUD), run and check it, then add one system at a time and check again. Never write a dozen files before running anything: the errors pile up and the calls run out before anything works.
- Install all packages in one command (`npm install three && npm install -D typescript vite @types/three`), then call their tools as `npx tsc` or `npx vite`.
- Create a new file with `edit_file` and an empty `old_string`. Never write source code through `python3 -c`, `sed` or a heredoc inside another script: quoting breaks and the file comes out empty or cut.
- Write each file once, compile or run it, then fix what breaks. Fix every error the compiler printed in one edit, not one per call. Do not rewrite a working file to make it "more robust".
- Once a file exists, change it with `edit_file` (not `sed -i` or a Python regex, which silently miss or hit the wrong line), not by writing it again whole: every full rewrite of a 30 KB file costs about 8k tokens of context, and a few of them fill the window.
- Do not switch language or layout halfway (TypeScript to JavaScript, many files to one file) to get around an error. Fix the error; if a tool itself fails (a build runs out of memory, a command crashes), tell the user the exact error before changing the design.
- Before editing a bug, say in one sentence what is wrong and which line shows it. Change only those lines, rerun, and compare with the output from before.
- If the same approach fails twice, switch: a smaller step, another tool, or one precise question to the user.

## Checking the result
- Add a headless test path: a flag such as `--selftest` that runs a few hundred steps with scripted input and prints the state (positions, health, score). Use it instead of driving an interactive terminal or window with scripts, which costs many calls and proves little.
- A page snapshot, or a program that merely starts, proves little. For a web page take a real screenshot and read the console errors.
- Try one real input and say what you saw. Say plainly what you could not test (graphics, controls, feel).
- Delete the scratch files and logs you made, and stop any server you started, or tell the user it is still running.

## Web pages and browser games
- Check a page with `check_page` when you have it: it runs the file in a headless browser on the server, as from a web server (modules, import maps and sibling files load), and returns its JavaScript errors, failed requests, visible text and a screenshot. Pass `keys` (e.g. `["Enter"]`) to start a game or test its controls. Run it after every change, before you say the page works.
- Without `check_page`, use the browser panel: `browser_navigate` with a file path loads that one file only, so for a page made of several files start a static server (`nohup python3 -m http.server 8080 > server.log 2>&1 &`) and open `http://localhost:8080/`. Snapshots list the page's errors since it loaded. If Ganjalf runs inside Docker that address does not reach the panel: inline the scripts into one HTML file.
- No bundler is needed: `<script type="module">` with relative imports works. For an npm package add an import map, e.g. `"three": "./node_modules/three/build/three.module.js"` (recent three.js has no `three.min.js`).
- A black canvas, a one-color screenshot or a HUD showing 0/0 means the script stopped: read the first error, fix that line, check again. Do not start over.
- If you could not run the page or cannot read images, say the picture is unchecked.

## Packaged apps
If an AppImage, installer or container misbehaves, run the plain binary or script first. If that works, the bug is in the packaging; if not, it is in the code. For OpenGL, check the shader compile logs, glGetError and the number of vertices passed to the draw call.

## Staying on task
- Do not open unrelated skills or run web research for a code problem.
- Finish with: what was wrong or what was built, which files and lines changed, how you verified it, what is still open.
