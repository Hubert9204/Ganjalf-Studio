<p align="center">
  <img alt="Ganjalf Studio" src="images/ganjalf-banner.svg" width="100%" />
</p>

<h3 align="center">Ganjalf Studio: un fork di Unsloth Studio con skill <code>SKILL.md</code>, tema grigio-argento e interfaccia rivista.</h3>

<p align="center">
  <a href="#-novità">Novità</a> •
  <a href="#-le-skill">Skill</a> •
  <a href="#-avvio-da-sorgente">Avvio</a> •
  <a href="#-licenza-e-crediti">Licenza</a>
</p>

> **Progetto non ufficiale.** Ganjalf Studio è un fork indipendente di [Unsloth](https://github.com/unslothai/unsloth) e non è affiliato a Unsloth AI. Per documentazione, modelli e supporto del progetto originale vedi [unsloth.ai/docs](https://unsloth.ai/docs).

## ✨ Novità

- **Import delle skill**: dalla finestra *Skills* importi un singolo `SKILL.md`, più file scelti insieme, una cartella trascinata sulla lista o un archivio ZIP.
- **Tema Ganjalf**: palette grigio-argento con accento blu freddo, in versione chiara e scura. Le palette con nome di Unsloth restano disponibili e hanno la precedenza quando le scegli.
- **Nuova identità**: titolo della scheda, icona (SVG) e manifest dell'app rinominati in *Ganjalf Studio*.
- **Tutto il resto di Unsloth Studio**: esecuzione e addestramento di modelli, chat, agenti e strumenti, API compatibile con OpenAI, RAG e ricerca.

## 📜 Le skill

Una skill è una cartella con un file `SKILL.md`: un blocco YAML iniziale con `name` e `description`, poi le istruzioni in Markdown.

```markdown
---
name: revisore-codice
description: Rivede una modifica e segnala bug, test mancanti e problemi di stile.
---
Quando l'utente chiede una revisione, leggi prima il diff e poi…
```

- **Dove vivono**: di default in `~/.agents/skills`; la cartella si cambia con la variabile `UNSLOTH_STUDIO_SKILLS_HOME`. Studio legge anche `~/.claude/skills` e alcune skill incluse.
- **Come le conosce il modello**: nel prompt entra un catalogo con nome e descrizione delle skill attive. Il testo completo si carica quando scrivi `@nome-skill` nel messaggio o quando il modello lo richiede.
- **Creare skill**: la skill inclusa `skill-creator` insegna al modello a scriverne di nuove. Come tutte le skill incluse parte disattivata: attivala dalla finestra *Skills*.
- **Importare**: pulsante *Import* (anche più file insieme) oppure trascina file e cartelle sulla lista. Limiti: 20 MB e 500 file per importazione. I file e le cartelle nascosti (che iniziano con `.`) nelle cartelle trascinate vengono ignorati.
- **Nome duplicato**: una skill importata con lo stesso nome di una inclusa finisce in `~/.agents/skills` e la nasconde.

## 🚀 Avvio da sorgente

Il procedimento è quello di Unsloth Studio (installazione locale dal repository).

**macOS, Linux, WSL**
```bash
git clone https://github.com/Hubert9204/Ganjalf-Studio
cd Ganjalf-Studio
UNSLOTH_STUDIO_HOME="$PWD/.studio" ./install.sh --local
UNSLOTH_STUDIO_HOME="$PWD/.studio" unsloth studio -p 8890
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/Hubert9204/Ganjalf-Studio.git
cd Ganjalf-Studio
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
$env:UNSLOTH_STUDIO_HOME="$PWD\.studio"; .\install.ps1 --local
$env:UNSLOTH_STUDIO_HOME="$PWD\.studio"; unsloth studio -p 8890
```

`UNSLOTH_STUDIO_HOME` tiene dati e ambiente in una cartella tua e la porta `8890` evita conflitti con un'eventuale istanza di Unsloth Studio già installata (che usa `8888` per impostazione predefinita). Per le altre opzioni di installazione e di avvio (GPU, solo GGUF, accesso da rete locale, HTTPS) valgono le [istruzioni di Unsloth](https://unsloth.ai/docs/new/studio/).

> **Attenzione:** gli strumenti lato server sono attivi per impostazione predefinita. Se esponi Studio fuori da `localhost`, proteggi la password o avvia con `--disable-tools`.

### Sviluppo del frontend

Il codice sta in `studio/frontend` (React, TypeScript, Tailwind) e il backend in `studio/backend` (FastAPI). Il tema è in `studio/frontend/src/ganjalf-theme.css`; l'import delle skill in `studio/backend/core/inference/skill_md_import.py` e `studio/backend/routes/skills.py`.

```bash
cd studio/frontend
npm install
npm run build
```

Test dell'import delle skill:
```bash
pytest studio/backend/tests/test_skill_md_import.py
```

## 📄 Licenza e crediti

Le parti di Studio (`studio/`) sono sotto **AGPL-3.0**; il pacchetto Unsloth di base è sotto **Apache 2.0**, come nel progetto originale (vedi i file `LICENSE` e `COPYING`). Le modifiche a questo fork restano sotto le stesse licenze e, se offri Studio come servizio in rete, la AGPL richiede di mettere a disposizione degli utenti il sorgente della versione modificata.

Ganjalf Studio esiste grazie a [Unsloth](https://github.com/unslothai/unsloth) e al lavoro del suo team. Grazie anche a [llama.cpp](https://github.com/ggml-org/llama.cpp), Hugging Face ([transformers](https://github.com/huggingface/transformers), [TRL](https://github.com/huggingface/trl)), PyTorch e NVIDIA, che il progetto originale ringrazia a sua volta.
