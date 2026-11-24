# Aggiornamenti di Ganjalf Studio

Ganjalf è un fork che si installa da sorgente, quindi si aggiorna dal proprio repository GitHub. Il pacchetto `unsloth` su PyPI è Unsloth Studio ufficiale: installarlo sopra Ganjalf lo sostituirebbe, per questo nessun percorso di aggiornamento lo usa più senza una richiesta esplicita.

## Come si aggiorna

| Installazione | Comando | Da dove |
|---|---|---|
| Launcher (`scripts/ganjalf-launch.sh`) | `git pull && bash scripts/ganjalf-launch.sh` | il remote del tuo clone |
| Docker | `docker exec <container> unsloth-studio-update` | `UNSLOTH_STUDIO_REPO` @ `GANJALF_UPDATE_BRANCH` (predefiniti: questo fork, `main`) |
| CLI `unsloth studio update` | fa `git pull --ff-only` dal repository Ganjalf e reinstalla da sorgente | come sopra |

- `unsloth-studio-update --ref <ref>` installa un ref preciso dello stesso repository; `--pypi` installa la release di Unsloth da PyPI (sostituisce Ganjalf).
- Se il clone ha modifiche o commit locali, `unsloth studio update` non installa nulla e chiede di fare il merge a mano.

## L'avviso nell'interfaccia

Il backend confronta il commit da cui è stata costruita l'installazione con il branch seguito, tramite l'API GitHub `compare` (al massimo una richiesta ogni 6 ore, un'ora dopo un errore). Se il branch ha commit nuovi, il banner mostra quanti sono, il comando da copiare e un link alla pagina delle modifiche su GitHub.

Il commit locale viene da `GANJALF_STUDIO_REVISION`, poi dal file `.ganjalf-revision` (scritto dalla build Docker e da `unsloth-studio-update`, perché l'immagine non ha `.git`), poi da `git rev-parse HEAD`.

| Variabile | Effetto |
|---|---|
| `GANJALF_UPDATE_SOURCE=ganjalf` | predefinito: controlla il repository Ganjalf |
| `GANJALF_UPDATE_SOURCE=unsloth` | torna al comportamento di Unsloth (controllo su PyPI, `unsloth studio update` da PyPI) |
| `GANJALF_UPDATE_SOURCE=off` | nessun controllo (anche `UNSLOTH_DISABLE_UPDATE_CHECK=1`) |
| `GANJALF_UPDATE_REPO` | `owner/nome` o URL GitHub (predefinito: `UNSLOTH_STUDIO_REPO`, poi `Hubert9204/Ganjalf-Studio`) |
| `GANJALF_UPDATE_BRANCH` | branch da seguire (predefinito `main`) |
| `GITHUB_TOKEN` | facoltativo, alza il limite di richieste all'API GitHub |

L'app desktop (Tauri), se la compili, cerca gli aggiornamenti tra le release di questo fork e non tra quelle di Unsloth. Le release devono essere firmate con la chiave indicata in `studio/src-tauri/tauri.conf.json`: finché il fork non ne pubblica, l'app non trova aggiornamenti.

Restano verso Unsloth solo cose che non installano Ganjalf: i binari precompilati di llama.cpp, audio.cpp e whisper.cpp, il pacchetto `unsloth-zoo`, le note di rilascio e la documentazione di Unsloth.

## Allineamento con Unsloth

```bash
git remote add upstream https://github.com/unslothai/unsloth   # una volta
git fetch upstream main
git merge upstream/main
```

Prima del merge controlla i file in conflitto. Dopo, verifica che le modifiche di Ganjalf siano ancora al loro posto: rebranding (`translate()` in `i18n/messages.ts` e le stringhe dell'interfaccia), protocollo agentico (`core/inference/agentic_protocol.py`), skill e prompt, offload automatico, aggiornamenti (`utils/ganjalf_update.py`, `docker/unsloth_studio_update.sh`). I test che lo controllano hanno nomi che iniziano con `test_ganjalf_` o `ganjalf-`.
