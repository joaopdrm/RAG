"""Fixtures compartilhadas. Nenhum teste aqui toca a rede: Qdrant e Ollama sao
substituidos por fakes, entao a suite roda sem nenhum servico externo no ar
(condicao real do runner de CI)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from qdrant_client.models import FilterSelector


class FakePoint:
    def __init__(self, id, vector, payload, score=None):
        self.id = id
        self.vector = vector
        self.payload = payload
        self.score = score


class FakeQdrantClient:
    """Reimplementa, em memoria, so o que este projeto usa do QdrantClient:
    upsert/scroll/delete/count/query_points e filtro Filter(must=[FieldCondition
    (key=.., match=MatchValue(value=..))]) -- a unica forma de filtro usada no
    codigo. Nao faz busca vetorial de verdade: query_points so devolve pontos.
    """

    def __init__(self):
        self.collections: dict[str, dict] = {}

    def _coll(self, name):
        return self.collections.setdefault(name, {})

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, collection_name, **_):
        self.collections.setdefault(collection_name, {})

    @staticmethod
    def _matches(payload, flt) -> bool:
        if flt is None:
            return True
        for cond in flt.must:
            if (payload or {}).get(cond.key) != cond.match.value:
                return False
        return True

    def count(self, collection_name):
        return SimpleNamespace(count=len(self._coll(collection_name)))

    def upsert(self, collection_name, points, wait=True):
        coll = self._coll(collection_name)
        for p in points:
            coll[p.id] = FakePoint(p.id, p.vector, dict(p.payload))

    def scroll(self, collection_name, scroll_filter=None, limit=100, offset=None,
               with_payload=True, with_vectors=True):
        coll = self._coll(collection_name)
        items = sorted(coll.values(), key=lambda p: str(p.id))
        items = [p for p in items if self._matches(p.payload, scroll_filter)]
        start = offset or 0
        page = items[start:start + limit]
        next_offset = start + limit if start + limit < len(items) else None

        out = []
        for p in page:
            payload = p.payload
            if isinstance(with_payload, list):
                payload = {k: payload.get(k) for k in with_payload}
            elif not with_payload:
                payload = None
            out.append(FakePoint(p.id, p.vector if with_vectors else None, payload))
        return out, next_offset

    def delete(self, collection_name, points_selector, wait=True):
        coll = self._coll(collection_name)
        if isinstance(points_selector, FilterSelector):
            to_delete = [pid for pid, p in coll.items()
                         if self._matches(p.payload, points_selector.filter)]
        else:
            to_delete = list(points_selector)
        for pid in to_delete:
            coll.pop(pid, None)

    def query_points(self, collection_name, query, with_payload=True, limit=10):
        points = list(self._coll(collection_name).values())[:limit]
        return SimpleNamespace(points=points)


@pytest.fixture
def fake_qdrant():
    return FakeQdrantClient()


@pytest.fixture
def patched_client(monkeypatch, fake_qdrant):
    """Aponta o `client` global de basic_rag, watch_data e ab_test para o fake.

    Cada um fez `from basic_rag import client`, entao e um nome separado no
    namespace de cada modulo -- os tres precisam ser corrigidos.
    """
    import ab_test
    import basic_rag
    import watch_data

    monkeypatch.setattr(basic_rag, "client", fake_qdrant, raising=True)
    monkeypatch.setattr(watch_data, "client", fake_qdrant, raising=True)
    monkeypatch.setattr(ab_test, "client", fake_qdrant, raising=True)
    return fake_qdrant


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Substitui watch_data.generate_embeddings por um vetor deterministico
    (hash do texto), sem chamar o Ollama. Devolve a lista de chamadas feitas."""
    import watch_data

    calls: list[str] = []

    def _fake(text: str):
        calls.append(text)
        return [float(len(text) % 7)] * 4

    monkeypatch.setattr(watch_data, "generate_embeddings", _fake, raising=True)
    return calls
