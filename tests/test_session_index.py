from __future__ import annotations

import math

import pytest

from obsidian_wiki import session_index as si


class FakeDoc:
    def __init__(self, session_id, fields, title_source="ai-title"):
        self.session_id = session_id
        self.fields = fields
        self.title_source = title_source


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def test_compound_identifiers_yield_whole_and_parts():
    """Both forms are needed: the whole token matches an exact symbol reuse,
    the parts connect sessions that discussed the same concept in other words."""
    tokens = set(si.tokenize("getUserToken"))
    assert {"getusertoken", "user", "token"} <= tokens

    tokens = set(si.tokenize("remote_policy"))
    assert {"remote_policy", "remote", "policy"} <= tokens


def test_paths_split_into_segments():
    tokens = set(si.tokenize("app/api/telemetry/route.ts"))
    assert {"api", "telemetry", "route"} <= tokens


def test_dotted_module_paths_split():
    assert {"warden", "identity"} <= set(si.tokenize("warden.identity"))


def test_meta_tokens_survive_namespaced():
    tokens = set(si.tokenize("proj:bookmark-agent repo:acme-widget"))
    assert "proj:bookmark-agent" in tokens
    assert "repo:acme-widget" in tokens


@pytest.mark.parametrize("junk", ["ab", "12345", "d8f1c448e", "deae261", "the", "check", "implement"])
def test_junk_is_rejected(junk):
    """Too short, pure digits, opaque hex ids, and boilerplate all drop out."""
    assert junk not in set(si.tokenize(junk))


@pytest.mark.parametrize("word", ["decade", "facade", "deadbeef"])
def test_hex_alphabet_words_are_kept(word):
    """The id filter requires a digit, so real words spelled in [a-f] survive."""
    assert word in set(si.tokenize(word))


def test_field_weights_favour_human_text_over_assistant_prose():
    doc = FakeDoc("s", {"title": ["telemetry"], "assistant": ["telemetry"]})
    weights = si.term_weights(doc)
    assert weights["telemetry"] == si.FIELD_WEIGHTS["title"] + si.FIELD_WEIGHTS["assistant"]


def test_unreliable_title_is_downweighted():
    """A title derived from a truncated first prompt must not outweigh a real one."""
    good = si.term_weights(FakeDoc("a", {"title": ["telemetry"]}, "ai-title"))
    weak = si.term_weights(FakeDoc("b", {"title": ["telemetry"]}, "first-prompt"))
    assert weak["telemetry"] < good["telemetry"]


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

BOILERPLATE = (
    "Let me check the file and run the tests. I will fix the error and "
    "update the code. Perfect, that works now."
)

TELEMETRY = [
    "add telemetry batching to the warden runtime with a redacted sink",
    "the telemetry sink drops spans under load, add warden batching retries",
    "warden telemetry chain signing broke, redacted spans never reach the sink",
]
SPRITES = [
    "slice the generated sprite sheet into aligned animation frames",
    "the sprite sheet flood fill leaves halos around each animation frame",
    "generate a sprite sheet and slice it into frames for the walk animation",
]


@pytest.fixture
def corpus():
    """Six documents, two topics, and identical boilerplate in every one.

    This is the shape of the real problem: the boilerplate is the single most
    frequent text in the corpus, so any indexer that does not actively suppress
    it will report all six documents as mutually similar.
    """
    docs = []
    for i, text in enumerate(TELEMETRY):
        docs.append(FakeDoc(f"tel{i}", {"first_prompt": [text], "assistant": [BOILERPLATE]}))
    for i, text in enumerate(SPRITES):
        docs.append(FakeDoc(f"spr{i}", {"first_prompt": [text], "assistant": [BOILERPLATE]}))
    return docs


def test_boilerplate_is_excluded_from_the_vocabulary(corpus):
    """The document-frequency ceiling must delete terms common to every session."""
    index = si.build_index(si.iter_term_maps(corpus))
    for term in ("file", "tests", "code", "works"):
        assert term not in index.idf


def test_intra_topic_similarity_beats_inter_topic(corpus):
    index = si.build_index(si.iter_term_maps(corpus))
    pos = {d: i for i, d in enumerate(index.doc_ids)}
    same = si.cosine(index.vectors[pos["tel0"]], index.vectors[pos["tel1"]])
    cross = si.cosine(index.vectors[pos["tel0"]], index.vectors[pos["spr0"]])
    assert same > cross
    assert cross < 0.1


def test_vectors_are_normalised_and_pruned(corpus):
    index = si.build_index(si.iter_term_maps(corpus))
    for vector in index.vectors:
        assert len(vector) <= si.TOP_TERMS_PER_DOC
        assert math.isclose(math.sqrt(sum(v * v for v in vector.values())), 1.0, rel_tol=1e-9)


def test_knn_links_only_within_a_topic(corpus):
    """The payoff test: neighbours must respect topic, not shared boilerplate."""
    index = si.build_index(si.iter_term_maps(corpus))
    edges = si.knn(index, k=2, min_sim=0.05)
    assert edges
    for i, j, weight, shared in edges:
        assert index.doc_ids[i][:3] == index.doc_ids[j][:3], (
            f"cross-topic edge {index.doc_ids[i]}–{index.doc_ids[j]} via {shared}")
        assert weight > 0


def test_hapax_terms_are_dropped_on_a_large_corpus():
    """min_df only applies once the corpus is big enough to support it."""
    docs = [FakeDoc(f"d{i}", {"prompt": [f"shared telemetry policy unique{i}"]}) for i in range(20)]
    index = si.build_index(si.iter_term_maps(docs))
    assert "unique0" not in index.idf


def test_sparse_documents_are_left_unlinked(corpus):
    """`ls` and `exit` sessions have no topic and must not join a cluster."""
    corpus.append(FakeDoc("junk", {"project": ["proj:scratch"]}))
    index = si.build_index(si.iter_term_maps(corpus))
    edges = si.knn(index, k=3, min_sim=0.01)
    junk = index.doc_ids.index("junk")
    assert all(junk not in (i, j) for i, j, _, _ in edges)


def test_search_ranks_the_right_topic(corpus):
    index = si.build_index(si.iter_term_maps(corpus))
    hits = si.search(index, si.vectorize_query("warden telemetry sink", index.idf), top_n=3)
    assert hits
    assert index.doc_ids[hits[0][0]].startswith("tel")


def test_empty_corpus_is_handled():
    index = si.build_index({})
    assert len(index) == 0
    assert si.knn(index) == []
    assert si.search(index, {}) == []
