# Plugin (formato Claude Code)

Ganjalf installa i plugin di Claude Code: pacchetti che raccolgono skill, comandi, agenti, hook e
server MCP. Si gestiscono da **Skills → Plugin** nella chat.

## Installare

Nel campo in alto si scrive da dove prenderlo, poi **Guarda dentro**:

| Sorgente | Esempio |
|---|---|
| repository GitHub | `owner/repo`, `owner/repo/cartella@ramo`, `https://github.com/owner/repo/tree/main/cartella` |
| altro git | `https://gitlab.com/owner/repo.git` (serve `git`) |
| archivio | `https://…/plugin.zip`, oppure il pulsante di caricamento (zip o tar fino a 50 MB) |
| cartella su questo computer | `/percorso/del/plugin` |
| marketplace aggiunto | `nome-plugin@nome-marketplace` |

Prima di installare, Ganjalf mostra cosa contiene il plugin: skill, comandi, agenti, server MCP e
**tutti i comandi che eseguirà su questo computer** (hook e server MCP locali), più le parti che non
usa. Se l'indirizzo è un marketplace (`.claude-plugin/marketplace.json`), propone di aggiungerlo e
ne elenca i plugin. Un repository privato su GitHub richiede `GITHUB_TOKEN` nell'ambiente di Studio.

I plugin si gestiscono solo dalla finestra di Studio dell'account proprietario: le chiavi API e gli
account gestiti non possono installarli.

## Cosa diventa ogni parte

| Parte del plugin | In Ganjalf |
|---|---|
| `skills/<nome>/SKILL.md` | skill `<plugin>-<nome>` (solo `<plugin>` se i nomi coincidono), nella sezione *Dai plugin* della finestra Skills |
| `commands/*.md` | skill `<plugin>-<comando>`: si chiama scrivendo `/<plugin>-<comando> argomenti` all'inizio del messaggio, o con `@` |
| `agents/*.md` | il tool `run_agent`, offerto con gli strumenti di codice quando è caricato un modello GGUF |
| `hooks/hooks.json` | eseguiti solo dopo averli attivati con l'interruttore **Hook** del plugin |
| `.mcp.json` | righe nell'elenco dei server MCP, con nome `<plugin> · <server>` |
| `bin/` | i programmi finiscono nel PATH del terminale finché il plugin è acceso, in coda (non sostituiscono mai un comando di sistema); nella sandbox la cartella del plugin è montata in sola lettura |
| `output-styles/*.md` | stili di risposta: si sceglie quello attivo in fondo alla finestra Plugin; il testo entra nelle istruzioni delle chat con gli strumenti (`keep-coding-instructions: true` tiene anche le istruzioni di codice) |
| `monitors/monitors.json` | comandi in background per tutta la chat (`when: always`) o dal primo uso di una skill (`on-skill-invoke:<skill>`); girano come processi della chat (pannello in alto, `terminal_output`), **solo con l'interruttore Hook acceso**, perché eseguono comandi come gli hook |
| `.lsp.json`, temi, workflow, `userConfig` | elencati come non usati: temi e workflow appartengono al terminale e al motore JavaScript di Claude Code |

`${CLAUDE_PLUGIN_ROOT}` e `${CLAUDE_PLUGIN_DATA}` vengono sostituiti nelle skill, nei comandi, negli
agenti, negli hook e nei server MCP; `${VAR}` e `${VAR:-predefinito}` nei server MCP vengono presi
dall'ambiente in cui gira Studio.

