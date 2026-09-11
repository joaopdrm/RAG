"""load_document() para .md/.mdx (leitura real de arquivo) e .pdf (PdfReader
trocado por um fake -- nao depende de pypdf conseguir abrir um binario real)."""
from types import SimpleNamespace

import watch_data as w


def test_load_document_mdx_without_front_matter(tmp_path):
    # chunk_text descarta chunks com menos de 40 chars, entao o conteudo de
    # teste precisa ser longo o bastante pra sobreviver ao filtro
    f = tmp_path / "shrek.mdx"
    f.write_text(
        "SHREK\n\n"
        "Once upon a time there was a princess locked in a tower far away.\n\n"
        "A dragon guarded the castle every single day and night without rest."
    )
    meta, chunks = w.load_document(str(f))
    assert meta["title"] == "SHREK"
    assert meta["source"] == "shrek.mdx"
    assert any("princess locked in a tower" in c for c in chunks)


def test_load_document_mdx_with_front_matter(tmp_path):
    f = tmp_path / "artigo.mdx"
    f.write_text(
        '---\ntitle: "Artigo de Teste"\nauthor: Joao\n---\n'
        "Conteudo do artigo aqui, com texto suficiente para nao ser descartado pelo chunker."
    )
    meta, chunks = w.load_document(str(f))
    assert meta["title"] == "Artigo de Teste"
    assert meta["author"] == "Joao"
    assert any("Conteudo do artigo" in c for c in chunks)


def test_load_document_defaults_title_and_source_to_filename(tmp_path):
    f = tmp_path / "notas.md"
    # extract_metadata_from_mdx sempre preenche title/source pela 1a linha/nome de
    # arquivo, mas load_document tambem tem esse fallback -- confirma que existe
    f.write_text("Notas\n\nAlgum conteudo relevante para o teste.")
    meta, _ = w.load_document(str(f))
    assert meta["source"] == "notas.md"


class _FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakeInfo:
    def __init__(self, title=None, author=None):
        self.title = title
        self.author = author


class _FakePdfReader:
    """Substitui pypdf.PdfReader: mesma interface (.pages, .metadata), sem
    precisar de um PDF binario de verdade nem da lib instalada."""
    def __init__(self, path):
        self.pages = [
            _FakePage("Titulo Do Artigo\n\nIntroducao com conteudo real sobre o tema."),
            _FakePage("Segunda pagina com mais conteudo relevante para indexar."),
        ]
        self.metadata = _FakeInfo(title="Titulo Vindo Do PDF", author="Autor X")


def test_load_document_pdf_uses_metadata_and_extracts_text(monkeypatch):
    monkeypatch.setattr(w, "PdfReader", _FakePdfReader)
    meta, chunks = w.load_document("qualquer/caminho.pdf")
    assert meta["title"] == "Titulo Vindo Do PDF"
    assert meta["author"] == "Autor X"
    assert meta["pages"] == 2
    assert any("Introducao com conteudo real" in c for c in chunks)
    assert any("Segunda pagina" in c for c in chunks)


def test_load_document_pdf_without_reader_raises_clear_error(monkeypatch):
    monkeypatch.setattr(w, "PdfReader", None)
    try:
        w.load_document("algum.pdf")
        assert False, "deveria ter levantado RuntimeError"
    except RuntimeError as exc:
        assert "pypdf" in str(exc)


def test_read_pdf_collapses_one_word_per_line_pages(monkeypatch):
    """Exportadores tipo Google Docs quebram cada palavra numa linha; _read_pdf
    deve colapsar isso pra nao virar um chunk por palavra."""
    quebrado = "\n".join(["Esta", "e", "uma", "frase", "quebrada", "palavra", "por", "palavra."])

    class _Reader:
        def __init__(self, path):
            self.pages = [_FakePage(quebrado)]
            self.metadata = SimpleNamespace(title=None, author=None)

    monkeypatch.setattr(w, "PdfReader", _Reader)
    _, text = w._read_pdf("qualquer.pdf")
    assert "\nE\nu\nm\na\n" not in text  # nao quebrou letra por letra
    assert "Esta e uma frase quebrada palavra por palavra." in text
