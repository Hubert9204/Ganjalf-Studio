# System prompt agentic per Ganjalf Studio

Prompt di sistema pensati per far lavorare i modelli locali come un agente: pianificare prima di agire, chiamare i tool in modo corretto (anche in parallelo), non inventare risultati, gestire gli errori, verificare prima di chiudere.

| File | Per quali modelli |
|---|---|
| `agentic-generic.md` | qualsiasi modello con tool calling |
| `agentic-qwen.md` | Qwen 3.5 / 3.6 / 3.8 (27B, 35B-A3B, con o senza MTP) |
| `agentic-nemotron.md` | Nemotron 3 / 3.5 (Super 120B, Nano) |
| `agentic-gemma.md` | Gemma 4 / 3 |

I file `agentic-*.md` sono generati: si modificano `sections/core.md` e `sections/<famiglia>.md`, poi si lancia `python3 studio/ganjalf_prompts/build.py` (con `--check` verifica che siano allineati).

## Come usarli

**In automatico (default).** Quando nella chat sono attivi dei tool locali, Ganjalf mette il protocollo in testa alle istruzioni sui tool (`core/inference/agentic_protocol.py`): `sections/core.md` più l'addendum della famiglia, riconosciuta dal nome del modello. Non serve fare niente.

| Variabile | Effetto |
|---|---|
| `GANJALF_AGENT_PROTOCOL=auto` | default: Qwen, Nemotron, Gemma da 9B in su |
| `GANJALF_AGENT_PROTOCOL=all` | tutti i modelli da 9B in su, testo generico per le altre famiglie |
| `GANJALF_AGENT_PROTOCOL=off` | mai |
| `GANJALF_AGENT_PROTOCOL_DIR=/percorso` | legge `core.md` e gli addenda da un'altra cartella (per provare varianti senza ricostruire l'immagine) |

Non entra nei provider esterni (OpenAI, Anthropic, Codex…) né nelle chat senza tool. I file vengono letti una volta per processo: dopo averli modificati riavvia Studio.

**A mano, come preset.** Se vuoi modificarlo per un singolo preset, incolla il file della famiglia nel campo **System prompt** e salva il preset. Ganjalf si accorge che il protocollo c'è già (riga `# How you work`) e non lo aggiunge una seconda volta.

Il prompt è in inglese di proposito: i modelli seguono meglio le istruzioni in inglese, ma rispondono nella lingua dell'utente (regola in testa al prompt).

## Cosa aggiunge Ganjalf da solo

Ganjalf accoda già al system prompt dei suggerimenti per i singoli tool (`web_search`, `python`, `terminal`, `render_html`, skill, memoria), vedi `_build_tool_action_nudge` in `studio/backend/routes/inference.py`. Questi prompt non li ripetono: coprono il *metodo* (pianificare, chiamare, gestire errori, verificare), non i singoli tool. Il formato delle tool call lo mette il chat template del modello, quindi il prompt non lo riscrive.

## Sampling consigliato per tool use intenso

| Modello | Modalità | temperature | top_p | top_k | min_p | presence_penalty |
|---|---|---|---|---|---|---|
| Qwen3.8-27B | thinking (agente) | 0.6 (ufficiale 1.0) | 0.95 | 20 | 0 | **0.0** |
| Qwen3.6-35B-A3B | thinking, coding/agente | 0.6 | 0.95 | 20 | 0 | **0.0** (1.0 se va in loop) |
| Qwen 3.x | non-thinking | 0.7 | 0.8 | 20 | 0 | 1.5 |
| Nemotron 3 Super 120B | tool calling | 0.6 (NVIDIA: 1.0) | 0.95 | off | 0.01 | 0.0 |
| Gemma 4 | tutte | 1.0 | 0.95 | 64 | 0 | 0.0 |

Regole generali:
- `repetition_penalty` sempre 1.0: penalizza i token ripetuti e rovina JSON, codice e percorsi.
- `presence_penalty` alto (1.5) fa male alle tool call: llama-server lo applica sugli ultimi 64 token, che durante una chiamata sono proprio tag, nomi di parametro e percorsi. Lato server, una richiesta con tool riceve al massimo `GANJALF_AGENTIC_PRESENCE_PENALTY` (default `0.0`, `off` per disattivare) come valore *consigliato*: vale per i client API (OpenCode, Claude Code, script) che non mandano il campo. Con il thinking acceso Qwen 3.5/3.6/3.8 partono da 0 sia nell'interfaccia sia nell'API (senza thinking resta 1.5); un valore che hai salvato tu, o che il client manda, ha sempre la precedenza.
- Con MTP una temperatura più bassa aumenta l'accettazione dei token speculativi, quindi 0.6 è anche più veloce di 1.0.
- Thinking acceso per i task agentici; spegnilo solo per risposte brevi senza tool.
- Contesto: almeno 64K per loop lunghi; `max_tokens` almeno 32K quando il thinking è acceso.
- **Guardrail morbidi** (solo note, mai blocchi): dopo `GANJALF_VERIFY_AFTER_WRITES` scritture di file di fila (default 6, `0` spento) senza eseguire nulla, il risultato del tool porta una nota che chiede di verificare; se il modello chiude dopo aver modificato file web senza `check_page`, viene rimandato una volta sola a controllare la pagina (`GANJALF_CHECK_PAGE_GATE=0` per spegnerlo). Qualsiasi `check_page`, anche fallito o non disponibile, toglie il promemoria.
- **Max Tool Calls Per Message** parte da "Max" in Ganjalf: un lavoro lungo si ferma al contesto o dopo 8 chiamate fallite di fila (`GANJALF_TOOL_FAILURE_STREAK`). Un valore salvato in passato resta finché non lo cambi.
- **Thinking Budget** (impostazioni della chat, solo modelli locali): Auto lascia il budget del modello; intorno a 4096 token accorcia le pause di ragionamento tra un passo e l'altro. Via API: `thinking_budget_tokens` o `thinking.budget_tokens`.
