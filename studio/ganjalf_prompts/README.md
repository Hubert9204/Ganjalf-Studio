# System prompt agentic per Ganjalf Studio

Prompt di sistema pensati per far lavorare i modelli locali come un agente: pianificare prima di agire, chiamare i tool in modo corretto (anche in parallelo), non inventare risultati, gestire gli errori, verificare prima di chiudere.

| File | Per quali modelli |
|---|---|
| `agentic-generic.md` | qualsiasi modello con tool calling |
| `agentic-qwen.md` | Qwen 3.5 / 3.6 / 3.8 (27B, 35B-A3B, con o senza MTP) |
| `agentic-nemotron.md` | Nemotron 3 / 3.5 (Super 120B, Nano) |
| `agentic-gemma.md` | Gemma 4 / 3 |

I file `agentic-*.md` sono generati: si modificano `parts/core.md` e `parts/<famiglia>.md`, poi si lancia `python3 studio/ganjalf_prompts/build.py` (con `--check` verifica che siano allineati).

## Come usarli

1. Apri la chat, impostazioni del modello, campo **System prompt**.
2. Incolla il contenuto del file della famiglia del modello.
3. Salvalo come preset (es. "Agente Qwen") così lo richiami in un clic.

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
- `presence_penalty` alto (1.5) in modalità thinking fa male alle tool call: llama-server lo applica sugli ultimi 64 token, che durante una chiamata sono proprio tag, nomi di parametro e percorsi. Oggi Ganjalf mette 1.5 anche in thinking per Qwen 3.5/3.6/3.8 (`qwen-sampling-table.ts`, `inference_defaults.json`): per l'uso agentico impostalo a 0 nel preset.
- Con MTP una temperatura più bassa aumenta l'accettazione dei token speculativi, quindi 0.6 è anche più veloce di 1.0.
- Thinking acceso per i task agentici; spegnilo solo per risposte brevi senza tool.
- Contesto: almeno 64K per loop lunghi; `max_tokens` almeno 32K quando il thinking è acceso.
