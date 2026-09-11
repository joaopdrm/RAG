#!/usr/bin/env bash
# Sobe o Qdrant (via Docker) e o watcher de ingestao (watch_data.py).
#
#   ./start.sh                 sincroniza data/ e fica observando
#   ./start.sh --no-sync       so observa mudancas novas
#   ./start.sh --force         reindexa tudo
#   ./start.sh stop            derruba o container do Qdrant
#
# O Qdrant continua rodando depois que voce fecha o watcher (Ctrl+C).

set -euo pipefail
cd "$(dirname "$0")"

# ativa a venv se existir (opcional: os comandos abaixo ja chamam env/bin/python direto)
[ -f env/bin/activate ] && source env/bin/activate

QDRANT_NAME="rag-qdrant"
QDRANT_STORAGE="$PWD/qdrant_storage"
PYTHON="env/bin/python"

# docker desta maquina (snap) precisa de sudo; descobre isso uma vez
if command docker version >/dev/null 2>&1; then
    DOCKER=(docker)
elif sudo docker version >/dev/null 2>&1; then
    DOCKER=(sudo docker)
else
    echo "[erro] sem acesso ao Docker. Inicie o daemon (ou rode com um usuario no grupo docker)." >&2
    exit 1
fi

if [ "${1:-}" = "stop" ]; then
    echo "[qdrant] parando $QDRANT_NAME"
    "${DOCKER[@]}" stop "$QDRANT_NAME" >/dev/null 2>&1 || true
    exit 0
fi

# 1. Qdrant
if [ -n "$("${DOCKER[@]}" ps -q -f "name=^${QDRANT_NAME}$")" ]; then
    echo "[qdrant] ja esta rodando"
elif [ -n "$("${DOCKER[@]}" ps -aq -f "name=^${QDRANT_NAME}$")" ]; then
    echo "[qdrant] reiniciando container existente"
    "${DOCKER[@]}" start "$QDRANT_NAME" >/dev/null
else
    echo "[qdrant] criando container (dados em $QDRANT_STORAGE)"
    mkdir -p "$QDRANT_STORAGE"
    "${DOCKER[@]}" run -d --name "$QDRANT_NAME" \
        -p 6333:6333 -p 6334:6334 \
        -v "$QDRANT_STORAGE:/qdrant/storage" \
        qdrant/qdrant >/dev/null
fi

# 2. espera o Qdrant aceitar conexao
printf "[qdrant] aguardando ficar pronto"
for _ in $(seq 1 30); do
    curl -sf http://localhost:6333/readyz >/dev/null 2>&1 && { echo " ok"; break; }
    printf "."
    sleep 1
done

# 3. Ollama roda fora do Docker; so avisa se estiver fora do ar
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "[aviso] Ollama nao responde em localhost:11434 -- inicie o Ollama antes de indexar"
fi

# 4. watcher em foreground (o Qdrant continua no ar ao sair)
echo "[watch] iniciando watch_data.py (Ctrl+C para parar; o Qdrant segue rodando)"
exec "$PYTHON" watch_data.py "$@"
