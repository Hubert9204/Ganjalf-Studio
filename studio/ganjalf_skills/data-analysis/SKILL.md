---
name: data-analysis
description: Analyze a dataset or spreadsheet - CSV, Excel, XLSX, JSON, Parquet tables. Column statistics, totals, averages, filters, group by, pivot, trends, charts, cleaning messy rows. Italiano - analizza dati, foglio di calcolo, tabella, colonne, righe, statistiche, media, somma, totale, percentuale, grafico, andamento, pulisci dati.
---

# Data analysis

Use this when the user gives you a table of data and wants numbers, patterns or a chart from it.

## Every number comes from code
Never compute, count or estimate by reading the data yourself. Every figure in your answer must be printed by a `python` call in this conversation.

## Steps
1. Inspect first, in one call: load the file, print shape, column names and types, `head()`, missing values per column. Do not print the whole table.
2. Say in one line what each relevant column means and anything odd (dates stored as text, numbers with commas, duplicates). Ask the user only if a column's meaning changes the result.
3. Clean only what the question needs, and say what you changed (rows dropped, types converted).
4. Compute the answer. Print results as small tables (at most about 30 rows); aggregate before printing.
5. Check: totals add up, row counts before and after filters, a spot check of one value against the raw row.
6. For a chart, save it as a PNG in the project folder and say where it is.

## The python tool
- Each call is a fresh process: variables do not survive between calls. Load the file again in each call, or save an intermediate result (`.parquet` or `.csv`) and load that.
- If pandas or openpyxl is missing, try `pip install` once; if it fails, use the csv and json modules.
- For a large file, read only the needed columns (`usecols`) or a sample first.

## Answer
The answer in one or two sentences, then a small table of the key numbers, then how you got them (filters, assumptions) and anything you could not check.
