"""Tests for Step 6 Sub-step 4 embedding provider (mocked client, no network).

Run from the project root: python -m pytest spike/tests -v
"""

import pytest

from spike.embedding_provider import EmbeddingBatchError, OpenAIEmbeddingProvider


class _FakeUsage:
    def __init__(self, prompt_tokens, total_tokens):
        self.prompt_tokens = prompt_tokens
        self.total_tokens = total_tokens


class _FakeEmbeddingItem:
    def __init__(self, vector):
        self.embedding = vector


class _FakeResponse:
    def __init__(self, model, vectors, prompt_tokens, total_tokens):
        self.model = model
        self.data = [_FakeEmbeddingItem(v) for v in vectors]
        self.usage = _FakeUsage(prompt_tokens, total_tokens)


class _FakeEmbeddingsResource:
    def __init__(self, responses=None, error_until_attempt=None):
        self._responses = list(responses) if responses is not None else []
        self.calls = []
        self._error_until_attempt = error_until_attempt
        self._attempt = 0

    def create(self, model, input):
        self.calls.append({"model": model, "input": list(input)})
        if self._error_until_attempt is not None and self._attempt < self._error_until_attempt:
            self._attempt += 1
            raise RuntimeError("simulated transient API error")
        return self._responses.pop(0)


class _FakeOpenAIClient:
    def __init__(self, embeddings_resource):
        self.embeddings = embeddings_resource


def test_embed_batch_returns_vectors_with_metadata_and_null_version():
    fake_response = _FakeResponse(
        model="text-embedding-3-small",
        vectors=[[0.1, 0.2], [0.3, 0.4]],
        prompt_tokens=5,
        total_tokens=5,
    )
    client = _FakeOpenAIClient(_FakeEmbeddingsResource(responses=[fake_response]))
    provider = OpenAIEmbeddingProvider(client=client)

    result = provider.embed_batch(["a", "b"])

    assert len(result.results) == 2
    assert result.results[0].vector == [0.1, 0.2]
    assert result.results[0].model == "text-embedding-3-small"
    assert result.results[0].model_version is None  # API does not return a distinct version
    assert result.prompt_tokens == 5
    assert result.total_tokens == 5


def test_embed_batch_empty_input_makes_no_api_call():
    resource = _FakeEmbeddingsResource(responses=[])
    provider = OpenAIEmbeddingProvider(client=_FakeOpenAIClient(resource))

    result = provider.embed_batch([])

    assert result.results == []
    assert len(resource.calls) == 0


def test_embed_batch_retries_transient_errors_then_succeeds():
    fake_response = _FakeResponse(model="text-embedding-3-small", vectors=[[0.5]], prompt_tokens=1, total_tokens=1)
    resource = _FakeEmbeddingsResource(responses=[fake_response], error_until_attempt=2)
    provider = OpenAIEmbeddingProvider(client=_FakeOpenAIClient(resource), max_retries=3)

    result = provider.embed_batch(["x"])

    assert len(result.results) == 1
    assert len(resource.calls) == 3  # 2 failures + 1 success


def test_embed_batch_raises_after_exhausting_retries_no_partial_result():
    resource = _FakeEmbeddingsResource(responses=[], error_until_attempt=10)
    provider = OpenAIEmbeddingProvider(client=_FakeOpenAIClient(resource), max_retries=2)

    with pytest.raises(EmbeddingBatchError):
        provider.embed_batch(["x", "y"])
