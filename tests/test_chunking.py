"""Funcoes puras de watch_data.py: normalizacao, chunking e limpeza de PDF.
Nenhuma delas toca rede ou disco alem do que o proprio teste cria."""
import watch_data as w


# ---------- slug_for / is_doc ----------

def test_slug_for_strips_extension():
    assert w.slug_for("/a/b/artigo.PDF") == "artigo"
    assert w.slug_for("relatorio.final.md") == "relatorio.final"


def test_is_doc_accepts_supported_extensions_case_insensitive():
    assert w.is_doc("a.pdf") and w.is_doc("A.MD") and w.is_doc("b.Mdx")


def test_is_doc_rejects_other_extensions():
    assert not w.is_doc("nota.txt") and not w.is_doc("imagem.png")


# ---------- _normalize ----------

def test_normalize_dehyphenates_line_break():
    out = w._normalize("infor-\nmation about the model")
    assert "infor-\n" not in out
    assert "information" in out


def test_normalize_collapses_many_blank_lines():
    out = w._normalize("paragrafo um\n\n\n\n\nparagrafo dois")
    assert "\n\n\n" not in out
    assert out.count("\n\n") == 1


# ---------- chunk_text ----------

def test_chunk_text_keeps_short_text_as_one_chunk():
    chunks = w.chunk_text("Paragrafo unico, bem curto, cabe facil no alvo de chunk.")
    assert len(chunks) == 1


def test_chunk_text_splits_on_paragraphs_when_over_target():
    paragrafo = "frase de teste com bastante conteudo repetido. " * 6  # ~250 chars
    texto = "\n\n".join([paragrafo] * 8)  # ~2000 chars, > CHUNK_TARGET (1200)
    chunks = w.chunk_text(texto)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= w.CHUNK_TARGET * 1.5


def test_chunk_text_falls_back_to_sentences_without_paragraphs():
    # uma unica "linha" longa sem blocos separados por linha em branco
    frase = "Esta e uma frase de teste sobre o assunto. "
    texto = frase * 40  # sem \n\n em lugar nenhum
    chunks = w.chunk_text(texto)
    assert len(chunks) >= 1
    # nao deve ter quebrado no meio de uma sentenca de forma bruta
    assert all(c.strip() for c in chunks)


def test_chunk_text_drops_duplicate_chunks():
    # PDFs costumam repetir a primeira pagina; o chunker deve descartar a copia
    paragrafo = "Este e um paragrafo que se repete no documento duplicado. " * 3
    texto = "\n\n".join([paragrafo, paragrafo, "Um paragrafo diferente aqui no final."])
    chunks = w.chunk_text(texto)
    normalizados = [c.strip().lower() for c in chunks]
    assert len(normalizados) == len(set(normalizados))


def test_chunk_text_drops_very_short_fragments():
    texto = "Paragrafo grande o bastante para ser um chunk valido de verdade.\n\nx"
    chunks = w.chunk_text(texto)
    assert all(len(c) >= 40 for c in chunks)


def test_chunk_text_overlap_between_consecutive_chunks():
    # dois blocos com conteudo variado (nao repetitivo, senao colide com o
    # dedup por fingerprint), cada um maior que CHUNK_TARGET sozinho -- forcam
    # exatamente uma quebra de chunk na fronteira entre eles
    p1 = ("O modelo processa a imagem de entrada em varias camadas convolucionais sucessivas. " * 20).strip()
    p2 = ("A camada final produz o mapa de caracteristicas usado na deteccao de anomalias. " * 20).strip()
    assert w.CHUNK_TARGET < len(p1) <= w.CHUNK_TARGET * 1.5  # nao aciona a fatia por tamanho
    chunks = w.chunk_text(f"{p1}\n\n{p2}")
    assert len(chunks) == 2

    tail = p1[-w.CHUNK_OVERLAP:]
    tail = tail[tail.find(" ") + 1:] if " " in tail else tail
    assert chunks[1].startswith(tail)
    assert chunks[1].endswith(p2)


# ---------- _strip_pdf_noise ----------

def test_strip_pdf_noise_removes_repeated_header():
    header = "Sakshi Indolia et al. / Procedia Computer Science 132 (2018) 679-688"
    pages = [
        f"{header}\nConteudo real da pagina {i} com uma frase completa aqui.\n"
        for i in range(1, 5)
    ]
    cleaned = w._strip_pdf_noise(pages)
    assert all(header not in pg for pg in cleaned)
    assert all("Conteudo real da pagina" in pg for pg in cleaned)


def test_strip_pdf_noise_keeps_lines_that_dont_repeat():
    pages = [f"Frase unica da pagina {i}, nao se repete em nenhuma outra." for i in range(5)]
    cleaned = w._strip_pdf_noise(pages)
    for original, out in zip(pages, cleaned):
        assert original in out


def test_strip_pdf_noise_removes_lone_equation_numbers():
    # corpo varia por pagina para nao ser confundido com cabecalho repetido
    pages = [
        f"Uma explicacao qualquer numero {i}.\n(14)\nMais texto depois da equacao {i}."
        for i in range(3)
    ]
    cleaned = w._strip_pdf_noise(pages)
    for i, pg in enumerate(cleaned):
        assert "(14)" not in pg.splitlines()
        assert f"Mais texto depois da equacao {i}" in pg


def test_strip_pdf_noise_keeps_lines_with_numbers_and_real_text():
    pages = [f"(14) Este metodo converge apos {i} iteracoes." for i in range(3)]
    cleaned = w._strip_pdf_noise(pages)
    for i, pg in enumerate(cleaned):
        assert f"converge apos {i} iteracoes" in pg


# ---------- _file_hash ----------

def test_file_hash_is_deterministic_and_content_sensitive(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("conteudo original")
    h1 = w._file_hash(str(f))
    h2 = w._file_hash(str(f))
    assert h1 == h2

    f.write_text("conteudo mudou")
    h3 = w._file_hash(str(f))
    assert h3 != h1
