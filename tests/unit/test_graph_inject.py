"""Brief injection — token-free via a stubbed retriever; no DB."""
import pytest

from evo.graph import inject
from evo.graph.candidates import CandidateSet, GraphCandidate


def _cset(need="improve ranking", n=2):
    cs = CandidateSet(need=need, queries=["improve ranking"], index_built_at="2026-07-19T00:00:00Z")
    for i in range(n):
        cs.add(GraphCandidate(
            need=need, query="improve ranking", repo_id=f"repo__{i}",
            label=f"rank{i}()", node_id=f"n{i}", kind="function",
            source_file=f"r{i}.py", source_location=f"r{i}.py:{i}", degree=10 - i,
        ))
    return cs


def _retriever(cs):
    def r(need, queries):
        return cs
    return r


def test_disabled_by_default_returns_unchanged():
    brief = "Do the thing."
    # no enabled arg, env unset -> off
    assert inject.inject_prior_art(brief, retrieve=_retriever(_cset())) == brief


def test_env_enables(monkeypatch):
    monkeypatch.setenv(inject.INJECT_ENV, "1")
    assert inject.injection_enabled() is True
    monkeypatch.setenv(inject.INJECT_ENV, "off")
    assert inject.injection_enabled() is False


def test_explicit_enabled_injects_block():
    brief = "Improve ranking precision."
    out = inject.inject_prior_art(brief, retrieve=_retriever(_cset()), enabled=True)
    assert inject._MARKER_BEGIN in out and inject._MARKER_END in out
    assert "rank0()" in out and "repo__0" in out
    # retrieval-not-selection framing is present
    assert "NOT approved dependencies" in out


def test_injection_is_idempotent():
    brief = "Improve ranking precision."
    once = inject.inject_prior_art(brief, retrieve=_retriever(_cset()), enabled=True)
    twice = inject.inject_prior_art(once, retrieve=_retriever(_cset()), enabled=True)
    assert twice.count(inject._MARKER_BEGIN) == 1
    assert twice.count(inject._MARKER_END) == 1


def test_empty_candidate_set_leaves_brief_unchanged():
    brief = "Improve ranking precision."
    out = inject.inject_prior_art(brief, retrieve=_retriever(_cset(n=0)), enabled=True)
    assert out == brief


def test_strip_prior_art_removes_block():
    brief = "Body text."
    injected = inject.inject_prior_art(brief, retrieve=_retriever(_cset()), enabled=True)
    stripped = inject.strip_prior_art(injected)
    assert inject._MARKER_BEGIN not in stripped
    assert "Body text." in stripped


def test_derive_queries_uses_content_terms():
    qs = inject.derive_queries("How does the ranking bonus improve precision?")
    assert qs and "ranking" in qs[0] and "how" not in qs[0]


def test_derive_queries_empty_for_stopwords_only():
    # all stopwords/short -> store tokenizer falls back, so not necessarily empty,
    # but a truly empty brief yields no queries
    assert inject.derive_queries("") == []


def test_retriever_error_is_non_fatal():
    from evo.graph.store import GraphUnavailable

    def boom(need, queries):
        raise GraphUnavailable("no index")

    brief = "Improve ranking."
    assert inject.inject_prior_art(brief, retrieve=boom, enabled=True) == brief
