"""The optional decision layer (obsidian_wiki/decisions.py).

No test touches the network: the HTTP backend talks to a fake System One
server on 127.0.0.1, and the rest use an in-process scripted backend.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict

import pytest

from obsidian_wiki import decisions as d
from obsidian_wiki.graphrag import query

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo-vault"
FAKE_KEY = "ts-test-key-0123456789abcdef-never-real"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def cfg(**kw: Any) -> d.DecisionConfig:
    kw.setdefault("enabled", True)
    return d.DecisionConfig(**kw)


def noul(p: float) -> Dict[str, Any]:
    return {"type": "noul", "noul": p}


def choice(probs: Dict[str, float]) -> Dict[str, Any]:
    top = max(probs, key=probs.get)
    return {"type": "choice", "choice": top, "confidence": probs[top], "probabilities": probs}


class Scripted(d.DecisionBackend):
    """In-process backend: answers = fn(state, questions)."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, fn: Callable[[Any, Dict[str, Any]], Dict[str, Any]]) -> None:
        self.fn = fn
        self.calls: list = []

    def ask(self, state, questions):
        self.calls.append((state, questions))
        return d.BackendAnswer(model=self.model, answers=self.fn(state, questions),
                               usage={"input_tokens": 10, "output_tokens": 1}, latency_ms=1.5)


class Failing(d.DecisionBackend):
    name = "failing"
    model = "x"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def ask(self, state, questions):
        raise d.DecisionError(self.reason)


def by_title(state: Dict[str, Any]) -> Dict[str, str]:
    """pid -> title, so scripted answers can key on content, not on shuffled ids."""
    return {pid: page["title"] for pid, page in state["pages"].items()}


class FakeSystemOne:
    """A loopback HTTP server speaking the /v1/systemone shape."""

    def __init__(self, respond: Callable[[Dict[str, Any]], tuple]) -> None:
        self.respond = respond
        self.requests: list = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                status, payload, delay = outer.respond(body)
                if delay:
                    time.sleep(delay)
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):  # keep test output clean
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_server():
    servers = []

    def make(respond):
        server = FakeSystemOne(respond)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


CANDS = [
    {"page": "concepts/a.md", "title": "Alpha", "summary": "about alpha", "tags": ["x"]},
    {"page": "concepts/b.md", "title": "Beta", "summary": "about beta", "tags": []},
    {"page": "concepts/c.md", "title": "Gamma", "summary": "about gamma", "tags": []},
    {"page": "concepts/d.md", "title": "Delta", "summary": "about delta", "tags": []},
]


def gate_answers(p_by_title: Dict[str, float]):
    def fn(state, questions):
        titles = by_title(state)
        return {f"rel_{pid}": noul(p_by_title[t]) for pid, t in titles.items()}
    return fn


# ---------------------------------------------------------------------------
# Config: off by default, explicit opt-in, tolerant env, strict flags
# ---------------------------------------------------------------------------


def test_off_by_default():
    c = d.DecisionConfig.from_env({})
    assert c.enabled is False
    assert c.thresholds() == {"act": 0.9, "confirm": 0.5}
    assert c.model == "jev-1.14.0"


@pytest.mark.parametrize("value", ["typesafe", "on", "1", "TypeSafe"])
def test_env_opt_in(value):
    c = d.DecisionConfig.from_env({d.ENV_MODE: value})
    assert c.enabled is True and c.backend == "typesafe"


@pytest.mark.parametrize("value", ["", "off", "0", "false", "none"])
def test_env_off_values(value):
    assert d.DecisionConfig.from_env({d.ENV_MODE: value}).enabled is False


def test_flag_overrides_env_both_ways():
    assert d.DecisionConfig.from_env({}, enabled=True).enabled is True
    assert d.DecisionConfig.from_env({d.ENV_MODE: "typesafe"}, enabled=False).enabled is False


def test_bad_env_numbers_fall_back_with_warning():
    c = d.DecisionConfig.from_env({d.ENV_ACT: "high", d.ENV_CONFIRM: "0.95", d.ENV_TIMEOUT: "-1"})
    assert c.act == 0.9 and c.confirm == 0.5 and c.timeout == d.DEFAULT_TIMEOUT
    assert len(c.warnings) >= 2


