"""Watchdog que mantem a colecao Qdrant `articles` em sincronia com a pasta data/.

- arquivo .mdx/.md/.pdf criado ou modificado -> (re)indexa o documento
- arquivo removido                           -> remove os pontos do documento

Cada documento e identificado pelo seu `slug` (nome do arquivo sem extensao).
Um arquivo so e reindexado quando seu conteudo muda: o hash SHA-256 do arquivo fica
no payload dos pontos e e comparado antes de gerar embeddings de novo. Ao reindexar,
os chunks que sumiram na nova versao sao apagados, entao editar um arquivo nunca
deixa chunks orfaos. Os IDs dos pontos sao UUIDv5 deterministicos derivados de
`slug#indice` (diferente do basic_rag.py, que usa inteiros manuais). Os embeddings
sao gravados em lotes conforme ficam prontos, com log de progresso.

Uso:
    python watch_data.py            # sincroniza os arquivos alterados e depois observa
    python watch_data.py --no-sync  # apenas observa mudancas a partir de agora
    python watch_data.py --force    # reindexa tudo, mesmo sem mudanca
    python watch_data.py --path OUTRA/PASTA

Precisa de um Qdrant em localhost:6333 e um Ollama em localhost:11434 rodando
(mesmos servicos/modelos do basic_rag.py).
"""
import argparse
import hashlib
import os
import re
import threading
import time
import uuid
from collections import Counter

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from qdrant_client.models import (
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
)

try:
    from pypdf import PdfReader
except ImportError:  # PDF e opcional; so quebra se houver .pdf na pasta
    PdfReader = None

