"""Per-deal in-memory RAG for extraction.

The portfolio-search feature owns the persistent ChromaDB collection; extraction
does not need persistence — a deal is extracted once per upload and the chunks
exist only for the duration of that extraction. So this module embeds the
deal's chunks into a numpy matrix in memory, supports top-K cosine search, and
disappears when the `DealCorpus` is garbage-collected. No collection lifecycle,
no cross-deal pollution, no Chroma involvement here.

Reuses the existing section-header chunker (`index.chunk_contract`) and the
existing batched embedder (`index.embed_texts`).
"""

from __future__ import annotations

import numpy as np
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from index import EMBEDDING_MODEL, chunk_contract, embed_texts

from deal_copilot.intake import LoadedDoc


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class RetrievedChunk(BaseModel):
    """One chunk returned by `DealCorpus.search` — text + metadata + distance."""
    model_config = ConfigDict(extra="forbid")

    text: str
    filename: str
    section_number: int
    section_title: str
    distance: float = Field(description="1 − cosine similarity. Lower = better match.")


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalization. Safe against zero vectors."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return matrix / norms


class DealCorpus:
    """In-memory chunked + embedded view of a deal's documents.

    Construction embeds every chunk once. Subsequent `search` calls embed the
    query and compute cosine via a single matrix-vector dot product.

    Memory footprint for the Phase 1 synthetic deal: ~33 chunks × 1536 dims ×
    4 bytes ≈ 200 KB. Trivial.
    """

    def __init__(self, client: OpenAI, loaded_docs: list[LoadedDoc]) -> None:
        self._client = client
        self._chunks: list[dict] = []
        for doc in loaded_docs:
            self._chunks.extend(chunk_contract(doc.text, doc.filename))

        if not self._chunks:
            self._embeddings = np.zeros((0, 0), dtype=np.float32)
            return

        texts = [c["text"] for c in self._chunks]
        raw = embed_texts(client, texts)
        # Stack and L2-normalize so a dot product = cosine similarity.
        self._embeddings = _l2_normalize(np.asarray(raw, dtype=np.float32))

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """Top-K chunks by cosine similarity to the query."""
        if self.chunk_count == 0:
            return []

        # Embed and normalize the query.
        q_resp = self._client.embeddings.create(model=EMBEDDING_MODEL, input=query)
        q_vec = np.asarray(q_resp.data[0].embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return []
        q_vec = q_vec / q_norm

        # cosine = dot product of normalized vectors.
        sims = self._embeddings @ q_vec
        k = min(top_k, self.chunk_count)
        # argpartition for top-k; reorder by similarity descending.
        top_idx = np.argpartition(-sims, k - 1)[:k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]

        results: list[RetrievedChunk] = []
        for i in top_idx:
            i = int(i)
            chunk = self._chunks[i]
            meta = chunk["metadata"]
            results.append(RetrievedChunk(
                text=chunk["text"],
                filename=meta["contract_name"],
                section_number=int(meta["section_number"]),
                section_title=meta["section_title"],
                distance=float(1.0 - sims[i]),
            ))
        return results


__all__ = ["RetrievedChunk", "DealCorpus"]