Disattivare un plugin toglie le sue skill e i suoi comandi, spegne i suoi server MCP, i suoi hook e
i suoi agenti. Rimuoverlo cancella anche i file e la cartella dati. **Aggiorna** lo riscarica dalla
stessa sorgente (per i plugin da GitHub l'interfaccia segnala quando il ramo è cambiato) e conserva
le scelte fatte.

## Hook

Stesso contratto di Claude Code: l'evento arriva come JSON sullo standard input, il comando gira
nella cartella di lavoro della chat con `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA` e
`CLAUDE_PROJECT_DIR` nell'ambiente, timeout 60 s salvo diversa indicazione.

| Evento | Quando | Effetto |
|---|---|---|
| `PreToolUse` | prima di ogni tool | uscita 2, `decision: block` o `permissionDecision: deny` bloccano la chiamata; il modello riceve il motivo |
| `PostToolUse` | dopo ogni tool | `additionalContext` o un blocco vengono aggiunti al risultato del tool |
| `UserPromptSubmit` | prima di generare | lo stdout entra nel prompt di sistema; un blocco chiede al modello di non eseguire la richiesta e spiegare perché |
| `SessionStart` | al primo messaggio di una chat | lo stdout entra nel prompt di sistema |
| `Stop` | quando l'agente sta per finire (modelli GGUF) | un blocco lo rimanda al lavoro con il motivo, al massimo 3 volte |
| `SubagentStop` | quando un agente di `run_agent` finisce | informativo: riceve `agent_type` e il resoconto |
| `PreCompact` | prima che i turni vecchi escano dal contesto (`matcher`: `auto` o `manual` per `/compact`) | informativo, in background |
| `Notification` | quando serve un permesso (`permission_prompt`) o il lavoro è finito (`idle_prompt`) | informativo, in background: utile per avvisi sul telefono |
| `SessionEnd` | quando cancelli una chat (`reason: clear`) | informativo, prima che la cartella della chat sparisca |

I tool di Studio vengono presentati agli hook con i nomi di Claude Code: `terminal` → `Bash`,
`edit_file` → `Edit`/`MultiEdit`/`Write`, `view_image` → `Read`, `web_search` → `WebSearch`; i
matcher (`Edit|Write`) e le condizioni `if` (`Bash(git commit*)`) funzionano senza modifiche. Gli
hook asincroni (`async`, `asyncRewake`) e quelli non di tipo `command` vengono saltati.

Ogni hook gira in un proprio gruppo di processi: allo **Stop** della chat (o alla disconnessione del
client) viene ucciso subito, gli hook successivi non partono e la chiamata tool non viene eseguita.

## Agenti

`run_agent` affida un compito a un agente di un plugin: il suo file Markdown diventa il prompt di
sistema e la riga `tools` sceglie gli strumenti (`Bash`, `Read`, `Grep`, `Glob` → `terminal` e
`python`; `Edit`, `Write` → `edit_file`; `WebSearch`, `WebFetch` → `web_search`). L'agente lavora in
una conversazione separata sul modello GGUF già caricato, nella stessa cartella e con la stessa
sandbox della chat, per al massimo 25 passaggi o 20 minuti; alla chat torna solo il suo rapporto
finale, così le ricerche lunghe non riempiono il contesto. Le sue chiamate ai tool non chiedono
conferma: approvare `run_agent` approva il suo lavoro. Le risposte del modello arrivano in streaming:
allo **Stop** la connessione si chiude, llama-server smette di generare e `run_agent` ritorna subito.

La conversazione dell'agente ha un budget suo: circa tre quarti della finestra del modello (in
caratteri, ~3 per token; `GANJALF_AGENT_CONTEXT_CHARS` per fissarlo). Quando lo supera, i risultati
dei tool più vecchi diventano una riga di riassunto; prompt, compito e gli ultimi due risultati
restano interi. Ogni risultato è tagliato a 6.000 caratteri tenendo inizio e fine (dove un log
mette gli errori), e il rapporto che torna alla chat a 12.000.

## Dove stanno i file

`~/.ganjalf-studio/plugins/` (in Docker `/opt/unsloth-studio/plugins/`):
`registry.json`, `installed/<plugin>/`, `data/<plugin>/`, `skills/` (generata),
`marketplaces/<nome>/`. `GANJALF_PLUGINS_HOME` sposta la cartella.

Codice: `studio/backend/core/plugins/` (`fetch.py`, `inspect.py`, `manager.py`, `hooks.py`,
`agents.py`), API in `routes/plugins.py`, interfaccia in
`studio/frontend/src/features/chat/components/plugins-dialog.tsx`.
