# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A learning/experimental RAG (retrieval-augmented generation) project in plain Python.
Standalone scripts, no framework, no package layout:

- [main.py](main.py) — earliest iteration. Uses the `demo` Qdrant collection. The
  augmented prompt is built but **not used** — `main()` calls `generate_response(prompt)`
  with the raw prompt. Treat this as scratch/reference.
- [basic_rag.py](basic_rag.py) — the current script. Uses the `articles` collection and
  a full ingest → clean → chunk → embed → store pipeline plus an interactive query loop.
- [watch_data.py](watch_data.py) — a `watchdog` file watcher that keeps the `articles`
  collection in sync with `data/`: (re)indexes an `.mdx`/`.md`/`.pdf` file when it is
  created/modified, removes its points when the file is deleted. Has its own document
  loading + chunking (does **not** use `basic_rag`'s `create_chunks`).

## External services (must be running before any script)

- **Qdrant** vector DB at `http://localhost:6333` — collections are auto-created on first run.
- **Ollama** at `http://localhost:11434` with these models pulled:
  - `mxbai-embed-large:335m` — embeddings, 1024-dim, cosine distance (matches `VectorParams`).
  - `mistral:7b-instruct-q4_K_M` — generation and prompt translation.

```
docker run -p 6333:6333 qdrant/qdrant
ollama pull mxbai-embed-large:335m
ollama pull mistral:7b-instruct-q4_K_M
```

## Commands

The project runs under the venv at `env/`, created from **WSL** (`env/bin/python`,
Linux Python 3.14). Run scripts with that interpreter — from WSL directly, or from
Windows via `wsl`:

```
env/bin/python -m pip install -r requirements.txt   # one-time
./start.sh                        # Qdrant (Docker) + watch_data.py; ./start.sh stop to tear down
env/bin/python watch_data.py      # THE ingestion path: sync data/ into Qdrant, then watch
env/bin/python watch_data.py --force     # re-index every file, ignoring the unchanged check
env/bin/python watch_data.py --no-sync   # watch only, skip the initial sync
env/bin/python basic_rag.py       # query loop (does NOT ingest); type "exit" to quit
env/bin/python ab_test.py "..."   # answer one question with vs without retrieved context
env/bin/python main.py            # older scratch version
```

`start.sh` runs the snap Docker via `sudo` (this box's user is not in the `docker`
group), names the container `rag-qdrant`, and persists data in `qdrant_storage/`.

There are no tests, linters, or build steps.

## How ingestion works

**`basic_rag.py` and `main.py` do NOT ingest** — their `main()` ingest block is commented
out; running them only starts the query loop. Loading `data/` into Qdrant is
[watch_data.py](watch_data.py)'s job (see below). The commented block in
[basic_rag.py](basic_rag.py) is the original, hand-run ingestion path and is kept for
reference only.

`basic_rag.py`'s (commented) ingest pipeline, per `.mdx` file in `data/`:

1. `extract_metadata_from_mdx` — parses `---` YAML front matter if present; otherwise
   falls back to `{title: <first line>, source: <filename>}`. `data/shrek.mdx` has **no**
   front matter, so it takes the fallback path.
2. `main()` then sets `metadata["slug"]` from the filename.
3. `clean_article_content` — strips `import ...` lines and HTML/JSX tags.
4. `create_chunks` — splits on blank lines (`\n\n`), one chunk per paragraph.
5. `store_article` — embeds each chunk and upserts a `PointStruct` whose payload is
   `{**metadata, "content": chunk}`.

Point IDs are **sequential integers assigned manually** via `start_id` / the `point_id`
counter, threaded across files by `store_article`'s return value. Re-running ingestion
reuses IDs from 0 and overwrites existing points.

## The watcher (`watch_data.py`)

Imports `basic_rag` for `client` + `generate_embeddings` (and to auto-create the
`articles` collection) and `extract_metadata_from_mdx` / `clean_article_content` for the
`.md`/`.mdx` path. Everything else is its own.

- **`load_document(path)`** dispatches by extension → `(metadata, chunks)`:
  - `.pdf` → `pypdf` (`_read_pdf`): text per page joined by blank lines; `title`/`author`
    pulled from the PDF's metadata when present, `pages` count always added. Pages that
    come out one-word-per-line (Google Docs export) are whitespace-collapsed so
    `chunk_text`'s sentence splitter can re-segment them.
  - `.md`/`.mdx` → `extract_metadata_from_mdx` + `clean_article_content`.
  - `title` / `source` default to the filename when missing.
- **`chunk_text`** (used for every type, replacing `basic_rag.create_chunks`): normalizes
  text (de-hyphenates line breaks, collapses blank lines), then packs paragraphs into
  ~`CHUNK_TARGET` (1200) char chunks with `CHUNK_OVERLAP` (200) char overlap; falls back
  to line/size splitting when the source has no paragraph structure. `shrek.mdx` →
  ~76 chunks (was 890 under the `\n\n` split).
- Point IDs are **deterministic UUIDv5** from `f"{slug}#{chunk_index}"`, so re-processing
  a file is idempotent.
- **Skip-if-unchanged**: `ingest_file` stores the file's SHA-256 in every point's payload
  as `file_hash` and returns early (`[skip] slug: inalterado`) when the current file
  hashes the same. `--force` re-indexes anyway. So re-running the watcher is cheap.
- Embeddings are upserted in batches of `UPSERT_BATCH` (32) as they finish, with
  `[..] slug: done/total` progress. After the last batch, `_delete_stale` removes points
  for that `slug` whose id is not in the new set (handles a shrunk / re-chunked file).
- `initial_sync` also **prunes**: any `slug` in Qdrant with no matching file in the folder
  is deleted (`[sync] slug: removido`). A file deleted while the watcher runs triggers the
  same via `delete_article`.
- `slug` = filename without extension → keep filenames clean, the `slug` shows up in the
  retrieval context the LLM sees. Watches `data/` non-recursively.
- Filesystem events are debounced per-path (`DEBOUNCE_SECONDS`) and gated on a
  file-size-stability check before indexing, to survive editors' multi-write saves and
  slow PDF copies.
- Observer selection: `inotify` does not fire for Windows-drive paths under WSL2, so the
  script uses `PollingObserver` automatically when the watched path is under `/mnt/` or
  `/media/`. Override with `--poll` / `--no-poll`.

Cold embedding call is ~14 s (Ollama model load); warm calls ~0.1 s each.

## Query flow (`basic_rag.py`)

user prompt → prefix `"Represent this sentence for searching relevant passages: "` →
embed → `query_points` top 8 from `articles` → drop near-duplicate hits (first 80 chars
match) and echo each kept hit's score+preview to the terminal → build a plain-text prompt
(`CONTEXTO:` / `PERGUNTA:` / `RESPOSTA:`, instruction to answer in pt-BR from the context
only and say `"Não encontrei isso nos documentos."` otherwise) → `generate_response`
(`num_ctx: 10000`).

- The embed prefix must stay minimal — it only steers retrieval. Answer language and
  behavior are set in the generation prompt, not here. `mxbai-embed-large` is multilingual,
  so a PT query hits an EN corpus fine (the old `translate_prompt` PT→EN hop was removed).
- The old `<retrieved-data>` / `<user-prompt>` XML wrapper was replaced: with low-quality
  chunks, Mistral 7B echoed that structure back and invented passage contents instead of
  answering. The plain format plus an explicit decline path fixed it.
- The context builder reads `point.payload['slug']` and `['content']`; a document indexed
  without those keys raises `KeyError` at query time.

## Grounding check (`ab_test.py`)

Standalone. For a question, prints the retrieved chunks with scores, then answers it two
ways: **with** the retrieved passages (same augmented prompt as `basic_rag.py`) and
**without** them (`generate_response` on the bare question). If the two answers look
alike, the model is leaning on training data rather than the corpus. The default question
set includes one deliberately out-of-corpus question (FLOPs cost) where the grounded
answer should decline and the ungrounded one rambles.
