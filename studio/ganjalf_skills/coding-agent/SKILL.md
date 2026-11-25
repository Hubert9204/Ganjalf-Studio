---
name: coding-agent
description: Create, write or fix code in a project folder. Build programs, games, apps, websites and scripts, explore files, read large files in chunks, fix bugs and compile errors, run and verify the result. Use for coding, debugging, refactoring, crashes and broken builds. Italiano - crea, creami, scrivi, sviluppa un gioco, un programma, un sito web, un'applicazione, uno script; codice, errore, bug, correggere, compilare, cartella, progetto, file di sorgente.
---

# Coding agent

Use this for code in a project folder: building a program, game, app or script, or fixing a bug, a failing build or a crash. Work like Claude Code: plan, build in small verified steps, run and check the result yourself, and finish with something that runs. The user may not be a programmer: never leave them a command to type to make your work run.

## Plan first
- For anything with 3 or more steps, call `todo_write` before writing code: small steps, each ending in something you can run or check (for a game: "Scene, player and one enemy, compiles and renders", then "Camera", "Combat", "HUD", ...). The user sees the list.
- Keep exactly one item `in_progress`. Mark an item `completed` as soon as its check passes, and add items you discover. Do not mark an item done if its check failed.

## Your limits here
- Tool calls per message may be capped (in Ganjalf there is no cap unless the user sets one; a run stops after 8 failed calls in a row). Spend at most 4 on checking the environment and put several commands in one call (`a && b && c`). With a cap, when about 10 calls are left, stop adding features: run what exists and write the summary.
- Tool calls run in a sandbox unless the user turned it off. System folders are read-only and there is no root, so `sudo`, `dnf install` and `apt install` cannot work: do not try them. There is no GPU and no screen. `/tmp` is emptied after each call.
- A process started with `&` or `nohup` dies when its call ends. For a dev server, a watcher or a long build use `terminal` with `run_in_background: true`: it returns a job id; read its output with `terminal_output` and stop it with `terminal_kill`.
- `pip install` works and lands in the project folder. For a missing C or C++ library, use what is installed, put a single-header library in the project, or use the standard library only.
- An existing project whose build needs a system package that is missing (a CMake `find_package` error, a missing `-devel` header): do not fake the package (no hand-written headers or `*Config.cmake`), do not edit its build files around it, and do not delete its build folder or `_deps`. Check what you can without the full build (`g++ -fsyntax-only` with the project's flags), then tell the user the exact install command (e.g. `sudo dnf install libcurl-devel`) and stop.
- Work only in the project folder you were given. If it is empty or missing, say so and stop: never search the disk for another copy of the project and change that one.
- Heavy builds share the machine with the model: use at most half the cores (`make -j4`, `ninja -j4` on 8 or more).
- C/C++ with a big library (JUCE, Qt, Boost): before using a class method, `grep` its header (e.g. in `build/_deps/juce-src/modules`) for the exact name and signature; do not trust memory. To check one file without the full build, take its flags from `build/compile_commands.json` (configure with `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`) and add `-fsyntax-only`.

## Choosing the approach
- Look at what is installed before choosing a stack (`python3 -c "import X"`, `g++ --version`, `node --version`).
- With no stack named, prefer the fewest moving parts. For a game, keep the rules and state apart from the drawing, so the rules can be tested without a screen.
- Try to install a missing package at most once; if it fails, switch approach and say why.

## Reading and searching
- Use `glob` to see the project's files, `grep` to find where something is defined or used, and `read_file` with `offset`/`limit` to read the part you need. Do not use `cat`, `sed -n`, `head` or `ls -R` in the terminal for this.
- Read the README or build file first (package.json, Makefile, pyproject.toml). Do not open every file.
- If a result is truncated, narrow the range or the pattern; do not repeat the same call.
- In a large project, give a survey ("where is X handled", "how do these modules connect") to `run_agent` with agent `explore`: it reads on its own and returns only the answer with paths and lines, so your context stays small. Use `general-purpose` for a separate piece of work with its own check.
- Several independent surveys at once: `run_agent` with `tasks` (up to 4, e.g. one `explore` per folder). With `run_in_background: true` the agents keep working while you do; read their reports with `terminal_output`.
- If the project has an AGENTS.md (or CLAUDE.md), it is already in your instructions: follow its commands. To commit or open a pull request, follow the git-workflow skill.

## Writing and changing code
- Follow the plan: the first step is the smallest version that runs, at most 4 source files; compile and check it before the next step. Never write a dozen files before running anything.
- Keep every file under about 400 lines: split a growing "engine" or "HUD" into modules. A 40 KB file costs about 10k tokens each time it is written and makes every error slow to find.
- Install all packages in one command (`npm install three && npm install -D typescript vite @types/three`), then call their tools as `npx tsc` or `npx vite`.
- Create a new file with `edit_file` and an empty `old_string`. Never write source code through `python3 -c`, `sed` or a heredoc: quoting breaks and the file comes out empty or cut.
- After a compile, fix every error in a file with one `edit_file` call holding several edits, not one call per error. Do not rewrite a working file to make it "more robust".
- Change existing files with `edit_file` (never `sed -i` or a Python regex, which silently miss or hit the wrong line), not by writing them again whole.
- Do not switch language or layout halfway (TypeScript to JavaScript, many files to one file) to get around an error. Fix the error; if a tool itself fails, say the exact error before changing the design.
- Before editing a bug, say in one sentence what is wrong and which line shows it. Change only those lines, rerun, compare.
- If the same approach fails twice, switch: a smaller step, another tool, or one precise question to the user.

## Checking the result
- Every plan item ends with a check you ran: a compile, a test, the program's output, or `check_page` for a page. A program that merely starts proves little.
- Add a headless test path for logic: a flag such as `--selftest` that runs a few hundred steps with scripted input and prints the state. Use it instead of driving an interactive terminal or window.
- Try one real input and say what you saw. Say plainly what you could not test (feel, sound, a window on the user's screen).
- Stop only what you started: background jobs with `terminal_kill`. Never `pkill -f node`, `pkill -f python` or `killall`: they kill the user's other programs. Delete scratch files and logs you made.

## Web pages and browser games
- `check_page` runs a page in a headless browser on the server and returns its JavaScript errors, failed requests, visible text and a screenshot; `keys` (e.g. `["Enter"]`) starts a game or tests its controls. Run it after every change, before you say the page works.
- To prove a control works, do not judge from the screenshot: expose the state on `window` (e.g. `window.game = game`), then `check_page` with `keys: ["w"]`, `hold_ms: 800` and `evaluate: "window.game.player.position"`, and compare with a run without the key.
- Test what the user will use, not only the API: curl proves the server, not the page. For every form or button of the task, `check_page` with `evaluate` that fills the fields, clicks, waits and reads the result (`document.querySelector('#amount').value='50'; document.querySelector('#save').click(); await new Promise(r => setTimeout(r, 500)); document.querySelector('#list').innerText`). A `failed: ...` there is a bug to fix.
- With a bundler (Vite, TypeScript): `npx tsc --noEmit`, `npm run build`, then `check_page dist/index.html`. When everything works, start the dev server with `terminal` `run_in_background: true` (`npx vite --host 0.0.0.0 --port 5173`), read the address with `terminal_output`, check `http://localhost:5173` with `check_page`, and leave it running so the user can open it.
- Without a bundler: `<script type="module">` with relative imports works; for an npm package add an import map, e.g. `"three": "./node_modules/three/build/three.module.js"` (recent three.js has no `three.min.js`). Serve it the same way (`python3 -m http.server 8080` in the background).
- A page with modules does not open from a double-click (`file://`). If the user wants a file to double-click, build a single file: `npm install -D vite-plugin-singlefile`, add `viteSingleFile()` to the plugins in `vite.config.ts`, `npm run build`; `dist/index.html` then opens from `file://`. Check it with `check_page dist/index.html`.
- The browser panel opens public sites only, never `localhost`: use `check_page` for local pages.
- Never hand-patch a built or minified file (`dist/`, `*.min.js`, a bundle): change the source and rebuild. Never point the source `index.html` at a built bundle.
- When the user says "it does not work", read the exact error and address in their message or screenshot first. A `file://` address is a way-of-opening problem: give them the running address or the single-file build, not a restructured project.
- A black canvas, a one-color screenshot or a HUD showing 0/0 means the script stopped: read the first error, fix that line, check again. Do not start over.

## Packaged apps
If an AppImage, installer or container misbehaves, run the plain binary or script first. If that works, the bug is in the packaging; if not, it is in the code.

## Finishing
- Do not open unrelated skills or run web research for a code problem.
- End with a short report: what was built or fixed, how you verified it (which checks passed), where it runs now (the address of the server you left running, or the file to open), and what is still open. No homework for the user: if something must run for it to work, you run it.
