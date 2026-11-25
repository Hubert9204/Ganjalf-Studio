# Skill di Ganjalf

Ogni cartella qui è una skill (`<nome>/SKILL.md`). `scripts/ganjalf-launch.sh` e, nell'immagine Docker, `docker/studio_home.sh` le copiano nella cartella skill dell'utente: le installano se mancano, le aggiornano se non le hai modificate, le lasciano stare se le hai modificate.

| Skill | Quando si carica |
|---|---|
| `coding-agent` | scrivere o correggere codice in una cartella di progetto |
| `web-research` | fatti attuali da cercare online, con fonti |
| `data-analysis` | CSV, Excel, JSON: numeri e grafici calcolati con Python |
| `git-workflow` | commit, branch, push, pull request, conflitti: legge le modifiche prima, messaggi chiari, niente force e niente salti degli hook; push e PR chiedono conferma |
| `init` | solo quando scrivi `/init`: esplora il progetto e scrive `AGENTS.md`, la guida che ogni chat nuova del progetto legge per prima |

## Come Ganjalf sceglie una skill

1. **Menzione esplicita**: `@web-research` nel messaggio carica la skill prima della generazione.
2. **Selezione automatica** (`core/inference/skill_relevance.py`): confronta le parole del messaggio con nome e `description` di ogni skill. Servono almeno 3 termini in comune e un distacco del 25% sulla seconda skill, altrimenti non carica niente. Le parole sono tagliate a 6 lettere ("generate" e "generation" contano uguale), quelle comuni a tutte le skill pesano meno.
3. **Il modello** può chiamare `read_skill` leggendo il catalogo (nome + descrizione) che Ganjalf mette nel system prompt: 4 KB per i modelli grandi, 1,5 KB sotto i 9B.

Quindi **la `description` è la parte più importante**: decide sia la selezione automatica sia quella del modello.

## Come scrivere una skill che rende il modello più "agentico"

**Description** (una riga, sotto i 600 caratteri):
- Prima cosa fa, poi gli oggetti tipici delle richieste, poi `Italiano -` con le parole che userai davvero ("cerca online", "foglio di calcolo").
- Parole *distintive*: termini che compaiono anche nelle altre skill non aiutano la selezione e possono renderla ambigua. Evita parole generiche come "file", "python", "script" se non sono il cuore della skill.
- Una skill che non deve mai caricarsi da sola (es. una procedura di rilascio) ha `metadata: {auto-load: "false"}` nel frontmatter.

**Corpo** (1–4 KB; i modelli locali seguono meglio istruzioni brevi):
1. Una frase: quando usarla.
2. **Limiti dell'ambiente**: cosa non funziona (sandbox, niente GPU, processi che muoiono a fine chiamata). Evita che il modello sprechi chiamate.
3. **Passi numerati** con il criterio per passare al successivo, e quali chiamate fare *insieme* nello stesso turno.
4. **Regole di verità**: da dove deve venire ogni numero o fatto (output di un tool, mai a occhio).
5. **Errori**: cosa fare quando un passo fallisce e quando cambiare strada (di solito: dopo 2 fallimenti dello stesso approccio).
6. **Fatto quando**: il controllo finale e il formato della risposta.

Scrivi in inglese, imperativo, frasi corte, niente prosa motivazionale. Metti esempi concreti di comandi (`wc -l FILE`, `sed -n '1,120p' FILE`) invece di principi astratti.

Il metodo generale (pianificare, chiamare, gestire errori, verificare) sta nel system prompt in `studio/ganjalf_prompts/`; le skill aggiungono solo la procedura del loro dominio.

## Controllo

`studio/backend/tests/test_ganjalf_shipped_skills.py` verifica che ogni skill di questa cartella vinca le sue richieste e non rubi quelle delle altre. Quando aggiungi una skill, aggiungi lì 2–3 richieste tipiche:

```bash
cd studio/backend && python -m pytest -q --noconftest tests/test_ganjalf_shipped_skills.py
```
