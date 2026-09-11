"""ab_test.py: retrieve/answer_with_context/answer_without_context, com Qdrant e
Ollama trocados por fakes. Nao roda o experimento de verdade (isso e o proprio
ab_test.py, pensado pra rodar manualmente com os servicos no ar) -- so garante
que a montagem do prompt e a leitura dos trechos estao corretas."""
from types import SimpleNamespace

import ab_test as at


def _point(slug, content, score=0.5):
    return SimpleNamespace(payload={"slug": slug, "content": content, "title": slug}, score=score)


def test_retrieve_embeds_question_and_queries_the_collection(monkeypatch, patched_client):
    captured = {}

    def fake_post(url, json=None):
        captured["url"] = url
        captured["input"] = json["input"]
        return SimpleNamespace(json=lambda: {"embeddings": [[0.1, 0.2, 0.3]]})

    monkeypatch.setattr(at.requests, "post", fake_post)
    patched_client.upsert(
        at.COLLECTION, points=[SimpleNamespace(id="1", vector=[0.1, 0.2, 0.3], payload={"slug": "a", "content": "x"})]
    )

    points = at.retrieve("minha pergunta")

    assert "minha pergunta" in captured["input"]
    assert "localhost:11434/api/embed" in captured["url"]
    assert len(points) == 1


def test_answer_with_context_uses_build_prompt_not_xml(monkeypatch):
    captured = {}

    def fake_generate_response(prompt):
        captured["prompt"] = prompt
        return "resposta gerada"

    monkeypatch.setattr(at, "generate_response", fake_generate_response)

    points = [_point("artigo-1", "trecho A sobre o assunto"), _point("artigo-1", "trecho A sobre o assunto")]
    resposta = at.answer_with_context("qual a pergunta?", points)

    assert resposta == "resposta gerada"
    assert "qual a pergunta?" in captured["prompt"]
    assert "trecho A sobre o assunto" in captured["prompt"]
    assert "<retrieved-data>" not in captured["prompt"]  # regressao: nao volta ao formato antigo
    # os dois pontos sao quase identicos: dedupe_passages deve ter cortado um
    assert captured["prompt"].count("trecho A sobre o assunto") == 1


def test_answer_without_context_does_not_leak_any_passage(monkeypatch):
    captured = {}

    def fake_generate_response(prompt):
        captured["prompt"] = prompt
        return "resposta sem contexto"

    monkeypatch.setattr(at, "generate_response", fake_generate_response)

    resposta = at.answer_without_context("pergunta isolada")

    assert resposta == "resposta sem contexto"
    assert "pergunta isolada" in captured["prompt"]
    assert "CONTEXTO" not in captured["prompt"]
    assert "artigo" not in captured["prompt"].lower()


def test_with_and_without_context_prompts_are_meaningfully_different(monkeypatch):
    """O ponto do A/B: os dois prompts enviados ao modelo devem ser bem
    diferentes -- um carrega o contexto recuperado, o outro nao carrega nada."""
    prompts = []
    monkeypatch.setattr(at, "generate_response", lambda p: (prompts.append(p), "ok")[1])

    points = [_point("artigo-x", "informação exclusiva que só existe nos documentos")]
    at.answer_with_context("pergunta", points)
    at.answer_without_context("pergunta")

    com_contexto, sem_contexto = prompts
    assert "informação exclusiva que só existe nos documentos" in com_contexto
    assert "informação exclusiva que só existe nos documentos" not in sem_contexto