def test_env_thresholds_are_configurable():
    c = d.DecisionConfig.from_env({d.ENV_ACT: "0.8", d.ENV_CONFIRM: "0.3"})
    assert c.thresholds() == {"act": 0.8, "confirm": 0.3}


def test_flag_values_are_validated_strictly():
    with pytest.raises(ValueError):
        d.DecisionConfig.from_env({}, act=1.5)
    with pytest.raises(ValueError):
        d.DecisionConfig.from_env({}, act=0.4, confirm=0.6)


def test_unknown_backend_fails_open():
    c = d.DecisionConfig.from_env({d.ENV_MODE: "local"})
    assert c.enabled and c.backend == "local"
    out = d.relevance_gate("q", CANDS, c, env={})
    assert out["decision"]["failed_open"] and out["decision"]["reason"] == "unknown_backend"
    assert out["candidates"] == CANDS


def test_status_reports_key_presence_never_value():
    s = d.status(d.DecisionConfig.from_env({}), env={d.ENV_KEY: FAKE_KEY})
    assert s["key_present"] is True
    assert FAKE_KEY not in json.dumps(s)


def test_band_edges():
    c = cfg()
    assert d.band(0.9, c) == "act" and d.band(0.89, c) == "confirm"
    assert d.band(0.5, c) == "confirm" and d.band(0.49, c) == "fallback"
    assert d.noul_confidence(0.95) == pytest.approx(0.9)
    assert d.noul_confidence(0.5) == 0.0


def test_scrub_masks_credentials():
    text = "mail me@example.com key sk-abcdefghijklmnop1234 at https://u:pw@host/x " + "f" * 40
    out = d.scrub(text, 500)
    assert "me@example.com" not in out and "sk-abc" not in out and "u:pw" not in out
    assert "f" * 40 not in out
    assert "[token]" in d.scrub("token " + "zQ9xK2" * 8, 500)
    slug = "where-agent-memory-should-live-and-why-it-matters-most"
    assert d.scrub(slug, 500) == slug
    assert len(d.scrub("word " * 50, 10)) == 10


# ---------------------------------------------------------------------------
# The HTTP backend against a loopback fake server
# ---------------------------------------------------------------------------


