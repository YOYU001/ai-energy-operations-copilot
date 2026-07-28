"""Step 10 Sub-step 2: embedding provider abstraction, ported unchanged from
spike/embedding_provider.py (Step 6 Sub-step 4).

Per docs/DECISIONS.md ADR-004, the embedding provider must not be hardcoded
into core RAG logic and every embedded chunk's metadata must record which
model/version produced it. OpenAIEmbeddingProvider is the only concrete
implementation, but callers depend only on the EmbeddingProvider protocol.

This sub-step keeps the retry loop's blocking time.sleep as-is (matching the
spike exactly) -- whether ingestion ends up calling this from a sync or async
code path is an orchestration decision left to Sub-step 3, not decided here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingResult:
    text: str
    vector: list[float]
    provider: str
    model: str
    dimensions: int
    model_version: str | None  # null when the API does not return a distinct version


@dataclass(frozen=True)
class EmbeddingBatchResult:
    results: list[EmbeddingResult]
    prompt_tokens: int | None
    total_tokens: int | None


class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str
    dimensions: int

    def embed_batch(self, texts: list[str]) -> EmbeddingBatchResult: ...


class EmbeddingBatchError(RuntimeError):
    """Raised when a batch could not be embedded after all retries.

    Deliberately its own exception type so callers can distinguish "this
    batch failed and nothing in it was written" from any other error --
    partial success within a failed batch must never happen (see the
    ingestion service, Sub-step 3, which only writes rows for batches that
    returned successfully).
    """


class OpenAIEmbeddingProvider:
    """Wraps the OpenAI embeddings API. Requires OPENAI_API_KEY in the
    environment (loaded via python-dotenv by the caller, exactly like
    backend/app/db.py does for DATABASE_URL) -- never pass a key literal."""

    provider_name = "openai"

    def __init__(self, model: str = "text-embedding-3-small", dimensions: int = 1536, max_retries: int = 3, client=None):
        self.model_name = model
        self.dimensions = dimensions
        self.max_retries = max_retries
        if client is not None:
            self._client = client  # test hook: inject a stub instead of a real OpenAI() client
        else:
            from openai import OpenAI  # imported lazily so tests can mock without requiring the package at import time

            self._client = OpenAI()

    def embed_batch(self, texts: list[str]) -> EmbeddingBatchResult:
        if not texts:
            return EmbeddingBatchResult(results=[], prompt_tokens=0, total_tokens=0)

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self._client.embeddings.create(model=self.model_name, input=texts)
                results = [
                    EmbeddingResult(
                        text=texts[i],
                        vector=list(item.embedding),
                        provider=self.provider_name,
                        model=response.model,
                        dimensions=len(item.embedding),
                        model_version=None,  # OpenAI's embeddings API does not return a separate version field
                    )
                    for i, item in enumerate(response.data)
                ]
                usage = getattr(response, "usage", None)
                return EmbeddingBatchResult(
                    results=results,
                    prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
                    total_tokens=getattr(usage, "total_tokens", None) if usage else None,
                )
            except Exception as exc:  # noqa: BLE001 -- intentionally broad, matches spike's fail-closed retry
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2**attempt)
        # All retries exhausted: raise, do not return a partial/empty result
        # that a caller could mistake for "zero chunks needed embedding".
        raise EmbeddingBatchError(f"embedding batch of {len(texts)} texts failed after {self.max_retries} attempts") from last_error
