"""Teste A/B do RAG: a mesma pergunta respondida COM e SEM os trechos recuperados.

Para que serve: checar se o modelo responde a partir dos documentos ou de memoria
(treino). Se a resposta COM contexto for parecida com a SEM contexto, o modelo esta
"alucinando" com conhecimento proprio. Se forem bem diferentes -- e a versao COM
contexto bater com os trechos exibidos -- o RAG esta ancorado.

Inclui de proposito uma pergunta fora do escopo do corpus (custo em FLOPs); a versao
COM contexto deveria admitir que nao sabe, a versao SEM contexto provavelmente inventa.

Uso:
    env/bin/python ab_test.py "sua pergunta"
    env/bin/python ab_test.py                 # roda o conjunto padrao
"""
import sys

import requests

from basic_rag import client, generate_response

EMBED_MODEL = "mxbai-embed-large:335m"
COLLECTION = "articles"
TOP_K = 10

PERGUNTAS_PADRAO = [
    "Como o metodo detecta concept drift sem usar rotulos?",
    "Quais as limitacoes do metodo em relacao ao DriftLens?",
    "Qual o custo computacional do metodo em FLOPs?",  # fora do escopo: deve admitir que nao sabe
]


def embed(text: str) -> list[float]:
    resp = requests.post(
        "http://localhost:11434/api/embed",
        json={"model": EMBED_MODEL, "input": text},
    )
    return resp.json()["embeddings"][0]


def retrieve(question: str):
    query = f"Represent this sentence for searching relevant passages: {question}"
    return client.query_points(
        collection_name=COLLECTION, query=embed(query), with_payload=True, limit=TOP_K
    ).points


def answer_with_context(question: str, points) -> str:
    passages = "\n".join(
        f"- Article Title: {p.payload['title']} -- Article Slug: {p.payload['slug']}"
        f" -- Article Content: {p.payload['content']}"
        for p in points
    )
    prompt = f"""
    The following are relevant passages:
    <retrieved-data>
    {passages}
    </retrieved-data>

    Here's the original user prompt, answer with help of the retrieved passages.
    <user-prompt>
    {question}
    </user-prompt>
    """
    return generate_response(prompt).strip()


def answer_without_context(question: str) -> str:
    return generate_response(f"Answer this question objectively:\n{question}").strip()


def run(question: str) -> None:
    print("=" * 72)
    print("PERGUNTA:", question)
    print("=" * 72)

    points = retrieve(question)
    print(f"\nTrechos recuperados (top {TOP_K}, por score):")
    for p in points:
        preview = " ".join(p.payload["content"].split())[:110]
        print(f"  [{p.score:.3f}] {p.payload['slug']}: {preview}")

    print("\n--- A) COM contexto (RAG) ---")
    print(answer_with_context(question, points))

    print("\n--- B) SEM contexto (so o modelo) ---")
    print(answer_without_context(question))
    print()


def main() -> None:
    if len(sys.argv) > 1:
        run(" ".join(sys.argv[1:]))
    else:
        for pergunta in PERGUNTAS_PADRAO:
            run(pergunta)


if __name__ == "__main__":
    main()