def test_http_request_shape_and_auth(fake_server):
    def respond(body):
        answers = {qid: noul(0.97) for qid in body["questions"]}
        return 200, {"model": "jev-1.14.0", "answers": answers, "usage": {"input_tokens": 50, "output_tokens": 4}}, 0

    server = fake_server(respond)
    c = cfg(base_url=server.url)
    out = d.relevance_gate("what is alpha", CANDS, c, env={d.ENV_KEY: FAKE_KEY})
    (req,) = server.requests
    assert req["path"] == "/v1/systemone"
    assert req["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    body = req["body"]
    assert set(body) == {"model", "state", "questions"}
    assert body["model"] == "jev-1.14.0"
    assert all(q["type"] == "noul" and set(q["criteria"]) == {"true", "false"} for q in body["questions"].values())
    rec = out["decision"]
    assert rec["backend"] == "typesafe" and rec["model"] == "jev-1.14.0"
    assert rec["latency_ms"] is not None and rec["latency_ms"] >= 0
    assert rec["thresholds"] == {"act": 0.9, "confirm": 0.5}
    assert rec["failed_open"] is False and rec["sent"] is True
    assert rec["usage"]["input_tokens"] == 50
    assert FAKE_KEY not in json.dumps(out)


def test_http_payload_is_minimal(fake_server):
    server = fake_server(lambda body: (200, {"model": "m", "answers": {q: noul(0.5) for q in body["questions"]},
                                             "usage": {}}, 0))
    cands = [dict(c) for c in CANDS]
    cands[0]["summary"] = "contact owner@example.com for details"
    cands[0]["body"] = "SECRET BODY TEXT"
    d.relevance_gate("alpha", cands, cfg(base_url=server.url), env={d.ENV_KEY: FAKE_KEY})
    sent = json.dumps(server.requests[0]["body"])
    assert "concepts/" not in sent  # no paths
    assert "SECRET BODY TEXT" not in sent  # no bodies
    assert "owner@example.com" not in sent  # masked
    assert set(server.requests[0]["body"]["state"]["pages"]) == {"P0", "P1", "P2", "P3"}


@pytest.mark.parametrize(
    "status,payload,reason",
    [
        (500, {"detail": "boom"}, "http_500"),
        (401, {"detail": "bad key"}, "http_401"),
        (429, {"detail": "slow down"}, "http_429"),
        (200, b"not json", "invalid_response"),
        (200, {"model": "m"}, "invalid_response"),
        (200, {"model": "m", "answers": {}, "usage": {}}, "invalid_answer"),
    ],
)
def test_http_failures_fail_open(fake_server, status, payload, reason):
    server = fake_server(lambda body: (status, payload, 0))
    out = d.relevance_gate("alpha", CANDS, cfg(base_url=server.url), env={d.ENV_KEY: FAKE_KEY})
    assert out["candidates"] == CANDS and out["dropped"] == []
    assert out["decision"]["failed_open"] is True
    assert out["decision"]["reason"] == reason
    assert FAKE_KEY not in json.dumps(out)
    assert out["decision"]["sent"] is True  # the backend answered, so the request reached it


def test_http_redirect_is_refused_and_key_not_forwarded(fake_server):
    target = fake_server(lambda body: (200, {"model": "m", "answers": {}, "usage": {}}, 0))

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.send_response(302)
            self.send_header("Location", target.url + "/v1/systemone")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        out = d.relevance_gate("alpha", CANDS, cfg(base_url=url), env={d.ENV_KEY: FAKE_KEY})
    finally:
        server.shutdown()
        server.server_close()
    assert out["decision"]["reason"] == "http_302" and out["decision"]["failed_open"]
    assert target.requests == []  # the key never reached the redirect target


def test_scrub_is_linear_on_a_long_unbroken_run():
    started = time.perf_counter()
    d.scrub("A" * 200_000, 1500)
    assert time.perf_counter() - started < 1.0


def test_http_timeout_fails_open(fake_server):
    server = fake_server(lambda body: (200, {"model": "m", "answers": {}, "usage": {}}, 1.0))
    started = time.perf_counter()
    out = d.relevance_gate("alpha", CANDS, cfg(base_url=server.url, timeout=0.2), env={d.ENV_KEY: FAKE_KEY})
    assert time.perf_counter() - started < 0.9
    assert out["decision"]["reason"] == "timeout" and out["decision"]["failed_open"]
    assert out["decision"]["sent"] is None  # may or may not have reached the backend
    assert out["candidates"] == CANDS


def test_wrong_answer_type_or_range_fails_open():
    for bad in (lambda s, q: {k: {"type": "choice"} for k in q},
                lambda s, q: {k: noul(1.7) for k in q},
                lambda s, q: {k: noul(float("nan")) for k in q},
                lambda s, q: {k: {"type": "noul", "noul": True} for k in q}):
        out = d.relevance_gate("alpha", CANDS, cfg(), backend=Scripted(bad))
        assert out["decision"]["reason"] == "invalid_answer"
        assert out["candidates"] == CANDS


def test_missing_key_never_calls_network(fake_server):
    server = fake_server(lambda body: (200, {}, 0))
    out = d.relevance_gate("alpha", CANDS, cfg(base_url=server.url), env={})
    assert out["decision"]["reason"] == "missing_key" and out["decision"]["sent"] is False
    assert server.requests == []


def test_plain_http_to_remote_host_refused():
    with pytest.raises(d.DecisionError) as err:
        d.TypeSafeBackend(FAKE_KEY, base_url="http://api.example.com")
    assert err.value.reason == "insecure_url"
    assert FAKE_KEY not in repr(d.TypeSafeBackend(FAKE_KEY))


# ---------------------------------------------------------------------------
# D1 relevance gate
# ---------------------------------------------------------------------------


def test_gate_bands():
    backend = Scripted(gate_answers({"Alpha": 0.6, "Beta": 0.02, "Gamma": 0.99, "Delta": 0.15}))
    out = d.relevance_gate("q", CANDS, cfg(), backend=backend)
    pages = [c["page"] for c in out["candidates"]]
    # Gamma (act, relevant) moves to the front; Beta (act, irrelevant) is dropped;
    # Alpha (fallback) and Delta (confirm) stay in lexical order.
    assert pages == ["concepts/c.md", "concepts/a.md", "concepts/d.md"]
    assert [c["page"] for c in out["dropped"]] == ["concepts/b.md"]
    verdicts = {c["title"]: c["decision"]["verdict"] for c in out["candidates"] + out["dropped"]}
    assert verdicts == {"Gamma": "relevant", "Alpha": "undecided", "Delta": "likely_irrelevant",
                        "Beta": "irrelevant"}
    assert out["decision"]["counts"] == {"judged": 4, "promoted": 1, "dropped": 1, "to_confirm": 1, "undecided": 1}


def test_gate_thresholds_are_applied():
    backend = Scripted(gate_answers({"Alpha": 0.9, "Beta": 0.5, "Gamma": 0.5, "Delta": 0.5}))
    strict = d.relevance_gate("q", CANDS, cfg(), backend=backend)
    assert strict["candidates"][0]["decision"]["band"] == "confirm"  # 0.9 -> confidence 0.8
    loose = d.relevance_gate("q", CANDS, cfg(act=0.8), backend=backend)
    assert loose["candidates"][0]["decision"]["band"] == "act"
    assert loose["decision"]["thresholds"]["act"] == 0.8


def test_gate_shuffles_but_is_deterministic():
    seen = []
    backend = Scripted(lambda s, q: (seen.append(list(by_title(s).values())), {k: noul(0.5) for k in q})[1])
    for _ in range(2):
        d.relevance_gate("some query", CANDS, cfg(), backend=backend)
    assert seen[0] == seen[1]  # same input, same order
    orders = set()
    for i in range(12):
        d.relevance_gate(f"query {i}", CANDS, cfg(), backend=backend)
        orders.add(tuple(seen[-1]))
    assert len(orders) > 1  # not always lexical order


def test_gate_withholds_pii_pages():
    cands = [dict(c) for c in CANDS]
    cands[1]["tags"] = ["visibility/pii"]
    backend = Scripted(gate_answers({"Alpha": 0.5, "Gamma": 0.5, "Delta": 0.5}))
    out = d.relevance_gate("q", cands, cfg(), backend=backend)
    assert "Beta" not in json.dumps(backend.calls[0][0])
    beta = next(c for c in out["candidates"] if c["title"] == "Beta")
    assert beta["decision"]["band"] == "not_sent"
    assert out["decision"]["payload"]["withheld_pii"] == 1


def test_gate_disabled_is_untouched():
    backend = Scripted(gate_answers({}))
    out = d.relevance_gate("q", CANDS, cfg(enabled=False), backend=backend)
    assert out["candidates"] == CANDS and backend.calls == []


# ---------------------------------------------------------------------------
# gated_query on the demo vault
# ---------------------------------------------------------------------------

QUESTION = "how should tool errors be retried"


def test_gated_query_disabled_equals_plain_query():
    plain = query(DEMO, QUESTION)
    assert d.gated_query(DEMO, QUESTION, cfg(enabled=False)) == plain


def test_gated_query_failed_open_equals_plain_plus_record():
    plain = query(DEMO, QUESTION)
    gated = d.gated_query(DEMO, QUESTION, cfg(), backend=Failing("timeout"))
    rec = gated.pop("decision")
    assert gated == plain
    assert rec["failed_open"] and rec["reason"] == "timeout"


def test_gated_query_rebuilds_should_read():
    plain = query(DEMO, QUESTION)
    assert len(plain["candidates"]) >= 2 and not plain["index_only"]
    first, second = plain["candidates"][0]["title"], plain["candidates"][1]["title"]

    def fn(state, questions):
        out = {}
        for pid, title in by_title(state).items():
            out[f"rel_{pid}"] = noul(0.01 if title == first else (0.99 if title == second else 0.5))
        return out

    gated = d.gated_query(DEMO, QUESTION, cfg(), backend=Scripted(fn))
    assert gated["candidates"][0]["title"] == second
    assert plain["candidates"][0]["page"] in [c["page"] for c in gated["dropped_candidates"]]
    assert plain["candidates"][0]["page"] not in gated["should_read"]
    assert gated["should_read"][0] == plain["candidates"][1]["page"]
    assert gated["decision"]["should_read_before"] == plain["should_read"]
    assert all("tags" not in c for c in gated["candidates"])


def test_gated_query_skips_structural_intents():
    backend = Scripted(gate_answers({}))
    out = d.gated_query(DEMO, "what are the top hubs", cfg(), backend=backend)
    assert out["decision"]["reason"] == "structural_intent" and backend.calls == []


# ---------------------------------------------------------------------------
# D4 ingest triage
# ---------------------------------------------------------------------------

TRI = ("update", "duplicate", "unrelated")


def triage_answers(by: Dict[str, Dict[str, float]], flip: set = frozenset()):
    def fn(state, questions):
        titles = by_title(state)
        out = {}
        for qid, q in questions.items():
            pid = qid.split("_", 1)[1].rsplit("__", 1)[0]
            probs = dict(by[titles[pid]])
            if titles[pid] in flip and qid.endswith("__b"):
                probs = {"update": probs["unrelated"], "duplicate": probs["duplicate"], "unrelated": probs["update"]}
            out[qid] = choice(probs)
        return out
    return fn


U = {"update": 0.95, "duplicate": 0.03, "unrelated": 0.02}
DUP = {"update": 0.03, "duplicate": 0.95, "unrelated": 0.02}
UNREL = {"update": 0.02, "duplicate": 0.02, "unrelated": 0.96}
MAYBE = {"update": 0.6, "duplicate": 0.1, "unrelated": 0.3}


def test_triage_update_existing():
    backend = Scripted(triage_answers({"Alpha": UNREL, "Beta": MAYBE, "Gamma": U, "Delta": UNREL}))
    out = d.ingest_triage("source text", CANDS, cfg(), backend=backend)
    assert out["verdict"] == "update_existing"
    assert [c["title"] for c in out["shortlist"]] == ["Gamma", "Beta"]
    assert {c["title"] for c in out["skip"]} == {"Alpha", "Delta"}
    assert out["decision"]["decided_by"] == "decision_model"
    # order check: two questions per page with the options in opposite order
    _state, questions = backend.calls[0]
    assert len(questions) == 8
    a = list(questions["tri_P0__a"]["criteria"])
    assert list(questions["tri_P0__b"]["criteria"]) == list(reversed(a))


def test_triage_duplicate_and_new_page():
    dup = d.ingest_triage("s", CANDS, cfg(), backend=Scripted(
        triage_answers({"Alpha": DUP, "Beta": UNREL, "Gamma": UNREL, "Delta": UNREL})))
    assert dup["verdict"] == "duplicate_skip"
    new = d.ingest_triage("s", CANDS, cfg(), backend=Scripted(
        triage_answers({t: UNREL for t in ("Alpha", "Beta", "Gamma", "Delta")})))
    assert new["verdict"] == "new_page" and new["shortlist"] == []


def test_triage_order_flip_is_undecided():
    backend = Scripted(triage_answers({"Alpha": U, "Beta": UNREL, "Gamma": UNREL, "Delta": UNREL}, flip={"Alpha"}))
    out = d.ingest_triage("s", CANDS, cfg(), backend=backend)
    alpha = next(c for c in out["shortlist"] if c["title"] == "Alpha")
    assert alpha["decision"]["order_flip"] is True and alpha["decision"]["band"] == "fallback"
    assert out["verdict"] == "undecided"
    assert out["decision"]["order_flips"] == 1


def test_triage_without_order_check_asks_once():
    backend = Scripted(triage_answers({t: U for t in ("Alpha", "Beta", "Gamma", "Delta")}))
    d.ingest_triage("s", CANDS, cfg(order_check=False), backend=backend)
    assert len(backend.calls[0][1]) == 4


def test_triage_fail_open_and_no_candidates():
    out = d.ingest_triage("s", CANDS, cfg(), backend=Failing("network"))
    assert out["verdict"] == "undecided" and out["shortlist"] == CANDS and out["decision"]["failed_open"]
    empty = d.ingest_triage("s", [], cfg(), backend=Failing("network"))
    assert empty["verdict"] == "new_page" and empty["decision"]["decided_by"] == "code"


def test_triage_source_excludes_its_own_page_and_sends_excerpt_only():
    src = DEMO / "concepts" / "prompt-caching.md"
    seen = {}

    def fn(state, questions):
        seen["state"] = state
        return {qid: choice(UNREL) for qid in questions}

    out = d.triage_source(DEMO, src, cfg(), backend=Scripted(fn), max_source_chars=200)
    pages = [c["page"] for c in out["shortlist"] + out["skip"]]
    assert "concepts/prompt-caching.md" not in pages and pages
    assert len(seen["state"]["source"]) <= 200
    assert not seen["state"]["source"].startswith("---")  # frontmatter is not sent


# ---------------------------------------------------------------------------
# D3 contradiction screen
# ---------------------------------------------------------------------------


def _write(vault: Path, rel: str, text: str) -> None:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _contra_vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    fm = "---\ntitle: {t}\ncategory: {c}\ntags: [x]\nsources: [m]\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n"
    _write(v, "entities/acme.md", fm.format(t="Acme", c="entities") + "## Founded\nAcme was founded in 2019.\n\n## Sources\n- a\n")
    _write(v, "concepts/history.md", fm.format(t="History", c="concepts")
           + "## Origins\n[[acme]] was founded in 2021 in Berlin.\n\n## Other\nNothing about it here.\n")
    _write(v, "concepts/product.md", fm.format(t="Product", c="concepts") + "## Pricing\nAcme charges per seat. See [[acme]].\n")
    return v


def test_find_section_pairs(tmp_path):
    v = _contra_vault(tmp_path)
    found = d.find_section_pairs(v)
    assert found["entities"] == ["entities/acme.md"]
    heads = {(p["a"]["heading"], p["b"]["heading"]) for p in found["pairs"]}
    assert ("Founded", "Origins") in heads
    assert all("Sources" not in h and "Other" not in h for pair in heads for h in pair)
    assert all(p["a"]["page"] != p["b"]["page"] for p in found["pairs"])
    capped = d.find_section_pairs(v, max_pairs=1)
    assert len(capped["pairs"]) == 1 and capped["truncated"]


def test_contradiction_screen_priorities(tmp_path):
    pairs = d.find_section_pairs(_contra_vault(tmp_path))["pairs"]

    def fn(state, questions):
        texts = state["section_1"]["text"] + state["section_2"]["text"]
        if "2019" in texts and "2021" in texts:
            probs = {"contradicts": 0.95, "corroborates": 0.01, "new_detail": 0.02, "unrelated": 0.02}
        else:
            probs = {"contradicts": 0.01, "corroborates": 0.01, "new_detail": 0.02, "unrelated": 0.96}
        return {qid: choice(probs) for qid in questions}

    out = d.contradiction_screen(pairs, cfg(), backend=Scripted(fn))
    top = out["to_read"][0]
    assert top["priority"] == 1 and {top["a"]["heading"], top["b"]["heading"]} == {"Founded", "Origins"}
    assert out["skipped"]  # confident non-conflicts are skipped
    assert all("text" not in r["a"] for r in out["to_read"] + out["skipped"])
    assert out["decision"]["counts"]["pairs"] == len(pairs)


def test_contradiction_screen_disabled_and_failed_list_every_pair(tmp_path):
    pairs = d.find_section_pairs(_contra_vault(tmp_path))["pairs"]
    off = d.contradiction_screen(pairs, cfg(enabled=False))
    assert len(off["to_read"]) == len(pairs) and {r["priority"] for r in off["to_read"]} == {3}
    failed = d.contradiction_screen(pairs, cfg(), backend=Failing("http_500"))
    assert len(failed["to_read"]) == len(pairs) and failed["decision"]["failed_open"]
    assert failed["decision"]["reason"] == "all_failed" and failed["decision"]["errors"] == {"http_500": len(pairs)}


# ---------------------------------------------------------------------------
# Never writes
# ---------------------------------------------------------------------------


def _snapshot(root: Path) -> dict:
    return {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in root.rglob("*") if p.is_file()}


def test_decisions_never_write_to_the_vault(tmp_path):
    v = tmp_path / "demo"
    shutil.copytree(DEMO, v)
    before = _snapshot(v)
    any_answer = Scripted(lambda s, q: {k: (noul(0.99) if k.startswith("rel_P") else choice(U if k.startswith("tri") else
                          {"contradicts": 0.9, "corroborates": 0.05, "new_detail": 0.03, "unrelated": 0.02})) for k in q})
    d.gated_query(v, QUESTION, cfg(), backend=any_answer)
    d.triage_source(v, v / "journal" / "2026-06-02-memory-design-review.md", cfg(), backend=any_answer)
    d.contradiction_screen(d.find_section_pairs(v)["pairs"], cfg(), backend=any_answer)
    assert _snapshot(v) == before


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(*args: str, env_extra: Dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("OBSIDIAN_WIKI_DECISIONS") and k != d.ENV_KEY}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-m", "obsidian_wiki.cli", *args], capture_output=True, text=True,
                          env=env, cwd=str(ROOT))


