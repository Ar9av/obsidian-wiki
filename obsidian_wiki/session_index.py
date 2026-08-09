"""Pure-stdlib TF-IDF over sessions: tokenizing, weighting, and cosine kNN.

This module decides whether the session graph is meaningful. Coding-session text
is dominated by boilerplate — "let me check the file", "I'll run the tests",
"you're right, let me fix that" — which is both high-frequency and completely
uninformative. Left alone, every session looks like every other session and the
clustering collapses into one blob.

Four independent defences, in descending order of how much work they do:

  1. Field weighting. Assistant prose is where boilerplate lives, so it carries
     the lowest weight and is heavily truncated upstream. Titles, human prompts
     and curated bookmark tags carry the topic and are weighted 3-6x.
  2. An adaptive document-frequency ceiling. Any term appearing in more than
     MAX_DF_RATIO of all sessions is deleted from the vocabulary outright. This
     is corpus-adaptive, so it catches machine-specific boilerplate (a person's
     main project name, their favourite framework) that no hand-written
     stopword list could anticipate.
  3. A hand-written agent-boilerplate stoplist, on top of English stopwords.
  4. Sublinear TF plus per-document top-N pruning. A session's identity becomes
     its most distinctive ~120 terms rather than its full boilerplate cloud.
     This is what actually sharpens the cosine similarity.

No third-party dependencies: `obsidian-wiki` ships with `dependencies = []` and
this module keeps it that way.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

# --- Weighting --------------------------------------------------------------
# What a session is "about" is carried by what the human typed and what the
# session was named — not by the assistant's narration of its own tool calls.
FIELD_WEIGHTS: dict[str, float] = {
    "title": 6.0,
    "bookmark": 5.0,
    "first_prompt": 4.0,
    "prompt": 3.0,
    "subagent": 3.0,
    "repo": 3.0,
    "project": 2.0,
    "branch": 2.0,
    "assistant": 1.0,
}

# A title derived from a truncated first prompt is far noisier than a generated
# one, so it does not get to outweigh the prompt it came from.
UNRELIABLE_TITLE_SOURCES = {"first-prompt", "history-display"}
UNRELIABLE_TITLE_WEIGHT = 4.0

MIN_DF = 3               # a term seen in fewer than 3 sessions is a typo or a one-off
MAX_DF_RATIO = 0.45      # a term in >45% of sessions carries no discriminating signal
SMALL_CORPUS_DOCS = 25   # below this the DF ceiling is not statistically meaningful
VOCAB_CAP = 30_000
TOP_TERMS_PER_DOC = 120
MAX_POSTINGS = 400       # bounds worst-case kNN cost on very common surviving terms
# A session reduced to two or three surviving terms (`ls`, `exit`, `run it`) has
# no topic. Linking it anyway would attach it to whatever shares its project
# token and inflate that cluster with noise, so it is left isolated instead.
MIN_TERMS_FOR_KNN = 5
MIN_TOKEN_LEN = 3
MAX_TOKEN_LEN = 40

# Namespaced tokens (proj:foo, repo:acme-widget) let a project anchor a cluster
# without colliding with the same word used as ordinary prose.
_META_RE = re.compile(r"\b(proj|repo|branch):([A-Za-z0-9_.\-]+)")
# Paths and dotted module names split for free here: neither `/` nor `.` is in
# the character class, so `app/api/telemetry/route.ts` yields its segments.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,39}")
_CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]{2,}(?![a-z])")

_ENGLISH_STOP = """
a about above after again against all am an and any are aren as at be because been
before being below between both but by can cannot could couldn did didn do does
doesn doing don down during each few for from further had hadn has hasn have haven
having he her here hers herself him himself his how i if in into is isn it its
itself just let me more most must my myself no nor not now of off on once only or
other ought our ours ourselves out over own re same shan she should shouldn so some
such than that the their theirs them themselves then there these they this those
through to too under until up very was wasn we were weren what when where which
while who whom why will with won would wouldn you your yours yourself yourselves
""".split()

# Terms that are frequent in *every* agent transcript regardless of topic. The
# adaptive DF ceiling catches most of these on a large corpus, but this list
# keeps small corpora (and fresh installs) sane too.
_AGENT_STOP = """
actually add added adding additional again against ahead already also alternative
always another answer anything approach appropriate around ask asked asking assistant
attempt available back based basically before begin better bit block bottom break
brief bring build building built call called calling case cases catch caused change
changed changes changing check checked checking claude clean clear code codebase
column come command commands comment commit common complete completed completely
component config configuration confirm consider console content context continue
copy correct correctly could create created creating current currently cut data
default define definitely delete deleted description detail details determine
difference different directly directory discuss display document documentation does
doing done double down draft drop due each easier easy edit edited editing either
else end ensure enter entire error errors especially even every everything exact
exactly example examples exist existing expect expected explain fail failed failing
fails false feel field file files fill final finally find finding fine finish first
fix fixed fixes fixing folder follow following format found four full function
functions further general generate generated get gets getting give given go goes
going good got great group guess handle handled handling happen happens hard help
here high hit hold hope idea if implement implementation implemented implementing
import important include included includes including indeed information initial
inline input insert inside instead interesting into issue issues item items just
keep kept key kind know known large last later latest lead least leave left less
let level like likely line lines list listed little load local logic long look
looked looking looks lot made main make makes making manual many match matches
matter maybe mean means mention mentioned message method might mind minor miss
missing mode moment more most move moved much multiple name named names necessary
need needed needs never new next nice note noted nothing notice now number object
obvious okay old once one only open option options order original other output
outside over overall page pages part particular pass passed path paths pattern
perfect perhaps piece place plan please point possible potential prefer pretty
previous print probably problem proceed process produce project proper properly
provide provided pull push put question quick quickly quite ran range rather read
reading ready real really reason recent reference regular related relevant remain
remove removed removing rename replace replaced report request require required
result results return returns review right root rule run running runs said same
save saved saw say saying script scripts search second section see seem seems seen
send sense sent separate set sets setting several share short should show shown
shows side similar simple simply since single situation small solution solve some
something sometimes soon sorry sort sound source space specific specifically spot
stage standard start started starting state statement status step steps still stop
store straight string structure stuff style suggest suggestion supported suppose
sure switch system take taken takes taking talk tell term test tested testing tests
text than thank thanks thing things think thought three through time times tiny
today together told took top total track try trying turn two type types typical
understand unless update updated updating usage use used useful uses using
usually value values variable various version very view wait want wanted wants way
exit quit stop cancel abort resume continue retry rerun again ping hey hello thx ack
ok okay sure yep nope done next prev back forward here there this that
ways well went whatever whether whole why wide will wish within without wonder word
work worked working works worth would write writes writing written wrong yeah yes
yet
""".split()

STOPWORDS: frozenset[str] = frozenset(_ENGLISH_STOP) | frozenset(_AGENT_STOP)


_HEX_CHARS = frozenset("0123456789abcdef")


def _looks_like_id(token: str) -> bool:
    """True for uuid fragments, commit sha prefixes, and other opaque ids.

    Transcripts are full of these (`d8f1c448e`, `deae261`) and they are pure
    noise: high IDF, so they score well, but they can never connect two
    sessions meaningfully. Requiring a digit keeps real hex-alphabet words
    (`added`, `decade`, `facade`) in the vocabulary.
    """
    if len(token) < 6:
        return False
    if not set(token) <= _HEX_CHARS:
        return False
    return any(c.isdigit() for c in token)


def _valid(token: str) -> bool:
    if not (MIN_TOKEN_LEN <= len(token) <= MAX_TOKEN_LEN):
        return False
    if token.isdigit() or _looks_like_id(token):
        return False
    return token not in STOPWORDS


def tokenize(text: str) -> Iterator[str]:
    """Yield normalised tokens, emitting compound identifiers whole *and* split.

    `getUserToken` yields `getusertoken`, `get`, `user`, `token`; `remote_policy`
    yields `remote_policy`, `remote`, `policy`. Keeping both means an exact
    identifier match scores strongly while a conceptual match ("policy") still
    connects sessions that never used the same symbol.
    """
    for prefix, value in _META_RE.findall(text):
        token = f"{prefix}:{value.lower()}"
        if len(token) <= MAX_TOKEN_LEN + 8:
            yield token

    for match in _WORD_RE.finditer(text):
        word = match.group(0)
        lowered = word.lower()
        if _valid(lowered):
            yield lowered
        # Split compounds only when there is something to split.
        if "_" in word or not word.islower():
            for chunk in word.split("_"):
                if not chunk:
                    continue
                for part in _CAMEL_RE.findall(chunk):
                    part = part.lower()
                    if part != lowered and _valid(part):
                        yield part


def term_weights(doc: Any) -> dict[str, float]:
    """Accumulate weighted raw term counts for one SessionDoc.

    Takes anything with `.fields` and `.title_source`, so `session_graph` can
    replay cached term maps without reconstructing full documents.
    """
    weights: dict[str, float] = defaultdict(float)
    title_source = getattr(doc, "title_source", "")
    for name, texts in (doc.fields or {}).items():
        weight = FIELD_WEIGHTS.get(name, 1.0)
        if name == "title" and title_source in UNRELIABLE_TITLE_SOURCES:
            weight = UNRELIABLE_TITLE_WEIGHT
        for text in texts:
            for token in tokenize(text):
                weights[token] += weight
    return dict(weights)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

@dataclass
class Index:
    doc_ids: list[str] = field(default_factory=list)
    idf: dict[str, float] = field(default_factory=dict)
    vectors: list[dict[str, float]] = field(default_factory=list)   # L2-normalised
    postings: dict[str, list[tuple[int, float]]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.doc_ids)


def build_index(
    term_maps: dict[str, dict[str, float]],
    *,
    min_df: int = MIN_DF,
    max_df_ratio: float = MAX_DF_RATIO,
    vocab_cap: int = VOCAB_CAP,
    top_terms: int = TOP_TERMS_PER_DOC,
) -> Index:
    """Turn raw weighted term counts into a pruned, normalised TF-IDF index."""
    doc_ids = sorted(term_maps)
    n_docs = len(doc_ids)
    index = Index(doc_ids=doc_ids)
    if n_docs == 0:
        return index

    df: dict[str, int] = defaultdict(int)
    for doc_id in doc_ids:
        for term in term_maps[doc_id]:
            df[term] += 1

    # Small corpora cannot support a min_df of 3 — nothing would survive.
    effective_min_df = min_df if n_docs >= 4 * min_df else 1
    # "Appears in 45% of documents" is only evidence of boilerplate once there
    # are enough documents for that to be a meaningful proportion. Across six
    # sessions a genuine topic term legitimately appears in half of them, so
    # below the threshold only terms present in *every* document are dropped.
    if n_docs >= SMALL_CORPUS_DOCS:
        df_ceiling = max(2, int(n_docs * max_df_ratio))
    else:
        df_ceiling = max(1, n_docs - 1)

    vocab = {t: d for t, d in df.items() if effective_min_df <= d <= df_ceiling}
    if len(vocab) > vocab_cap:
        keep = sorted(vocab, key=lambda t: -vocab[t])[:vocab_cap]
        vocab = {t: vocab[t] for t in keep}

    idf = {t: math.log((n_docs + 1) / (d + 1)) + 1.0 for t, d in vocab.items()}
    index.idf = idf

    postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for i, doc_id in enumerate(doc_ids):
        scored: list[tuple[str, float]] = []
        for term, weight in term_maps[doc_id].items():
            term_idf = idf.get(term)
            if term_idf is None or weight <= 0:
                continue
            # Sublinear TF: the tenth mention of a term says much less than the
            # first, and without this a long session outranks a focused one.
            scored.append((term, (1.0 + math.log(weight)) * term_idf))

        scored.sort(key=lambda kv: -kv[1])
        scored = scored[:top_terms]
        norm = math.sqrt(sum(v * v for _, v in scored))
        vector = {t: v / norm for t, v in scored} if norm else {}
        index.vectors.append(vector)
        for term, value in vector.items():
            postings[term].append((i, value))

    # Cap posting lists so one surviving common term cannot dominate kNN cost.
    index.postings = {
        term: sorted(plist, key=lambda p: -p[1])[:MAX_POSTINGS] if len(plist) > MAX_POSTINGS else plist
        for term, plist in postings.items()
    }
    return index


def vectorize_query(text: str, idf: dict[str, float]) -> dict[str, float]:
    """Vectorise free text against an existing IDF table."""
    raw: dict[str, float] = defaultdict(float)
    for token in tokenize(text):
        raw[token] += 1.0
    scored = {
        t: (1.0 + math.log(w)) * idf[t]
        for t, w in raw.items() if t in idf
    }
    norm = math.sqrt(sum(v * v for v in scored.values()))
    return {t: v / norm for t, v in scored.items()} if norm else {}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine of two L2-normalised sparse vectors."""
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def knn(
    index: Index,
    *,
    k: int = 8,
    min_sim: float = 0.08,
    mutual: bool = False,
) -> list[tuple[int, int, float, list[str]]]:
    """Symmetric k-nearest-neighbour edges as `(i, j, similarity, shared_terms)`.

    Scores are accumulated through the inverted index, so cost scales with the
    pruned per-document term count rather than with the corpus size.
    """
    neighbours: dict[int, dict[int, float]] = {}
    for i, vector in enumerate(index.vectors):
        if len(vector) < MIN_TERMS_FOR_KNN:
            neighbours[i] = {}
            continue
        scores: dict[int, float] = defaultdict(float)
        for term, value in vector.items():
            for j, other in index.postings.get(term, ()):
                if j != i:
                    scores[j] += value * other
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
        neighbours[i] = {j: s for j, s in top if s >= min_sim}

    edges: list[tuple[int, int, float, list[str]]] = []
    seen: set[tuple[int, int]] = set()
    for i, nbrs in neighbours.items():
        for j, sim in nbrs.items():
            pair = (i, j) if i < j else (j, i)
            if pair in seen:
                continue
            reciprocal = neighbours.get(j, {})
            if mutual and i not in reciprocal:
                continue
            seen.add(pair)
            weight = max(sim, reciprocal.get(i, 0.0))
            edges.append((pair[0], pair[1], weight, shared_terms(index, pair[0], pair[1])))

    edges.sort(key=lambda e: -e[2])
    return edges


