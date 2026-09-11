"""ingest_file / delete_article / initial_sync contra o FakeQdrantClient (sem
Qdrant nem Ollama de verdade -- ver conftest.py)."""
import watch_data as w


def _write(tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text)
    return str(f)


# dois paragrafos longos o bastante (juntos > CHUNK_TARGET) pra virarem 2 chunks
CONTEUDO_A = (
    "Titulo A\n\n"
    + ("Primeiro paragrafo com bastante conteudo repetido para garantir tamanho suficiente. " * 8)
    + "\n\n"
    + ("Segundo paragrafo tambem com bastante texto relevante para o teste de ingestao aqui. " * 8)
)
CONTEUDO_A_MENOR = (
    "Titulo A\n\n"
    "Unico paragrafo restante depois de uma edicao que encolheu bastante o arquivo original."
)


def test_ingest_file_indexes_all_chunks(tmp_path, patched_client, fake_embeddings):
    path = _write(tmp_path, "a.md", CONTEUDO_A)
    w.ingest_file(path)

    points, _ = patched_client.scroll(w.COLLECTION, limit=100)
    assert len(points) >= 2
    assert all(p.payload["slug"] == "a" for p in points)
    assert all(p.payload["source"] == "a.md" for p in points)
    assert all("file_hash" in p.payload for p in points)


def test_ingest_file_skips_when_file_unchanged(tmp_path, patched_client, fake_embeddings):
    path = _write(tmp_path, "a.md", CONTEUDO_A)
    w.ingest_file(path)
    n_embed_calls = len(fake_embeddings)

    w.ingest_file(path)  # mesmo conteudo: nao deve reprocessar
    assert len(fake_embeddings) == n_embed_calls


def test_ingest_file_reprocesses_when_content_changes(tmp_path, patched_client, fake_embeddings):
    path = _write(tmp_path, "a.md", CONTEUDO_A)
    w.ingest_file(path)
    n_embed_calls = len(fake_embeddings)

    _write(tmp_path, "a.md", CONTEUDO_A_MENOR)
    w.ingest_file(path)
    assert len(fake_embeddings) > n_embed_calls


def test_ingest_file_force_reprocesses_even_if_unchanged(tmp_path, patched_client, fake_embeddings):
    path = _write(tmp_path, "a.md", CONTEUDO_A)
    w.ingest_file(path)
    n_embed_calls = len(fake_embeddings)

    w.ingest_file(path, force=True)
    assert len(fake_embeddings) > n_embed_calls


def test_ingest_file_removes_orphan_chunks_when_file_shrinks(tmp_path, patched_client, fake_embeddings):
    path = _write(tmp_path, "a.md", CONTEUDO_A)
    w.ingest_file(path)
    pontos_antes, _ = patched_client.scroll(w.COLLECTION, limit=100)
    assert len(pontos_antes) >= 2

    _write(tmp_path, "a.md", CONTEUDO_A_MENOR)
    w.ingest_file(path)

    pontos_depois, _ = patched_client.scroll(w.COLLECTION, limit=100)
    assert len(pontos_depois) == 1
    assert "Unico paragrafo restante" in pontos_depois[0].payload["content"]


def test_delete_article_removes_only_that_slug(tmp_path, patched_client, fake_embeddings):
    w.ingest_file(_write(tmp_path, "a.md", CONTEUDO_A))
    w.ingest_file(_write(tmp_path, "b.md", CONTEUDO_A.replace("Titulo A", "Titulo B")))

    w.delete_article("a")

    restantes, _ = patched_client.scroll(w.COLLECTION, limit=100)
    assert restantes and all(p.payload["slug"] == "b" for p in restantes)


def test_initial_sync_indexes_every_supported_file(tmp_path, patched_client, fake_embeddings):
    _write(tmp_path, "a.md", CONTEUDO_A)
    _write(tmp_path, "b.mdx", CONTEUDO_A.replace("Titulo A", "Titulo B"))
    _write(tmp_path, "ignorar.txt", "isso nao deveria ser indexado de jeito nenhum")

    w.initial_sync(str(tmp_path))

    slugs = {p.payload["slug"] for p in patched_client.scroll(w.COLLECTION, limit=100)[0]}
    assert slugs == {"a", "b"}


def test_initial_sync_prunes_slugs_without_a_file(tmp_path, patched_client, fake_embeddings):
    w.ingest_file(_write(tmp_path, "a.md", CONTEUDO_A))
    (tmp_path / "a.md").unlink()  # arquivo sumiu, mas os pontos continuam no Qdrant

    w.initial_sync(str(tmp_path))

    pontos, _ = patched_client.scroll(w.COLLECTION, limit=100)
    assert pontos == []


def test_initial_sync_on_missing_folder_does_not_raise(patched_client):
    w.initial_sync("/pasta/que/nao/existe/com/certeza")  # so nao deve levantar excecao
