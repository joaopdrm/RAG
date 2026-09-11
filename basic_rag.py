import requests
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import yaml
import re
import os
import sys

# cores ANSI (desligadas se a saida nao for um terminal, ex. piped para arquivo)
_TTY = sys.stdout.isatty()
CYAN = "\033[36m" if _TTY else ""
DIM = "\033[2m" if _TTY else ""
BOLD = "\033[1m" if _TTY else ""
OFF = "\033[0m" if _TTY else ""

client = QdrantClient(url="http://localhost:6333")

if not client.collection_exists(collection_name="articles"):
    client.create_collection(
        collection_name="articles",
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
    )

# dummy_data = [
#     "joao",
#     "Joao ama isabela",
#     "Laila ama Joao"
# ]

def extract_metadata_from_mdx(file_path: str):
    with open(file_path, "r", encoding="utf-8") as file:
        content = file.read()

    # Tenta extrair front matter
    if content.startswith("---"):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            try:
                metadata = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                metadata = {}
            return metadata, parts[2].strip()

    # Sem front matter: usa a primeira linha como título
    lines = content.strip().split('\n')
    title = lines[0].strip()
    metadata = {"title": title, "source": os.path.basename(file_path)}
    article_content = '\n'.join(lines[1:]).strip()

    return metadata, article_content

def create_chunks(article_content: str):
    chunks = []
    for chunk in article_content.split('\n\n'):
        chunks.append(chunk)
    return chunks

def clean_article_content(article_content: str):
    # Remove import statements
    cleaned_content = re.sub(r"^import .*\n?", "",
                             article_content, flags=re.MULTILINE)
    # Remove XML/HTML tags but keep content
    cleaned_content = re.sub(r"<[^>]+>", "", cleaned_content)
    return cleaned_content.strip()

# Modelo de geração. mistral:7b não cabe em GPU/RAM pequena; troque por um 2-3B
# (ex. "llama3.2:3b", "qwen2.5:3b-instruct", "gemma2:2b") se der erro de memória.
GEN_MODEL = "mistral:7b-instruct-q4_K_M"


def generate_response(prompt: str) -> str:
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": GEN_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": 4096},
        },
        timeout=600,
    )
    data = response.json()
    if "response" not in data:
        # Ollama devolve {"error": "..."} quando o modelo não carrega (falta de VRAM/RAM, etc.)
        raise RuntimeError(data.get("error", data))
    return data["response"]

def generate_embeddings(text: str):
    response = requests.post(
        "http://localhost:11434/api/embed",
        json={"model": "mxbai-embed-large:335m", "input": text},
    )
    if len(response.json()["embeddings"]) > 0:
        return response.json()["embeddings"][0]
    else:
        return None
       
def store_article(start_id: int, metadata: dict, chunks: list[str]):
    for i, chunk in enumerate(chunks):
        embbed = generate_embeddings(chunk)
        client.upsert(
            collection_name="articles",
            wait=True,
            points=[PointStruct(
                id=start_id + i,
                vector=embbed,
                payload={**metadata, "content": chunk}
            )]
        )
        print(f"  Chunk {i+1}/{len(chunks)}")
    return start_id + len(chunks)  # retorna próximo ID disponível

def indexed_docs():
    """(total_de_pontos, {slug: titulo}) da colecao articles; (0, {}) se o Qdrant cair."""
    try:
        total = client.count(collection_name="articles").count
        points, _ = client.scroll(
            collection_name="articles", limit=10000,
            with_payload=["slug", "title"], with_vectors=False,
        )
    except Exception:
        return 0, {}
    docs = {}
    for p in points:
        payload = p.payload or {}
        slug = payload.get("slug", "?")
        docs.setdefault(slug, payload.get("title") or slug)
    return total, docs