def shared_terms(index: Index, i: int, j: int, top_n: int = 5) -> list[str]:
    """The terms contributing most to the similarity of two documents."""
    a, b = index.vectors[i], index.vectors[j]
    if len(a) > len(b):
        a, b = b, a
    contributions = [(t, v * b[t]) for t, v in a.items() if t in b]
    contributions.sort(key=lambda kv: -kv[1])
    return [t for t, _ in contributions[:top_n]]


def length_prior(vector: dict[str, float]) -> float:
    """Saturating penalty for documents too short to be trustworthy.

    L2 normalisation gives a one-term document all of its weight on that term,
    so a session whose entire surviving content is "prismor" scores a near
    perfect cosine against the query "prismor telemetry" — beating a real
    session that actually discussed both. Scaling by how much evidence the
    document has restores the ordering without discarding short sessions.
    """
    return min(1.0, len(vector) / MIN_TERMS_FOR_KNN)


def search(index: Index, qvec: dict[str, float], *, top_n: int = 50) -> list[tuple[int, float, list[str]]]:
    """Rank documents against a query vector, returning `(doc_idx, sim, terms)`."""
    if not qvec:
        return []
    scores: dict[int, float] = defaultdict(float)
    matched: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for term, value in qvec.items():
        for j, other in index.postings.get(term, ()):
            contribution = value * other
            scores[j] += contribution
            matched[j].append((term, contribution))

    for j in scores:
        scores[j] *= length_prior(index.vectors[j])

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_n]
    out = []
    for j, score in ranked:
        terms = [t for t, _ in sorted(matched[j], key=lambda kv: -kv[1])[:5]]
        out.append((j, score, terms))
    return out


def top_terms_for(index: Index, i: int, n: int = 10) -> list[str]:
    """The n highest-weight terms of a document — its readable fingerprint."""
    return [t for t, _ in sorted(index.vectors[i].items(), key=lambda kv: -kv[1])[:n]]


def iter_term_maps(docs: Iterable[Any]) -> dict[str, dict[str, float]]:
    return {doc.session_id: term_weights(doc) for doc in docs}
