# Vedere le pagine: `check_page` e il pannello browser

Un modello che scrive una pagina web o un gioco nel browser deve poterla vedere girare, altrimenti
dichiara "funziona" davanti a uno schermo nero. Ganjalf gli dà due modi.

## `check_page` (browser sul server)

Tool del backend (`studio/backend/core/inference/page_check.py`), offerto insieme agli strumenti di
codice (`python`, `terminal`, `edit_file`, `view_image`) quando sul server ci sono Playwright e un
Chromium.

- Apre un file della cartella di lavoro (o un indirizzo `http://localhost:PORTA` di un server avviato
  dal modello) in un Chromium headless: nessuna finestra, è un display virtuale. Funziona senza
  schermo, in Docker e con la chat chiusa.
- I file della cartella sono serviti da un'origine fittizia (`http://workspace.ganjalf/`) tramite
  l'instradamento delle richieste di Playwright: moduli ES, import map e `fetch()` dei file vicini
  funzionano come su un server web, e non si apre nessuna porta.
- Aspetta `wait_seconds` (predefinito 2, massimo 20), preme i tasti in `keys` (es. `["Enter"]`) e
  restituisce: titolo, errori non gestiti e `console.error` con la riga, richieste fallite o
  bloccate, dimensioni dei canvas, testo visibile e uno screenshot 1280x720. Se lo screenshot è di un
  solo colore lo dice esplicitamente (lo script si è fermato).
- WebGL funziona senza GPU (SwiftShader).
- Allo **Stop** della chat ritorna subito; il browser headless si chiude da solo.
- Promemoria a fine turno: se il modello ha modificato file web (HTML/CSS/Vue/Svelte/JSX/TSX, o
  JS/TS in una cartella con un file HTML) e sta per dare la risposta finale senza aver lanciato
  `check_page` dopo l'ultima modifica, viene rimandato **una sola volta** a controllare la pagina.
  Scatta solo se `check_page` è offerto; qualsiasi `check_page` (anche fallito o non disponibile) lo
  toglie, e se la pagina non si può controllare il modello lo dice e chiude.
  `GANJALF_CHECK_PAGE_GATE=0` lo spegne.
- Raggiunge Internet pubblico e il loopback; blocca le porte di Studio, le reti private e i siti
  esclusi dalla policy di accesso web. Il testo della pagina arriva al modello dentro il recinto dei
  contenuti non fidati.

Installazione:

| Dove | Come |
|---|---|
| `scripts/ganjalf-launch.sh` | al primo avvio esegue `scripts/ganjalf-install-page-check.sh` (una volta; il marcatore è `~/.ganjalf-studio/.ganjalf-page-check-tried`) |
| a mano | `bash scripts/ganjalf-install-page-check.sh`, poi riavvia Studio |
| librerie di sistema mancanti | `GANJALF_PAGE_CHECK_DEPS=1 bash scripts/ganjalf-install-page-check.sh` (serve root o sudo) |
| Docker | incluso nell'immagine; `--build-arg GANJALF_PAGE_CHECK=0` lo esclude (circa 400 MB) |

Variabili: `GANJALF_PAGE_CHECK=0` non lo installa e non lo offre; `GANJALF_PAGE_CHECK_BROWSER=/percorso/chrome`
sceglie il browser; senza, usa il Chromium di Playwright se scaricato, altrimenti `chromium`,
`chromium-browser` o `google-chrome` del sistema.

## Il pannello browser della chat

- **Errori della pagina**: la shell del pannello (`routes/browser.py`), l'anteprima dei file HTML e
  le viste native dell'app desktop registrano errori non gestiti, promesse rifiutate,
  `console.error`, risorse non caricate e richieste bloccate dall'anteprima, dal primo script in poi.
  `browser_navigate` e `browser_snapshot` li riportano al modello in "Page errors since it loaded".
  Le righe degli script inline sono quelle del file del modello.
- **Screenshot nella versione web**: senza l'app desktop il pannello non può catturare lo schermo
  senza chiedere; la pagina si disegna da sola (markup e canvas, letti dentro un frame d'animazione
  così anche WebGL viene catturato). Immagini di altri siti e iframe restano fuori.
