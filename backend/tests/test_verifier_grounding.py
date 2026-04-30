from __future__ import annotations

from app.agents.verifier import _mentions_unsupported_source


def test_mentions_unsupported_source_detects_source_mismatch_language() -> None:
    assert _mentions_unsupported_source(
        "This fact is correct, but the answer is not derived from the provided sources."
    )
    assert _mentions_unsupported_source(
        "The justification notes the irrelevance of the provided sources."
    )


def test_mentions_unsupported_source_allows_supported_language() -> None:
    assert not _mentions_unsupported_source(
        "The source states that each daughter DNA molecule has one original strand."
    )
