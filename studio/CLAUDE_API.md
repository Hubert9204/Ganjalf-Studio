# Compatibilità con l'API Messages di Claude

Ganjalf espone `POST /v1/messages` e `POST /v1/messages/count_tokens` nel formato dell'API
Messages di Anthropic, per i modelli locali (GGUF, safetensors, motori gestiti) e per i provider
esterni. Codice: `studio/backend/core/inference/anthropic_compat.py`, rotte in
`studio/backend/routes/inference.py`, errori in `studio/backend/utils/api_errors.py`.

## Stato (audit di novembre 2026)

| Area | Supporto |
|---|---|
| Richiesta | `model`, `messages`, `system` (stringa o blocchi, `cache_control` accettato), `max_tokens`, `temperature`, `top_p`, `top_k`, `stop_sequences`, `stream`, `metadata`, `thinking` (`enabled`/`adaptive`/`disabled`, `budget_tokens`), `output_config.effort`, `tools` (client, server `web_search`/`web_fetch`/`code_execution`, Anthropic-schema), `tool_choice` (`auto`, `any`, `tool`, `none`) |
| Blocchi in input | `text`, `image` (base64 e URL), `document` (testo, contenuto, PDF base64), `search_result`, `tool_use`, `tool_result` (con `is_error` e immagini), `thinking`/`redacted_thinking` ripetuti dal client |
| Streaming | `message_start`, `ping`, `content_block_start/delta/stop` (`text_delta`, `thinking_delta`, `input_json_delta` a pezzi), `message_delta` (`stop_reason`, `stop_sequence`, `usage`), `message_stop`, `error` a metà stream |
| `stop_reason` | `end_turn`, `max_tokens`, `tool_use`, `stop_sequence` (provider esterni), `refusal` |
| Usage | `input_tokens`, `output_tokens`, `cache_read_input_tokens` (prompt riusato da llama-server), `cache_creation_input_tokens` sempre 0 |
| Errori | corpo `{"type":"error","error":{"type":…,"message":…}}`, 400 `invalid_request_error` anche per la validazione, 401, 403, 404, 413, 429 `rate_limit_error`, 500, 529 `overloaded_error` |
| Intestazioni | `request-id` su ogni risposta di `/v1/messages` |
| Modelli | `GET /v1/models` e `/v1/models/{id}`: con l'intestazione `anthropic-version` aggiungono `type`, `display_name`, `created_at`, `has_more`, `first_id`, `last_id` |
| Annullamento | chiusura della connessione, `cancel_id` o l'id del messaggio fermano la generazione |

Interventi di Ganjalf in questo audit:

- evento `ping` subito dopo `message_start`, come l'API di Anthropic;
- `message_delta.usage` non manda più `input_tokens: 0` quando il conteggio non è noto: gli SDK
  copiano ogni campo non nullo sopra quello di `message_start`, e il contatore del contesto (es. in
  Claude Code) tornava a zero;
- `GET /v1/models` nel formato dell'API Models quando il client è un SDK Anthropic;
- intestazione `request-id`;
- budget di ragionamento per la chat di Studio: `thinking_budget_tokens` (o
  `thinking.budget_tokens`) arriva a llama-server anche sul percorso chat, e l'interfaccia ha il
  cursore **Thinking Budget** (0 = quello del modello).

## Limiti noti

- Con un modello GGUF locale una `stop_sequence` taglia il testo correttamente, ma `stop_reason` è
  `end_turn` invece di `stop_sequence`: llama-server non dice quale parola l'ha fermato nel formato
  OpenAI.
- I blocchi `thinking` hanno `signature` vuota e non arriva un `signature_delta`: non c'è nulla da
  firmare in locale. Un client che rimanda quei blocchi a Ganjalf funziona; non vanno rimandati
  all'API di Anthropic.
- `cache_control` è accettato e ignorato: llama-server riusa il prompt da solo (riportato in
  `cache_read_input_tokens`).
- Files API, Batches API e blocchi `container_upload` non sono implementati.