# Reaproveita o pipeline de ingestao e o client ja configurado.
# Importar basic_rag tambem garante que a colecao `articles` exista.
from basic_rag import (
    clean_article_content,
    client,
    extract_metadata_from_mdx,
    generate_embeddings,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
COLLECTION = "articles"
EXTENSIONS = (".mdx", ".md", ".pdf")
DEBOUNCE_SECONDS = 1.5  # espera o editor parar de escrever antes de indexar
UPSERT_BATCH = 32       # grava no Qdrant a cada N chunks
CHUNK_TARGET = 1200     # tamanho alvo de um chunk, em caracteres
CHUNK_OVERLAP = 200     # trecho repetido entre chunks vizinhos, em caracteres


def log(msg: str) -> None:
    print(msg, flush=True)  # flush: stdout fica block-buffered quando nao e um terminal


def slug_for(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def is_doc(path: str) -> bool:
    return path.lower().endswith(EXTENSIONS)


def _normalize(text: str) -> str:
    """Limpa texto cru (principalmente de PDF) antes de fatiar em chunks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"-\n(?=\w)", "", text)          # une palavra hifenizada na quebra
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)          # colapsa linhas em branco
    return text.strip()


def chunk_text(text: str) -> list[str]:
    """Empacota paragrafos em chunks de ~CHUNK_TARGET chars com sobreposicao.

    Serve para prosa (PDF, .md). Sem paragrafos, cai para sentencas; se ainda
    assim houver blocos gigantes, fatia por tamanho.
    """
    text = _normalize(text)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) < 2:
        blocks = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

    chunks: list[str] = []
    buf = ""
    for block in blocks:
        if buf and len(buf) + len(block) + 1 > CHUNK_TARGET:
            chunks.append(buf)
            tail = buf[-CHUNK_OVERLAP:]
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail
            buf = f"{tail}\n{block}".strip()
        else:
            buf = f"{buf}\n{block}".strip() if buf else block
    if buf:
        chunks.append(buf)

    out: list[str] = []
    step = max(CHUNK_TARGET - CHUNK_OVERLAP, 1)
    for c in chunks:
        if len(c) <= CHUNK_TARGET * 1.5:
            out.append(c)
        else:
            out.extend(c[i:i + CHUNK_TARGET] for i in range(0, len(c), step))

    # descarta chunks curtos e duplicados (PDF costuma repetir a 1a pagina)
    final, seen = [], set()
    for c in out:
        if len(c) < 40:
            continue
        key = re.sub(r"\W+", "", c.lower())[:120]
        if key in seen:
            continue
        seen.add(key)
        final.append(c)
    return final


_EQ_NOISE = re.compile(r"^[\s(]*\(?\d{1,3}\)?[\s.,;:−-]*$")  # linhas tipo "(14)" ou "− (5)"


def _strip_pdf_noise(raw_pages: list[str]) -> list[str]:
    """Remove cabecalho/rodape que se repete entre paginas e linhas de numero de equacao."""
    n = len(raw_pages)
    freq: Counter[str] = Counter()
    for pg in raw_pages:
        for ln in {l.strip() for l in pg.splitlines() if l.strip()}:
            freq[ln] += 1
    boiler = {ln for ln, c in freq.items() if n >= 3 and c >= max(3, n * 0.34)}

    out = []
    for pg in raw_pages:
        kept = [
            ln for ln in pg.splitlines()
            if ln.strip() and ln.strip() not in boiler and not _EQ_NOISE.match(ln)
        ]
        out.append("\n".join(kept))
    return out


def _read_pdf(path: str) -> tuple[dict, str]:
    if PdfReader is None:
        raise RuntimeError("suporte a PDF requer pypdf: pip install pypdf")
    reader = PdfReader(path)
    info = reader.metadata or {}

    raw_pages = []
    for page in reader.pages:
        try:
            raw = page.extract_text() or ""
        except Exception:  # pagina problematica nao derruba o arquivo inteiro
            raw = ""
        # alguns exportadores (ex. Google Docs) quebram cada palavra numa linha;
        # nesse caso colapsa os espacos e deixa o chunk_text redividir por sentenca
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if lines and sum(len(ln) < 15 for ln in lines) > 0.5 * len(lines):
            raw = re.sub(r"\s+", " ", raw)
        raw_pages.append(raw)

    pages = _strip_pdf_noise(raw_pages)
    meta: dict = {"pages": len(reader.pages)}
    if getattr(info, "title", None):
        meta["title"] = info.title.strip()
    if getattr(info, "author", None):
        meta["author"] = info.author
    return meta, "\n\n".join(pages)


def load_document(path: str) -> tuple[dict, list[str]]:
    """(metadata, chunks) para .pdf, .md ou .mdx."""
    if path.lower().endswith(".pdf"):
        metadata, text = _read_pdf(path)
    else:
        metadata, raw = extract_metadata_from_mdx(path)
        text = clean_article_content(raw)
    metadata.setdefault("title", slug_for(path))
    metadata.setdefault("source", os.path.basename(path))
    return metadata, chunk_text(text)


def file_is_stable(path: str, wait: float = 0.4) -> bool:
    """True se o tamanho do arquivo nao mudar durante `wait` segundos."""
    try:
        size1 = os.path.getsize(path)
        time.sleep(wait)
        return size1 == os.path.getsize(path)
    except OSError:
        return False


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def _indexed_hash(slug: str) -> str | None:
    """Hash do arquivo guardado no payload dos pontos desse slug (ou None)."""
    points, _ = client.scroll(
        collection_name=COLLECTION,
        scroll_filter=Filter(must=[FieldCondition(key="slug", match=MatchValue(value=slug))]),
        limit=1,
        with_payload=["file_hash"],
        with_vectors=False,
    )
    return points[0].payload.get("file_hash") if points else None


def _slug_filter(slug: str) -> FilterSelector:
    return FilterSelector(
        filter=Filter(must=[FieldCondition(key="slug", match=MatchValue(value=slug))])
    )


def delete_article(slug: str) -> None:
    client.delete(collection_name=COLLECTION, points_selector=_slug_filter(slug), wait=True)


def _delete_stale(slug: str, keep: set[str]) -> None:
    """Apaga pontos desse slug que nao estao entre os ids da nova versao."""
    stale: list[str] = []
    offset = None
    flt = Filter(must=[FieldCondition(key="slug", match=MatchValue(value=slug))])
    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION,
            scroll_filter=flt,
            limit=256,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        stale.extend(p.id for p in points if p.id not in keep)
        if offset is None:
            break
    if stale:
        client.delete(collection_name=COLLECTION, points_selector=stale, wait=True)


def ingest_file(path: str, force: bool = False) -> None:
    slug = slug_for(path)
    file_hash = _file_hash(path)
    if not force and _indexed_hash(slug) == file_hash:
        log(f"[skip] {slug}: inalterado")
        return

    metadata, chunks = load_document(path)
    metadata["slug"] = slug
    metadata["file_hash"] = file_hash
    if not chunks:
        log(f"[skip] {slug}: sem conteudo extraivel")
        return

    total = len(chunks)
    new_ids: list[str] = []
    batch: list[PointStruct] = []
    done = 0
    for i, chunk in enumerate(chunks):
        vector = generate_embeddings(chunk)
        if vector is None:
            continue
        pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{slug}#{i}"))
        new_ids.append(pid)
        batch.append(PointStruct(id=pid, vector=vector, payload={**metadata, "content": chunk}))
        if len(batch) >= UPSERT_BATCH:
            client.upsert(collection_name=COLLECTION, wait=True, points=batch)
            done += len(batch)
            batch = []
            log(f"[..] {slug}: {done}/{total}")

    if batch:
        client.upsert(collection_name=COLLECTION, wait=True, points=batch)
        done += len(batch)

    if not done:
        log(f"[skip] {slug}: nenhum embedding gerado")
        return

    _delete_stale(slug, keep=set(new_ids))  # limpa chunks de versoes anteriores
    log(f"[ok] {slug}: {done}/{total} chunk(s) indexado(s)")


class DebouncedHandler(FileSystemEventHandler):
    """Junta rajadas de eventos por arquivo e so age depois que ele estabiliza."""

    def __init__(self) -> None:
        self._pending: dict[str, tuple[str, float]] = {}  # path -> (acao, ultimo_evento)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _queue(self, path: str, action: str) -> None:
        if not is_doc(path):
            return
        with self._lock:
            self._pending[path] = (action, time.monotonic())

    def on_created(self, event):
        if not event.is_directory:
            self._queue(event.src_path, "ingest")

    def on_modified(self, event):
        if not event.is_directory:
            self._queue(event.src_path, "ingest")

    def on_moved(self, event):
        if event.is_directory:
            return
        self._queue(event.src_path, "delete")  # nome antigo saiu
        self._queue(event.dest_path, "ingest")  # nome novo entrou (save atomico)

    def on_deleted(self, event):
        if not event.is_directory:
            self._queue(event.src_path, "delete")

    def _run(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            ready = []
            with self._lock:
                for path, (action, ts) in list(self._pending.items()):
                    if now - ts >= DEBOUNCE_SECONDS:
                        ready.append((path, action))
                        del self._pending[path]

            for path, action in ready:
                try:
                    if action == "ingest" and os.path.exists(path):
                        if not file_is_stable(path):
                            self._queue(path, "ingest")  # ainda escrevendo, tenta depois
                            continue
                        ingest_file(path)
                    else:
                        delete_article(slug_for(path))
                        log(f"[ok] {slug_for(path)}: removido")
                except Exception as exc:  # nao derruba o observer
                    log(f"[erro] {path}: {exc}")

            time.sleep(0.5)

    def stop(self) -> None:
        self._stop.set()
        self._worker.join(timeout=2)


def _indexed_slugs() -> set[str]:
    slugs: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION, limit=256, offset=offset,
            with_payload=["slug"], with_vectors=False,
        )
        slugs.update(p.payload.get("slug") for p in points if p.payload.get("slug"))
        if offset is None:
            return slugs


def initial_sync(path: str, force: bool = False) -> None:
    if not os.path.isdir(path):
        log(f"[aviso] pasta nao existe: {path}")
        return
    files = sorted(f for f in os.listdir(path) if is_doc(f))
    log(f"[sync] {len(files)} arquivo(s) em {path}")
    for name in files:
        try:
            ingest_file(os.path.join(path, name), force=force)
        except Exception as exc:
            log(f"[erro] {name}: {exc}")

    # remove do Qdrant o que nao existe mais como arquivo na pasta
    on_disk = {slug_for(f) for f in files}
    for slug in _indexed_slugs() - on_disk:
        delete_article(slug)
        log(f"[sync] {slug}: removido (arquivo nao existe mais)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-sync", action="store_true", help="nao reindexa os arquivos existentes ao iniciar")
    parser.add_argument("--force", action="store_true", help="reindexa mesmo os arquivos inalterados")
    parser.add_argument("--path", default=DATA_DIR, help=f"pasta a observar (padrao: {DATA_DIR})")
    parser.add_argument(
        "--poll", dest="poll", action="store_true", default=None,
        help="usa polling em vez de eventos nativos (necessario no WSL observando /mnt/c)",
    )
    parser.add_argument("--no-poll", dest="poll", action="store_false", help="forca eventos nativos")
    args = parser.parse_args()

    watch_path = os.path.abspath(args.path)
    os.makedirs(watch_path, exist_ok=True)

    if not args.no_sync:
        initial_sync(watch_path, force=args.force)

    # inotify nao funciona em drives Windows montados no WSL2 (/mnt/c): usa polling la.
    use_poll = args.poll
    if use_poll is None:
        use_poll = watch_path.startswith(("/mnt/", "/media/"))

    handler = DebouncedHandler()
    observer = PollingObserver() if use_poll else Observer()
    observer.schedule(handler, watch_path, recursive=False)
    observer.start()
    mode = "polling" if use_poll else "nativo"
    log(f"[watch] observando {watch_path} ({mode})  (Ctrl+C para parar)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("\n[watch] encerrando...")
    finally:
        observer.stop()
        observer.join()
        handler.stop()


if __name__ == "__main__":
    main()