def print_intro():
    w = 60
    titulo = "RAG local - pergunte sobre os artigos no database"
    print(f"\n{CYAN}╭{'─' * w}╮")
    print(f"│{titulo.center(w)}│")
    print(f"╰{'─' * w}╯{OFF}\n")

    print(f"{BOLD}Como perguntar{OFF}")
    print(f"  {DIM}·{OFF} seja específico e cite o tema ou o artigo")
    print(f'    {DIM}"é sobre drift?"  ->  "como o método detecta concept drift sem rótulos?"{OFF}')
    print(f"  {DIM}·{OFF} pode ser em português ou inglês")
    print(f"  {DIM}·{OFF} pergunte só o que os documentos cobrem\n")

    print(f"{BOLD}Confira a resposta{OFF}")
    print(f"  {DIM}·{OFF} ela mistura os trechos recuperados com o que o modelo já sabe de treino")
    print(f'  {DIM}·{OFF} peça "cite o trecho"; para testar, pergunte algo fora dos artigos')

    print(f"{BOLD}Sair{OFF}  {DIM}·{OFF}  digite  exit  ou  q\n")

    total, docs = indexed_docs()
    if docs:
        print(f"{DIM}{len(docs)} documento(s), {total} trecho(s) indexado(s):{OFF}")
        for nome in docs.values():
            print(f"{DIM}   · {nome[:58]}{OFF}")
    else:
        print(f"{DIM}nenhum documento indexado - rode  ./start.sh  ou  watch_data.py{OFF}")
    print()


def main():
    print_intro()
    # articles = "C:/projetos/rag/data"
    # article_files = [f for f in os.listdir(articles) if f.endswith(".mdx")]
    # point_id = 0  # contador global

    # for article_file in article_files:
    #     file_path = os.path.join(articles, article_file)
    #     try:
    #         metadata, article_content = extract_metadata_from_mdx(file_path)
    #         metadata["slug"] = article_file.replace(".mdx", "")
    #         cleaned_article = clean_article_content(article_content)
    #         chunks = create_chunks(cleaned_article)
    #         point_id = store_article(point_id, metadata, chunks)
    #         print(f"Processado: {article_file}")
    #     except Exception as e:
    #         print(f"Error processing {article_file}: {e}")
    while True:
        try:
            prompt = input(f"{CYAN}❯{OFF} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt:
            continue
        if prompt.lower() in ("exit", "q", "sair"):
            break
        # Este prefixo vai para o EMBEDDING (só afeta a busca). Mantenha mínimo:
        # o idioma da resposta se controla no prompt de geração, não aqui.
        # mxbai-embed-large é multilíngue, então a pergunta pode ser em PT.
        adjusted_prompt = f"Represent this sentence for searching relevant passages: {prompt}"

        response = requests.post(
            "http://localhost:11434/api/embed",
            json={"model": "mxbai-embed-large:335m", "input": adjusted_prompt},
        )
        embeddings = response.json()["embeddings"][0]

        results = client.query_points(
            collection_name="articles",
            query=embeddings,
            with_payload=True,
            limit=8,
        )

        # remove trechos duplicados/quase iguais e mostra o que foi recuperado
        contexto, vistos = [], set()
        for point in results.points:
            texto = " ".join(point.payload["content"].split())
            chave = texto[:80].lower()
            if chave in vistos:
                continue
            vistos.add(chave)
            contexto.append(f"[{point.payload['slug']}] {texto}")
            print(f"{DIM}  · {point.score:.3f}  {texto[:90]}{OFF}")

        augmented_prompt = (
            "Você responde perguntas sobre artigos científicos usando SOMENTE o "
            "contexto abaixo. Se o contexto não contiver a resposta, responda apenas: "
            '"Não encontrei isso nos documentos." Não repita o contexto. '
            "Responda sempre e unicamente em português do Brasil, independentemente do idioma da pergunta ou do contexto recuperado.\n\n"
            f"CONTEXTO:\n{chr(10).join(contexto)}\n\n"
            f"PERGUNTA: {prompt}\n\n"
            "RESPOSTA:"
        )

        print()
        try:
            print(generate_response(augmented_prompt).strip())
        except Exception as exc:
            print(f"{DIM}[erro na geração] {exc}{OFF}")
            print(f"{DIM}os trechos acima já respondem; veja GEN_MODEL em basic_rag.py "
                  f"se for falta de memória.{OFF}")
        print("\n")

if __name__ == "__main__":
    main()