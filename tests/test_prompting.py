"""dedupe_passages / build_prompt de basic_rag.py -- a parte do RAG que decide o
que vai pro modelo. E aqui que vive a causa raiz do incidente de alucinacao:
um prompt em XML (<retrieved-data>) fazia o Mistral 7B ecoar a propria estrutura
do prompt em vez de responder. Os testes abaixo travam esse comportamento."""
from types import SimpleNamespace

import basic_rag as b


def _point(slug, content, score=0.5):
    return SimpleNamespace(payload={"slug": slug, "content": content}, score=score)


# ---------- dedupe_passages ----------

def test_dedupe_passages_keeps_distinct_points():
    points = [_point("a", "Conteudo do primeiro trecho."), _point("a", "Conteudo bem diferente aqui.")]
    passages = b.dedupe_passages(points)
    assert len(passages) == 2


def test_dedupe_passages_drops_near_duplicates_by_prefix():
    # mesmo inicio (80 primeiros chars) -- tipico de PDF que duplica pagina
    texto_longo = "Este texto se repete quase identico " * 5
    points = [_point("x", texto_longo), _point("x", texto_longo + " com um final levemente diferente")]
    passages = b.dedupe_passages(points)
    assert len(passages) == 1


def test_dedupe_passages_normalizes_whitespace():
    points = [_point("x", "linha um\n\nlinha   dois   com espacos")]
    _, texto, _ = b.dedupe_passages(points)[0]
    assert "\n" not in texto
    assert "  " not in texto


def test_dedupe_passages_preserves_slug_and_score():
    points = [_point("meu-slug", "algum conteudo de teste aqui.", score=0.876)]
    slug, _, score = b.dedupe_passages(points)[0]
    assert slug == "meu-slug"
    assert score == 0.876


# ---------- build_prompt ----------

def test_build_prompt_contains_question_and_context():
    passages = [("artigo-x", "trecho relevante sobre o tema perguntado", 0.9)]
    prompt = b.build_prompt(passages, "qual a pergunta do usuario?")
    assert "qual a pergunta do usuario?" in prompt
    assert "trecho relevante sobre o tema perguntado" in prompt
    assert "artigo-x" in prompt


def test_build_prompt_has_decline_instruction():
    prompt = b.build_prompt([("a", "x", 0.1)], "pergunta qualquer")
    assert "Não encontrei isso nos documentos." in prompt


def test_build_prompt_forces_portuguese_answer():
    prompt = b.build_prompt([("a", "x", 0.1)], "question in english")
    assert "português do brasil" in prompt.lower() or "portugues do brasil" in prompt.lower()


def test_build_prompt_never_reintroduces_the_xml_wrapper():
    """Regressao direta do incidente: o Mistral ecoava <retrieved-data> em vez
    de responder quando o prompt usava esse wrapper com contexto ruim."""
    prompt = b.build_prompt([("a", "algum trecho", 0.1)], "pergunta")
    assert "<retrieved-data>" not in prompt
    assert "<user-prompt>" not in prompt


def test_build_prompt_with_empty_context_still_has_decline_path():
    # nenhum trecho recuperado (busca vazia / colecao vazia) -- o modelo ainda
    # deve ser instruido a admitir que nao sabe, nao inventar
    prompt = b.build_prompt([], "pergunta sem nenhum trecho encontrado")
    assert "Não encontrei isso nos documentos." in prompt
    assert "CONTEXTO:\n\n" in prompt  # contexto vazio, mas a secao existe