def test_cli_graph_query_unchanged_without_opt_in():
    res = _cli("graph-query", str(DEMO), QUESTION)
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout) == query(DEMO, QUESTION)


def test_cli_graph_query_decide_without_key_fails_open():
    res = _cli("graph-query", str(DEMO), QUESTION, "--decide")
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    rec = out.pop("decision")
    assert rec["failed_open"] and rec["reason"] == "missing_key" and rec["sent"] is False
    assert out == query(DEMO, QUESTION)


def test_cli_env_opt_in_and_no_decide(fake_server):
    server = fake_server(lambda body: (200, {"model": "jev-1.14.0", "answers": {q: noul(0.5) for q in body["questions"]},
                                             "usage": {}}, 0))
    env = {d.ENV_MODE: "typesafe", d.ENV_KEY: FAKE_KEY, d.ENV_URL: server.url}
    on = _cli("graph-query", str(DEMO), QUESTION, env_extra=env)
    assert json.loads(on.stdout)["decision"]["failed_open"] is False
    assert FAKE_KEY not in on.stdout + on.stderr
    off = _cli("graph-query", str(DEMO), QUESTION, "--no-decide", env_extra=env)
    assert "decision" not in json.loads(off.stdout)
    assert len(server.requests) == 1


def test_cli_rejects_bad_thresholds():
    res = _cli("graph-query", str(DEMO), QUESTION, "--decide", "--decide-act", "0.3", "--decide-confirm", "0.6")
    assert res.returncode == 2 and "confirm" in res.stderr


def test_cli_decide_subcommands_without_opt_in():
    st = _cli("decide", "status", env_extra={d.ENV_KEY: FAKE_KEY})
    assert json.loads(st.stdout)["enabled"] is False and FAKE_KEY not in st.stdout
    tri = _cli("decide", "triage", str(DEMO / "journal" / "2026-06-02-memory-design-review.md"), "--vault", str(DEMO))
    out = json.loads(tri.stdout)
    assert out["decision"]["reason"] == "disabled" and out["shortlist"]
    con = _cli("decide", "contradictions", "--vault", str(DEMO))
    out = json.loads(con.stdout)
    assert out["decision"]["reason"] == "disabled" and out["to_read"]


def test_benchmark_runs_offline_with_the_mock():
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "bench_decisions.py"), "--json"],
                         capture_output=True, text=True, cwd=str(ROOT),
                         env={k: v for k, v in os.environ.items() if k != d.ENV_KEY})
    assert res.returncode == 0, res.stderr
    report = json.loads(res.stdout)
    assert report["backend"] == "mock" and report["questions"] == 12
    assert report["gate"]["failed_open"] == 0
    assert set(report["plain"]) == set(report["gated"])
