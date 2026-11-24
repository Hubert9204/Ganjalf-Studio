<p align="center">
  <img alt="Ganjalf Studio" src="images/ganjalf-banner.svg" width="100%" />
</p>

<h3 align="center">Ganjalf Studio: un fork di Unsloth Studio per far lavorare i modelli locali come agenti, con skill <code>SKILL.md</code>, plugin di Claude Code, un'API compatibile con Claude e una nuova veste grafica.</h3>

<p align="center">
  <a href="#-novità">Novità</a> •
  <a href="#-le-skill">Skill</a> •
  <a href="#-avvio-e-aggiornamento">Avvio</a> •
  <a href="#-impostazioni-consigliate">Impostazioni</a> •
  <a href="#-documentazione">Documentazione</a> •
  <a href="#-licenza-e-crediti">Licenza</a>
</p>

> **Progetto non ufficiale.** Ganjalf Studio è un fork indipendente di [Unsloth](https://github.com/unslothai/unsloth) e non è affiliato a Unsloth AI. Per documentazione, modelli e supporto del progetto originale vedi [unsloth.ai/docs](https://unsloth.ai/docs).

## ✨ Novità

**Agente sui modelli locali**
- **Protocollo agentico**: con i tool attivi, Ganjalf mette in testa al prompt un metodo di lavoro (pianificare, chiamare i tool correttamente, non inventare risultati, gestire gli errori, verificare prima di dire "fatto"), con note specifiche per Qwen, Nemotron e Gemma. Dettagli in [studio/ganjalf_prompts/README.md](studio/ganjalf_prompts/README.md).
- **Nessun tetto alle chiamate**: *Max Tool Calls Per Message* parte da "Max". Un lavoro lungo si ferma al contesto (finestra scorrevole o compattazione) oppure quando le ultime 8 chiamate di fila falliscono: il modello deve allora riportare l'errore esatto, cosa funziona e il passo successivo (`GANJALF_TOOL_FAILURE_STREAK`, `0` lo disattiva).
- **Thinking Budget**: un cursore nelle impostazioni della chat limita i token di ragionamento dei modelli locali (Auto lascia quello del modello).
- **Sotto-agenti, piano e processi**: `run_agent` ha sempre due agenti di serie, `explore` (solo lettura: cerca nel progetto e risponde con file e righe, senza chiedere conferma) e `general-purpose` (tutti gli strumenti), oltre a quelli dei plugin; lavorano in una conversazione separata e restituiscono solo il resoconto. La pillola **Plan** accanto a Tools attiva la modalità piano: il modello esplora in sola lettura, presenta il piano in una card con "Approva e procedi" e non tocca i file finché non approvi. I server lasciati accesi dal modello compaiono in alto nella chat (icona del terminale) con il loro indirizzo e un pulsante per fermarli.
- **Claude Code sul modello locale**: `unsloth start claude` avvia il vero Claude Code puntato su Ganjalf. Dettagli in [studio/CLAUDE_API.md](studio/CLAUDE_API.md#usare-claude-code-con-il-modello-locale).
- **Strumenti come Claude Code**: insieme al terminale il modello ha `todo_write` (il piano di lavoro, mostrato in chat come checklist che si spunta), `read_file` (righe numerate a intervalli), `grep` e `glob` (cerca nel codice ed elenca i file, saltando `node_modules`, `.git`, `dist`) e i processi in background: `terminal` con `run_in_background` avvia un dev server o un watcher che resta acceso dopo la chiamata (nella sandbox `&` e `nohup` muoiono con la chiamata), `terminal_output` ne legge l'output e `terminal_kill` lo ferma. Alla fine il modello lascia il risultato funzionante (es. il server acceso con il suo indirizzo) invece di dare comandi da eseguire. `GANJALF_AGENT_TOOLS=0` li toglie, `GANJALF_BACKGROUND_TIMEOUT` (default 4 ore) limita i job.
- **Guardrail morbidi**: dopo 6 scritture di file di fila senza eseguire niente, il modello riceve una nota che gli chiede di provare quello che ha scritto (build, test, script) se si può (`GANJALF_VERIFY_AFTER_WRITES`, `0` la disattiva). Se ha modificato pagine web (HTML/CSS, o JS/TS accanto a un HTML) e sta per chiudere senza aver lanciato `check_page`, viene rimandato una sola volta a controllare la pagina (`GANJALF_CHECK_PAGE_GATE=0` lo disattiva). Nessuno dei due blocca: se il controllo non è possibile, il modello lo dice e chiude.
- **Log di build leggibili**: quando l'output di `terminal` o `python` è troppo lungo, oltre all'inizio il modello vede le righe d'errore della parte tagliata e le ultime righe; npm non stampa più barre di avanzamento, colori e avvisi di fund/audit.
- **Istruzioni fissate nel contesto**: quando la finestra di contesto scorre, le ultime due istruzioni dell'utente restano nel prompt, così il modello non perde il compito a metà lavoro.
- **Il modello vede le pagine che crea**: il tool `check_page` apre una pagina o un gioco della cartella di lavoro in un Chromium senza finestra sul server (anche in Docker, anche a chat chiusa) e restituisce errori JavaScript, richieste fallite, testo visibile e uno screenshot; può premere tasti per avviare un gioco. Nel pannello browser della chat le letture riportano gli errori della pagina dal caricamento in poi, e `browser_screenshot` funziona anche nella versione web (canvas e WebGL compresi). Dettagli in [studio/PAGE_CHECK.md](studio/PAGE_CHECK.md).
- **Limite di memoria dei tool più realistico (Linux)**: conta la memoria usata davvero, così `node`, `vite build` e WebAssembly girano nella sandbox.

**Skill e plugin**
- **Skill di serie**: al primo avvio `coding-agent` (lavoro sul codice: leggere i file grandi a pezzi, costruire a fette, correggere con `edit_file`, verificare), `web-research` e `data-analysis` vengono copiate tra le tue skill, e `skill-creator` viene attivata.
- **Skill scritte dal modello**: `skill-creator` insegna al modello a scrivere procedure (fasi con comandi e verifiche, errori incontrati e correzioni, criterio di "finito") invece di descrizioni del progetto. `create_skill` accetta file aggiuntivi (`references/`, `templates/`, `scripts/`, `examples/`) e può pubblicare una nuova versione di una skill scritta dal modello stesso (`replace`; la precedente resta in `.ganjalf-skill-history`, le skill tue o importate non vengono mai toccate). `read_skill` con `copy_to` copia un template nel progetto senza farlo passare dal contesto.
- **Skill scelta dal motore**: se la richiesta corrisponde chiaramente a una skill attiva, il backend ne carica le istruzioni prima di generare, come se l'avessi nominata con `@`.
- **Import delle skill**: un singolo `SKILL.md`, più file insieme, una cartella trascinata sulla lista o un archivio ZIP.
- **Plugin di Claude Code**: da *Skills → Plugin* installi plugin da GitHub, URL, zip, cartella o marketplace, dopo aver visto cosa contengono e quali comandi eseguono. Skill e comandi (`/plugin-comando`) diventano skill, i server MCP si aggiungono all'elenco, gli hook (`PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`, `Stop`) partono solo dopo che li attivi, e gli agenti sono a disposizione del modello con il tool `run_agent`. Dettagli in [studio/PLUGINS.md](studio/PLUGINS.md).

**API e motore**
- **API compatibile con Claude**: `/v1/messages` segue l'API Messages di Anthropic (thinking, tool use in streaming, immagini, documenti, errori, `count_tokens`), con l'evento `ping`, l'intestazione `request-id`, `/v1/models` nel formato Anthropic quando il client manda `anthropic-version`, e lo Stop che ferma anche i cicli agente, gli hook e i sotto-agenti. Stato, gestione del contesto e limiti in [studio/CLAUDE_API.md](studio/CLAUDE_API.md).
- **Offload nel training**: l'opzione *Offload layers* parte su Auto e sposta in RAM solo i layer che non entrano in VRAM. Dettagli in [studio/TRAINING_OFFLOAD.md](studio/TRAINING_OFFLOAD.md).
- **Aggiornamenti da questo repository**: l'interfaccia avvisa quando `main` ha commit nuovi; nessun percorso di aggiornamento installa più il pacchetto Unsloth da PyPI senza chiederlo. Dettagli in [studio/GANJALF_UPDATES.md](studio/GANJALF_UPDATES.md).

**Aspetto**
- **Tema e identità Ganjalf**: palette grigio-argento con accento blu freddo (chiara e scura), mascotte con cappello blu e pipa grigia, logo in barra laterale, icona e titolo della scheda. Le palette con nome di Unsloth restano disponibili.
- **Animazione di lavoro**: mentre il modello pensa, scrive o lavora da agente compare un libro che si sfoglia accanto a una pipa che fuma, al posto dello spinner.

**Tutto il resto di Unsloth Studio**: esecuzione e addestramento di modelli, chat, agenti e strumenti, API compatibile con OpenAI, RAG e ricerca.

## 📜 Le skill

Una skill è una cartella con un file `SKILL.md`: un blocco YAML iniziale con `name` e `description`, poi le istruzioni in Markdown.

```markdown
---
name: revisore-codice
description: Rivede una modifica e segnala bug, test mancanti e problemi di stile.
---
Quando l'utente chiede una revisione, leggi prima il diff e poi…
```

- **Dove vivono**: di default in `~/.agents/skills`; la cartella si cambia con la variabile `UNSLOTH_STUDIO_SKILLS_HOME`. Studio legge anche `~/.claude/skills`, le skill dei plugin installati e alcune skill incluse.
- **Come le conosce il modello**: nel prompt entra un catalogo con nome e descrizione delle skill attive. Il testo completo si carica quando scrivi `@nome-skill` (o `/nome` all'inizio del messaggio, per i comandi dei plugin), quando il modello lo richiede, oppure quando il motore riconosce che la richiesta corrisponde a una skill.
- **Scelta automatica**: il motore confronta la richiesta con nome e descrizione di ogni skill attiva (sovrapposizione di termini, senza modelli né rete) e carica una sola skill, solo se batte nettamente le altre e condivide almeno tre termini con la richiesta. Scrivi la descrizione con le parole che userebbe chi ha bisogno di quella skill, anche in italiano. Si spegne con `GANJALF_AUTO_SKILLS=0`; una skill può escludersi con `metadata: {auto-load: "false"}` nel blocco YAML. Se la modalità dei permessi chiede conferma, il caricamento passa dalla stessa approvazione di un `@`.
- **Creare skill**: la skill inclusa `skill-creator` insegna al modello a scriverne di nuove ed è attiva di serie con lo script di avvio.
- **Importare**: pulsante *Import* (anche più file insieme) oppure trascina file e cartelle sulla lista. Limiti: 20 MB e 500 file per importazione. I file e le cartelle nascosti (che iniziano con `.`) nelle cartelle trascinate vengono ignorati.
- **Skill di serie aggiornate da sole**: lo script di avvio aggiorna `coding-agent`, `web-research` e `data-analysis` alla versione del repository, a meno che tu non le abbia modificate.
- **Nome duplicato**: una skill importata con lo stesso nome di una inclusa finisce in `~/.agents/skills` e la nasconde.

## 🚀 Avvio e aggiornamento

Da utente normale (non root):

```bash
git clone https://github.com/Hubert9204/Ganjalf-Studio
cd Ganjalf-Studio
bash scripts/ganjalf-launch.sh
```

Per aggiornare e riavviare, sempre:

```bash
cd ~/Ganjalf-Studio && git pull && bash scripts/ganjalf-launch.sh
```

Lo script tiene dati e ambiente in `~/.ganjalf-studio` (separati da un eventuale Unsloth Studio), installa da questo repository, sceglie la prima porta libera da `8890` e apre il browser. L'installazione scarica diversi GB; la GPU NVIDIA viene riconosciuta da sola.

- **Primo avvio dopo un aggiornamento**: se il `git pull` ha cambiato l'interfaccia o le dipendenze, lo script reinstalla e ricompila il frontend da solo, quindi ci mette qualche minuto in più. Il backend e le skill invece non richiedono reinstallazione.
- **`check_page`**: alla prima esecuzione lo script installa Playwright nell'ambiente di Studio e usa il Chrome/Chromium del sistema, o ne scarica uno (circa 150 MB). Ci prova una volta sola; se Chromium non parte per librerie mancanti: `GANJALF_PAGE_CHECK_DEPS=1 bash scripts/ganjalf-install-page-check.sh`. `GANJALF_PAGE_CHECK=0` lo disattiva.
- **Variabili utili**: `GANJALF_HOME`, `GANJALF_PORT`, `GANJALF_NO_BROWSER=1`, `GANJALF_AUTO_SKILLS=0`, `GANJALF_PAGE_CHECK=0`, `ROLLING_INSTRUCTION_PIN_GROUPS=0` (spegne le istruzioni fissate) e `UNSLOTH_NO_TORCH=1` (solo GGUF, installazione molto più piccola).

**Docker**: `docker/Dockerfile.studio` clona Studio da questo fork (argomento di build `UNSLOTH_STUDIO_REPO`) e include Playwright e Chromium per `check_page` (`--build-arg GANJALF_PAGE_CHECK=0` per toglierli, circa 400 MB). Con una GPU NVIDIA serve il NVIDIA Container Toolkit e l'opzione `--gpus all`.

```bash
docker buildx build -f docker/Dockerfile.studio -t ganjalf-studio docker/
docker run --rm --gpus all -p 8000:8000 -v ganjalf-data:/opt/unsloth-studio ganjalf-studio
```

In Docker lo script di avvio non gira: le skill di serie vengono copiate nel volume a ogni avvio del container, le variabili vanno impostate a mano. Per aggiornare: `docker exec <container> unsloth-studio-update` (segue `main` di questo fork; `--pypi` installa invece la release di Unsloth, sostituendo Ganjalf). Per avere `check_page` in un'immagine costruita prima, va ricostruita.

**Limite di memoria dei tool (Linux)**: il limite di *Impostazioni > Sicurezza > Limite di memoria* vale sulla memoria usata davvero (un controllo ogni secondo ferma il comando che lo supera). Lo spazio di indirizzi riservabile ha 48 GB in più, perché Node riserva circa 10 GB per ogni modulo WebAssembly e con un tetto stretto `vite build` non parte; si cambia con `GANJALF_SANDBOX_AS_HEADROOM_GB` (`0` torna al tetto rigido di Unsloth).

**Aggiornamenti**: Ganjalf si aggiorna solo da questo repository, mai dal pacchetto PyPI di Unsloth senza chiederlo. Quando `main` ha commit nuovi l'interfaccia mostra un avviso con il comando. Variabili e procedura di allineamento con Unsloth in [studio/GANJALF_UPDATES.md](studio/GANJALF_UPDATES.md).

Per le altre opzioni di installazione (HTTPS, accesso da rete locale, solo GGUF) valgono le [istruzioni di Unsloth](https://unsloth.ai/docs/new/studio/).

> **Attenzione:** gli strumenti lato server sono attivi per impostazione predefinita. Se esponi Studio fuori da `localhost`, proteggi la password o avvia con `--disable-tools`. Con i permessi "Full access" il modello può scrivere ovunque l'utente possa scrivere. Hook, server MCP locali e `run_agent` dei plugin eseguono comandi con i tuoi permessi: guarda l'anteprima prima di installare.

## 🔧 Impostazioni consigliate

Per un modello locale che lavora da agente (es. Qwen3.6-35B-A3B con thinking), nel pannello delle impostazioni della chat:

| Impostazione | Valore | Perché |
|---|---|---|
| **Presence Penalty** | `0` (1.0 se va in loop) | predefinito con thinking per i Qwen 3.5/3.6/3.8 (1.5 resta senza thinking); durante le tool call un valore alto penalizza proprio tag, parametri e percorsi. Un 1.5 salvato in passato per un modello resta: rimettilo a 0 o usa il ripristino del valore consigliato |
| **Max Tool Calls Per Message** | `Max` | predefinito in Ganjalf; un valore salvato in passato resta finché non lo cambi |
| **Thinking Budget** | `Auto`, o ~4096 per i lavori lunghi | ragionamenti più brevi tra un passo e l'altro |
| Temperature / Top P / Top K / Min P | 0.6 / 0.95 / 20 / 0 | campionamento consigliato per thinking e codice |
| Thinking | acceso per i lavori agentici | |

Tabella completa per Qwen, Nemotron e Gemma in [studio/ganjalf_prompts/README.md](studio/ganjalf_prompts/README.md).

## 📚 Documentazione

| Documento | Contenuto |
|---|---|
| [studio/PLUGINS.md](studio/PLUGINS.md) | plugin di Claude Code: installazione, hook, agenti, dove stanno i file |
| [studio/PAGE_CHECK.md](studio/PAGE_CHECK.md) | `check_page` e gli errori/screenshot del pannello browser |
| [studio/CLAUDE_API.md](studio/CLAUDE_API.md) | compatibilità con l'API Messages di Anthropic, Stop, timeout, context window, limiti |
| [studio/ganjalf_prompts/README.md](studio/ganjalf_prompts/README.md) | protocollo agentico e campionamento consigliato |
| [studio/ganjalf_skills/README.md](studio/ganjalf_skills/README.md) | skill di serie e come scriverne |
| [studio/GANJALF_UPDATES.md](studio/GANJALF_UPDATES.md) | aggiornamenti, avviso nell'interfaccia, allineamento con Unsloth |
| [studio/TRAINING_OFFLOAD.md](studio/TRAINING_OFFLOAD.md) | offload dei layer nel training |
| [studio/SKILL_MENTIONS.md](studio/SKILL_MENTIONS.md) | come funzionano le menzioni `@skill` |
| [studio/MCP.md](studio/MCP.md) | server MCP e il server MCP di Studio |

### Sviluppo

Il codice sta in `studio/frontend` (React, TypeScript, Tailwind) e in `studio/backend` (FastAPI).

| Cosa | Dove |
| --- | --- |
| Tema, logo in barra laterale | `studio/frontend/src/ganjalf-theme.css` |
| Mascotte | `studio/frontend/src/components/mascot-img.tsx` |
| Animazione di lavoro (libro e pipa) | `studio/frontend/src/components/ganjalf-working-mark.tsx` |
| Titolo della scheda | `studio/frontend/public/ganjalf-boot.js` |
| Nomi nei testi tradotti | `rebrand()` e `translate()` in `studio/frontend/src/i18n/messages.ts` |
| Protocollo agentico | `studio/ganjalf_prompts/`, `studio/backend/core/inference/agentic_protocol.py` |
| Skill: import e scelta automatica | `studio/backend/core/inference/skill_md_import.py`, `skill_relevance.py`, `skill_mentions.py` |
| Skill di serie | `studio/ganjalf_skills/` |
| Plugin | `studio/backend/core/plugins/`, `studio/backend/routes/plugins.py`, `studio/frontend/src/features/chat/components/plugins-dialog.tsx` |
| `check_page` | `studio/backend/core/inference/page_check.py`, `scripts/ganjalf-install-page-check.sh` |
| API Messages (Claude) | `studio/backend/core/inference/anthropic_compat.py`, `/v1/messages` in `studio/backend/routes/inference.py` |
| Thinking Budget | `studio/frontend/src/features/chat/stores/thinking-budget-store.ts` |
| Aggiornamenti | `studio/backend/utils/ganjalf_update.py`, `docker/unsloth_studio_update.sh` |

```bash
cd studio/frontend && npm install && npm run build
cd ../backend && python -m pytest tests/test_ganjalf_*.py tests/test_skill_md_import.py tests/test_skill_relevance.py
```

## 📄 Licenza e crediti

Le parti di Studio (`studio/`) sono sotto **AGPL-3.0**; il pacchetto Unsloth di base è sotto **Apache 2.0**, come nel progetto originale (vedi i file `LICENSE` e `COPYING`). Le modifiche a questo fork restano sotto le stesse licenze e, se offri Studio come servizio in rete, la AGPL richiede di mettere a disposizione degli utenti il sorgente della versione modificata.

I nomi e i loghi Unsloth sono marchi dei rispettivi titolari: questo fork usa un nome e una grafica propri. Le righe di credito e gli avvisi legali del progetto originale restano com'è (nelle traduzioni, "Unsloth AI", "Unsloth team" e i messaggi sotto chiavi *about*, *license*, *attribution* e *credits* non vengono rinominati).

Ganjalf Studio esiste grazie a [Unsloth](https://github.com/unslothai/unsloth) e al lavoro del suo team. Grazie anche a [llama.cpp](https://github.com/ggml-org/llama.cpp), Hugging Face ([transformers](https://github.com/huggingface/transformers), [TRL](https://github.com/huggingface/trl)), PyTorch e NVIDIA, che il progetto originale ringrazia a sua volta.
