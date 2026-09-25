# RAG

RAG local para consultar artigos em PDF/Markdown em linguagem natural. Roda inteiramente
na sua máquina: [Qdrant](https://qdrant.tech/) como banco vetorial e [Ollama](https://ollama.com/)
para embeddings e geração. Nenhum dado sai da máquina.

Projeto de estudo, não uma ferramenta de produção — veja [Limitações](#limitações) antes
de confiar nas respostas.

## Como funciona

```
data/*.pdf, *.md, *.mdx
        │
        ▼
  watch_data.py ──► extrai texto, divide em chunks, gera embedding (Ollama),
  (watchdog)         grava no Qdrant. Reindexa só o que mudou (hash SHA-256).
        │
        ▼
     Qdrant (coleção "articles")
        │
        ▼
  basic_rag.py ──► pergunta → embedding → busca no Qdrant → monta um prompt
  (loop de pergunta) com os trechos recuperados → Ollama gera a resposta em pt-BR,
                     citando os artigos usados.
```

- **Ingestão** (`watch_data.py`): observa a pasta `data/`. Um arquivo novo é dividido em
  chunks (~1200 caracteres, com sobreposição), embedado e indexado; editar reindexa só
  aquele arquivo; apagar remove os vetores. PDFs passam por uma limpeza extra (remove
  cabeçalho repetido, numeração de equação solta, texto quebrado palavra-por-palavra em
  exports do Google Docs).
- **Consulta** (`basic_rag.py`): loop interativo. Busca os trechos mais relevantes,
  monta um prompt com esses trechos como contexto e instrui o modelo a responder só com
  base neles — e a admitir quando não sabe, em vez de inventar.
- **Checagem de alucinação** (`ab_test.py`): responde a mesma pergunta com e sem os
  trechos recuperados, pra comparar se a resposta está de fato ancorada no contexto ou
  vindo do conhecimento geral do modelo.

## Requisitos

- Python 3.10+
- [Docker](https://www.docker.com/) (pra rodar o Qdrant) ou uma instância Qdrant já no ar
- [Ollama](https://ollama.com/) com os modelos:
  ```
  ollama pull mxbai-embed-large:335m
  ollama pull mistral:7b-instruct-q4_K_M
  ```
  `mistral:7b` precisa de ~4.4 GB de RAM/VRAM. Numa máquina mais modesta, troque o
  `GEN_MODEL` em `basic_rag.py` por algo menor (`llama3.2:3b`, `qwen2.5:3b-instruct`,
  `gemma2:2b`).

## Instalação

```bash
python -m venv env
source env/bin/activate        # Windows: env\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
./start.sh                  # sobe o Qdrant (Docker) + o watcher; sincroniza data/ e observa
# ou, com o Qdrant já rodando em outro lugar:
python watch_data.py        # ingestão: sincroniza data/ e continua observando
python watch_data.py --force       # reindexa tudo, ignorando o cache de hash
python watch_data.py --no-sync     # só observa, sem sincronizar no início

python basic_rag.py         # loop de pergunta (não indexa nada; "exit"/"q" pra sair)
python ab_test.py "pergunta"       # resposta com e sem contexto, lado a lado
python ab_test.py                  # roda um conjunto de perguntas padrão
```

Coloque os arquivos (`.pdf`, `.md`, `.mdx`) em `data/`.

## Testes

```bash
pytest -q
```

Não depende de Qdrant nem Ollama rodando — os testes usam um cliente Qdrant e chamadas
ao Ollama falsos (veja `tests/conftest.py`).

## Estrutura

| Arquivo | |
|---|---|
| `watch_data.py` | ingestão: extrai, divide em chunks, embeda e indexa `data/` |
| `basic_rag.py` | loop de pergunta e resposta; também expõe as funções de contexto/prompt reaproveitadas pelos outros scripts |
| `ab_test.py` | checagem manual de ancoragem (com/sem contexto) |
| `start.sh` | sobe Qdrant (Docker) + roda o watcher |
| `main.py` | versão inicial/experimental, mantida como referência |
| `tests/` | suíte pytest, com fakes pro Qdrant e Ollama |

## Limitações

- É um projeto de aprendizado sobre RAG, não algo revisado para produção.
- A resposta depende da qualidade da extração de PDF e da busca vetorial; sempre
  desconfie e confira contra o documento original.
- Sem autenticação, sem multiusuário — pensado pra rodar localmente, pra uso pessoal.

## Licença

[MIT](LICENSE)
