"""Optional decision layer: hand small closed judgments to a System One model.

A decision model answers a closed question (yes/no, pick one) with calibrated
probabilities and never writes text. Code prepares the options; the model
picks; code acts on the answer only when the confidence clears a threshold.
The main agent still reads, writes and answers. This module only reorders,
filters and flags what the agent looks at first.

Hard rules, enforced here rather than left to callers:

* **Off by default.** Nothing runs unless ``OBSIDIAN_WIKI_DECISIONS`` names a
  backend or the caller passes ``enabled=True`` (the CLI's ``--decide``).
* **Fails open.** A missing key, a timeout, an HTTP error or an answer that
  does not validate returns the normal, non-decision result with
  ``failed_open: true`` and a ``reason``. No decision function raises for a
  backend problem, and none of them writes to the vault.
* **Minimum data.** Retrieval sends the query plus page titles, summaries and
  tags, under opaque ids (``P0``, ``P1``…), never paths or bodies. Pages tagged
  ``visibility/pii`` are never sent. Emails, URLs with credentials and
  token-shaped strings are masked before anything leaves the machine.
* **Confidence bands.** ``>= act`` acts, ``confirm..act`` keeps the item and
  flags it for the agent to confirm, ``< confirm`` leaves the normal result in
  place. Both thresholds are configurable.
* **Position bias.** Candidate order in the state is shuffled with a seed
  derived from the input, and Choice questions are asked twice with the
  options in opposite order; when the two orderings disagree the answer is
  treated as undecided.
* **Provenance.** Every decision records backend, model, ``latency_ms`` and the
  thresholds it was judged against.

The backend is an interface (:class:`DecisionBackend`): anything with
``name``, ``model`` and ``ask(state, questions)`` works, so a local backend can
be added later without touching the decisions.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

__all__ = [
    "BackendAnswer",
    "DecisionBackend",
    "DecisionConfig",
    "DecisionError",
    "TypeSafeBackend",
    "band",
    "contradiction_screen",
    "find_section_pairs",
    "gated_query",
    "ingest_triage",
    "make_backend",
    "noul_confidence",
    "relevance_gate",
    "scrub",
    "status",
    "triage_source",
]

ENV_MODE = "OBSIDIAN_WIKI_DECISIONS"
ENV_MODEL = "OBSIDIAN_WIKI_DECISIONS_MODEL"
ENV_URL = "OBSIDIAN_WIKI_DECISIONS_URL"
ENV_TIMEOUT = "OBSIDIAN_WIKI_DECISIONS_TIMEOUT"
ENV_ACT = "OBSIDIAN_WIKI_DECISIONS_ACT"
ENV_CONFIRM = "OBSIDIAN_WIKI_DECISIONS_CONFIRM"
ENV_KEY = "TYPESAFE_API_KEY"

# Pinned rather than `jev-latest`: an alias moves when a release ships, and
# thresholds are only meaningful against the model they were set on.
DEFAULT_MODEL = "jev-1.14.0"
DEFAULT_URL = "https://api.typesafe.ai"
DEFAULT_TIMEOUT = 5.0
DEFAULT_ACT = 0.9
DEFAULT_CONFIRM = 0.5

BACKENDS = ("typesafe",)
_OFF = {"", "off", "0", "false", "no", "none"}
_ON_ALIASES = {"on", "1", "true", "yes", "jev"}

# A response larger than this is not a System One answer for our question
# sizes; refuse it instead of buffering it.
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class DecisionError(Exception):
    """A backend problem. Decision functions catch it and fail open."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def _env_float(env: Mapping[str, str], key: str, default: float, warnings: List[str]) -> float:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        warnings.append(f"{key}={raw!r} is not a number; using {default}")
        return default
    if not math.isfinite(value):
        warnings.append(f"{key}={raw!r} is not finite; using {default}")
        return default
    return value


@dataclass
class DecisionConfig:
    enabled: bool = False
    backend: str = "typesafe"
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_URL
    timeout: float = DEFAULT_TIMEOUT
    act: float = DEFAULT_ACT
    confirm: float = DEFAULT_CONFIRM
    # Ask each Choice twice with reversed options and require agreement.
    order_check: bool = True
    # Fixed seed for the shuffle; None derives one from the input so a rerun
    # of the same query sends the same order.
    seed: Optional[int] = None
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("act", "confirm"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} threshold must be between 0 and 1, got {value}")
        if self.confirm > self.act:
            raise ValueError(f"confirm threshold ({self.confirm}) must not exceed act ({self.act})")
        if self.timeout <= 0:
            raise ValueError(f"timeout must be positive, got {self.timeout}")

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        *,
        enabled: Optional[bool] = None,
        **overrides: Any,
    ) -> "DecisionConfig":
        """Read the opt-in and knobs from the environment.

        ``enabled=True`` (``--decide``) turns the layer on even when the env
        says off; ``enabled=False`` (``--no-decide``) forces it off. ``None``
        follows the env. Malformed env numbers fall back to the defaults with
        a warning rather than breaking the normal command. ``overrides``
        (from CLI flags) win over env and are validated strictly.
        """
        env = os.environ if env is None else env
        warnings: List[str] = []
        mode = (env.get(ENV_MODE) or "").strip().lower()
        env_on = mode not in _OFF
        backend = "typesafe" if (not env_on or mode in _ON_ALIASES) else mode
        act = _env_float(env, ENV_ACT, DEFAULT_ACT, warnings)
        confirm = _env_float(env, ENV_CONFIRM, DEFAULT_CONFIRM, warnings)
        if not (0.0 <= confirm <= act <= 1.0):
            warnings.append(
                f"thresholds confirm={confirm} act={act} must satisfy 0 <= confirm <= act <= 1; using defaults"
            )
            act, confirm = DEFAULT_ACT, DEFAULT_CONFIRM
        timeout = _env_float(env, ENV_TIMEOUT, DEFAULT_TIMEOUT, warnings)
        if timeout <= 0:
            warnings.append(f"{ENV_TIMEOUT} must be positive; using {DEFAULT_TIMEOUT}")
            timeout = DEFAULT_TIMEOUT
        values: Dict[str, Any] = {
            "enabled": env_on if enabled is None else bool(enabled),
            "backend": backend,
            "model": (env.get(ENV_MODEL) or "").strip() or DEFAULT_MODEL,
            "base_url": (env.get(ENV_URL) or "").strip() or DEFAULT_URL,
            "timeout": timeout,
            "act": act,
            "confirm": confirm,
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(warnings=warnings, **values)

    def thresholds(self) -> Dict[str, float]:
        return {"act": self.act, "confirm": self.confirm}


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


@dataclass
class BackendAnswer:
    model: str
    answers: Dict[str, Any]
    usage: Dict[str, Any]
    latency_ms: float


class DecisionBackend:
    """Interface for a decision backend. Subclass or duck-type it.

    ``ask`` takes the System One shapes (a ``state`` and a mapping of named
    questions) and returns the answers keyed by the same names. It raises
    :class:`DecisionError` on any failure; it never returns partial garbage.
    """

    name: str = "abstract"
    model: str = ""

    def ask(self, state: Any, questions: Dict[str, Dict[str, Any]]) -> BackendAnswer:  # pragma: no cover
        raise NotImplementedError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: urllib would re-send the bearer key to the new URL unchecked."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None  # urllib then raises HTTPError(code) -> fails open as http_3xx


def _url_allowed(url: str) -> bool:
    """HTTPS anywhere, plain HTTP only to loopback, so the key never crosses a network in clear."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return True
    return parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}


class TypeSafeBackend(DecisionBackend):
    """``POST {base_url}/v1/systemone`` with a bearer key (https://docs.typesafe.ai/api)."""

    name = "typesafe"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_URL,
        timeout: float = DEFAULT_TIMEOUT,
        opener: Optional[Callable[..., Any]] = None,
    ) -> None:
        if not api_key:
            raise DecisionError("missing_key", f"{ENV_KEY} is not set")
        if not _url_allowed(base_url):
            raise DecisionError("insecure_url", "the backend URL must be https (or http to loopback)")
        self._api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.build_opener(_NoRedirect).open

    def __repr__(self) -> str:  # never show the key
        return f"TypeSafeBackend(model={self.model!r}, base_url={self.base_url!r})"

    def ask(self, state: Any, questions: Dict[str, Dict[str, Any]]) -> BackendAnswer:
        try:
            body = json.dumps(
                {"model": self.model, "state": state, "questions": questions},
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise DecisionError("invalid_request", str(exc)) from None
        request = urllib.request.Request(
            self.base_url + "/v1/systemone",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "obsidian-wiki-decisions",
            },
        )
        started = time.perf_counter()
        try:
            with self._open(request, timeout=self.timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            detail = ""
            if exc.code in (400, 422):  # validation errors describe our request, not secrets
                try:
                    detail = exc.read(400).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001 - detail is best effort
                    detail = ""
            raise DecisionError(f"http_{exc.code}", detail) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise DecisionError("timeout") from None
            raise DecisionError("network", type(exc.reason).__name__) from None
        except (socket.timeout, TimeoutError):
            raise DecisionError("timeout") from None
        except OSError as exc:
            raise DecisionError("network", type(exc).__name__) from None
        latency_ms = (time.perf_counter() - started) * 1000.0
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise DecisionError("invalid_response", "response too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise DecisionError("invalid_response", "not JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
            raise DecisionError("invalid_response", "no answers object")
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        model = payload.get("model") if isinstance(payload.get("model"), str) else self.model
        return BackendAnswer(model=model, answers=payload["answers"], usage=usage, latency_ms=latency_ms)


def make_backend(cfg: DecisionConfig, env: Optional[Mapping[str, str]] = None) -> DecisionBackend:
    env = os.environ if env is None else env
    if cfg.backend == "typesafe":
        return TypeSafeBackend(
            (env.get(ENV_KEY) or "").strip(),
            model=cfg.model,
            base_url=cfg.base_url,
            timeout=cfg.timeout,
        )
    raise DecisionError("unknown_backend", f"{cfg.backend!r} (supported: {', '.join(BACKENDS)})")


def status(cfg: DecisionConfig, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """What the layer would do, with no network call. Reports key presence, never its value."""
    env = os.environ if env is None else env
    return {
        "enabled": cfg.enabled,
        "backend": cfg.backend,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "timeout_s": cfg.timeout,
        "thresholds": cfg.thresholds(),
        "order_check": cfg.order_check,
        "key_present": bool((env.get(ENV_KEY) or "").strip()),
        "url_allowed": _url_allowed(cfg.base_url),
        "warnings": list(cfg.warnings),
    }


# ---------------------------------------------------------------------------
# Answer validation, bands, privacy
# ---------------------------------------------------------------------------


def _prob(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionError("invalid_answer", "probability is not a number")
    value = float(value)
    if not math.isfinite(value) or value < -1e-6 or value > 1 + 1e-6:
        raise DecisionError("invalid_answer", "probability out of range")
    return min(1.0, max(0.0, value))


def _noul(answers: Mapping[str, Any], qid: str) -> float:
    answer = answers.get(qid)
    if not isinstance(answer, dict) or answer.get("type") != "noul":
        raise DecisionError("invalid_answer", f"{qid}: missing noul answer")
    return _prob(answer.get("noul"))


def _choice(answers: Mapping[str, Any], qid: str, options: Sequence[str]) -> Dict[str, float]:
    answer = answers.get(qid)
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise DecisionError("invalid_answer", f"{qid}: missing choice answer")
    if answer.get("choice") not in options:
        raise DecisionError("invalid_answer", f"{qid}: choice is not one of the options")
    probs = answer.get("probabilities")
    if not isinstance(probs, dict):
        raise DecisionError("invalid_answer", f"{qid}: no probabilities")
    out = {opt: _prob(probs.get(opt, 0.0)) for opt in options}
    total = sum(out.values())
    if total <= 0:
        raise DecisionError("invalid_answer", f"{qid}: probabilities sum to zero")
    return {opt: p / total for opt, p in out.items()}


def noul_confidence(p: float) -> float:
    """Distance from 0.5, scaled to 0..1 (TypeSafe's suggested Noul confidence)."""
    return abs(p - 0.5) * 2.0


def band(confidence: float, cfg: DecisionConfig) -> str:
    if confidence >= cfg.act:
        return "act"
    if confidence >= cfg.confirm:
        return "confirm"
    return "fallback"


_MASKS = (
    (re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@\S+", re.I), "[url-with-credentials]"),
    (re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|github_pat|xox[abprs]|AKIA|ASIA)[-_A-Za-z0-9]{12,}\b"), "[token]"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "[hex]"),
    # Long runs mixing letters and digits (API keys, base64). Requiring both
    # keeps long hyphenated slugs and words readable.
    (re.compile(r"(?<![A-Za-z0-9+/_-])(?=[A-Za-z0-9+/_-]*\d)(?=[A-Za-z0-9+/_-]*[A-Za-z])[A-Za-z0-9+/_-]{40,}={0,2}"),
     "[token]"),
)


def scrub(text: Any, limit: int) -> str:
    """Mask credential-shaped strings, collapse whitespace, cap the length."""
    out = str(text or "")
    for pattern, repl in _MASKS:
        out = pattern.sub(repl, out)
    out = re.sub(r"\s+", " ", out).strip()
    if len(out) > limit:
        out = out[: max(0, limit - 1)].rstrip() + "…"
    return out


def _rng(cfg: DecisionConfig, *parts: str) -> random.Random:
    if cfg.seed is not None:
        return random.Random(cfg.seed)
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _is_pii(tags: Sequence[str]) -> bool:
    return any(str(t).strip().lower() == "visibility/pii" for t in tags or ())


# Failures that happen before any byte leaves the machine.
_PRE_NETWORK = {"disabled", "no_candidates", "no_pairs", "nothing_sendable", "structural_intent",
                "missing_key", "insecure_url", "unknown_backend", "invalid_request"}
# Failures that happen after the backend answered (plus every ``http_*`` status).
_POST_RESPONSE = {"invalid_response", "invalid_answer"}


def _record(
    kind: str,
    cfg: DecisionConfig,
    *,
    backend: Optional[DecisionBackend] = None,
    model: Optional[str] = None,
    latency_ms: Optional[float] = None,
    failed_open: bool = False,
    reason: Optional[str] = None,
    usage: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if latency_ms is not None or (reason or "").startswith("http_") or reason in _POST_RESPONSE:
        sent: Optional[bool] = True
    elif reason in _PRE_NETWORK or not failed_open:
        sent = False
    else:
        sent = None  # a timeout or network error: the request may have reached the backend
    return {
        "kind": kind,
        "enabled": cfg.enabled,
        "backend": backend.name if backend is not None else cfg.backend,
        "model": model or (backend.model if backend is not None else cfg.model),
        "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
        "thresholds": cfg.thresholds(),
        "failed_open": failed_open,
        "reason": reason,
        "usage": usage or {},
        "sent": sent,
        "payload": payload or {},
    }


def _resolve_backend(
    cfg: DecisionConfig, backend: Optional[DecisionBackend], env: Optional[Mapping[str, str]]
) -> DecisionBackend:
    return backend if backend is not None else make_backend(cfg, env)


def _choice_pair(
    qid: str,
    instructions: str,
    criteria: Dict[str, str],
    cfg: DecisionConfig,
    rng: random.Random,
) -> Dict[str, Dict[str, Any]]:
    """One Choice, or two with opposite option orders when order_check is on."""
    names = list(criteria)
    rng.shuffle(names)
    questions = {f"{qid}__a": {"type": "choice", "instructions": instructions,
                               "criteria": {n: criteria[n] for n in names}}}
    if cfg.order_check:
        questions[f"{qid}__b"] = {"type": "choice", "instructions": instructions,
                                  "criteria": {n: criteria[n] for n in reversed(names)}}
    return questions


def _read_choice_pair(
    answers: Mapping[str, Any], qid: str, options: Sequence[str], cfg: DecisionConfig
) -> Dict[str, Any]:
    first = _choice(answers, f"{qid}__a", options)
    if not cfg.order_check:
        probs, flipped = first, False
    else:
        second = _choice(answers, f"{qid}__b", options)
        probs = {o: (first[o] + second[o]) / 2.0 for o in options}
        flipped = max(first, key=first.get) != max(second, key=second.get)
    top = max(probs, key=probs.get)
    conf = probs[top]
    level = "fallback" if flipped else band(conf, cfg)
    return {
        "choice": top,
        "confidence": round(conf, 4),
        "probabilities": {o: round(p, 4) for o, p in probs.items()},
        "band": level,
        "order_flip": flipped,
    }


# ---------------------------------------------------------------------------
# D1: relevance gate (wiki-query)
# ---------------------------------------------------------------------------

_REL_CRITERIA = {
    "true": "The page is about what the query asks, or it states facts an answer to the query needs.",
    "false": "The page only shares words with the query, or it is about a different subject.",
}


def relevance_gate(
    query: str,
    candidates: Sequence[Dict[str, Any]],
    cfg: DecisionConfig,
    *,
    backend: Optional[DecisionBackend] = None,
    env: Optional[Mapping[str, str]] = None,
    max_summary_chars: int = 400,
) -> Dict[str, Any]:
    """Judge each candidate page's relevance from its title, summary and tags.

    Returns ``{"candidates", "dropped", "decision"}``. ``candidates`` keeps the
    input order unless a judgment reached the ``act`` band: confidently
    relevant pages move to the front (by probability), confidently irrelevant
    ones move to ``dropped``. Everything else stays where lexical ranking put
    it, annotated so the agent knows what to confirm. On any failure the input
    comes back unchanged.
    """
    original = [dict(c) for c in candidates]
    if not cfg.enabled:
        return {"candidates": original, "dropped": [], "decision": _record("relevance_gate", cfg, reason="disabled")}
    if not original:
        return {"candidates": [], "dropped": [], "decision": _record("relevance_gate", cfg, reason="no_candidates")}

    rng = _rng(cfg, "relevance", query, *(str(c.get("page", "")) for c in original))
    order = list(range(len(original)))
    rng.shuffle(order)
    pages: Dict[str, Dict[str, Any]] = {}
    pid_of: Dict[int, str] = {}
    withheld: List[int] = []
    for idx in order:
        cand = original[idx]
        if _is_pii(cand.get("tags", ())):
            withheld.append(idx)
            continue
        pid = f"P{len(pages)}"
        pid_of[idx] = pid
        pages[pid] = {
            "title": scrub(cand.get("title", ""), 160),
            "summary": scrub(cand.get("summary", ""), max_summary_chars),
            "tags": [scrub(t, 40) for t in cand.get("tags", ()) if not str(t).startswith("visibility/")][:8],
        }
    payload = {"fields": ["query", "title", "summary", "tags"], "pages": len(pages), "withheld_pii": len(withheld)}
    if not pages:
        for idx in withheld:
            original[idx]["decision"] = {"band": "not_sent", "verdict": "undecided", "p_relevant": None}
        return {"candidates": original, "dropped": [],
                "decision": _record("relevance_gate", cfg, reason="nothing_sendable", payload=payload)}

    state = {"query": scrub(query, 500), "pages": pages}
    questions = {
        f"rel_{pid}": {
            "type": "noul",
            "instructions": f"Would reading the wiki page `pages.{pid}` help answer `query`?",
            "criteria": _REL_CRITERIA,
        }
        for pid in pages
    }
    try:
        be = _resolve_backend(cfg, backend, env)
        answer = be.ask(state, questions)
        probs = {pid: _noul(answer.answers, f"rel_{pid}") for pid in pages}
    except DecisionError as exc:
        return {"candidates": original, "dropped": [],
                "decision": _record("relevance_gate", cfg, backend=backend, failed_open=True,
                                    reason=exc.reason, payload=payload)}

    promoted: List[tuple] = []
    rest: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for idx, cand in enumerate(original):
        if idx not in pid_of:
            cand["decision"] = {"band": "not_sent", "verdict": "undecided", "p_relevant": None}
            rest.append(cand)
            continue
        p = probs[pid_of[idx]]
        level = band(noul_confidence(p), cfg)
        if level == "act":
            verdict = "relevant" if p >= 0.5 else "irrelevant"
        elif level == "confirm":
            verdict = "likely_relevant" if p >= 0.5 else "likely_irrelevant"
        else:
            verdict = "undecided"
        cand["decision"] = {"band": level, "verdict": verdict, "p_relevant": round(p, 4)}
        if verdict == "relevant":
            promoted.append((-p, idx, cand))
        elif verdict == "irrelevant":
            dropped.append(cand)
        else:
            rest.append(cand)
    promoted.sort(key=lambda t: (t[0], t[1]))
    kept = [c for _, _, c in promoted] + rest
    record = _record("relevance_gate", cfg, backend=be, model=answer.model, latency_ms=answer.latency_ms,
                     usage=answer.usage, payload=payload)
    record["counts"] = {
        "judged": len(pages),
        "promoted": len(promoted),
        "dropped": len(dropped),
        "to_confirm": sum(1 for c in kept if c["decision"]["band"] == "confirm"),
        "undecided": sum(1 for c in kept if c["decision"]["band"] in ("fallback", "not_sent")),
    }
    record["all_dropped"] = not kept
    return {"candidates": kept, "dropped": dropped, "decision": record}


def _page_tags(vault: Path, rel: str) -> List[str]:
    from obsidian_wiki.graph_analysis import frontmatter_tags
    from obsidian_wiki.vault import split_frontmatter

    try:
        text = (vault / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    front, _ = split_frontmatter(text)
    return frontmatter_tags(front) if front else []


def gated_query(
    vault: Path,
    question: str,
    cfg: DecisionConfig,
    *,
    backend: Optional[DecisionBackend] = None,
    env: Optional[Mapping[str, str]] = None,
    max_should_read: int = 3,
    **query_kwargs: Any,
) -> Dict[str, Any]:
    """``graphrag.query`` plus the relevance gate. Disabled: byte-for-byte the plain result."""
    from obsidian_wiki.graphrag import query

    result = query(vault, question, max_should_read=max_should_read, **query_kwargs)
    if not cfg.enabled:
        return result
    if result.get("graph") is not None:
        result["decision"] = _record("relevance_gate", cfg, reason="structural_intent")
        return result
    cands = result.get("candidates") or []
    # Tags go to the gate (for the PII check and as context) on copies only, so
    # a failed-open result is exactly the plain one plus the decision record.
    tagged = [{**c, "tags": _page_tags(vault, c["page"])} for c in cands]
    gate = relevance_gate(question, tagged, cfg, backend=backend, env=env)
    for cand in gate["candidates"] + gate["dropped"]:
        cand.pop("tags", None)
    decision = gate["decision"]
    if not decision["failed_open"] and decision["reason"] is None:
        before = list(result.get("should_read") or [])
        path_pages = [p for p in result.get("path") or [] if p not in {c["page"] for c in cands}]
        result["candidates"] = gate["candidates"]
        result["dropped_candidates"] = gate["dropped"]
        if not result.get("index_only"):
            reads = [c["page"] for c in gate["candidates"]
                     if c.get("decision", {}).get("verdict") != "likely_irrelevant"][:max_should_read]
            for p in path_pages:
                if p not in reads:
                    reads.append(p)
            result["should_read"] = reads[: max_should_read + 2]
        decision["should_read_before"] = before
    result["decision"] = decision
    return result


# ---------------------------------------------------------------------------
# D4: ingest triage (wiki-ingest, wiki-dedup)
# ---------------------------------------------------------------------------

_TRIAGE_OPTIONS = ("update", "duplicate", "unrelated")
_TRIAGE_CRITERIA = {
    "update": "The source adds facts about this page's subject, or changes something the page says.",
    "duplicate": "The page already says everything the source says about the page's subject; the source adds nothing to it.",
    "unrelated": "The page is about a different subject; the source would not change it.",
}


def ingest_triage(
    source_text: str,
    candidates: Sequence[Dict[str, Any]],
    cfg: DecisionConfig,
    *,
    source_label: str = "",
    backend: Optional[DecisionBackend] = None,
    env: Optional[Mapping[str, str]] = None,
    max_source_chars: int = 1500,
    max_summary_chars: int = 400,
) -> Dict[str, Any]:
    """For each existing page the source might touch: update, duplicate or unrelated.

    Returns ``{"verdict", "shortlist", "skip", "decision"}``. ``verdict`` is
    ``update_existing``, ``duplicate_skip``, ``new_page`` or ``undecided``;
    only ``act``-band answers produce anything but ``undecided``, and the
    agent still does the writing. ``shortlist`` is the order to read pages
    in. On failure: lexical order, ``undecided``.
    """
    original = [dict(c) for c in candidates]

    def _plain(reason: Optional[str], *, failed: bool = False, be: Optional[DecisionBackend] = None,
               payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        verdict = "new_page" if not original else "undecided"
        rec = _record("ingest_triage", cfg, backend=be, failed_open=failed, reason=reason, payload=payload)
        rec["decided_by"] = "code" if not original else None
        return {"verdict": verdict, "shortlist": original, "skip": [], "decision": rec}

    if not cfg.enabled:
        return _plain("disabled")
    if not original:
        return _plain("no_candidates")

    rng = _rng(cfg, "triage", source_label, source_text[:200], *(str(c.get("page", "")) for c in original))
    order = list(range(len(original)))
    rng.shuffle(order)
    pages: Dict[str, Dict[str, Any]] = {}
    pid_of: Dict[int, str] = {}
    for idx in order:
        cand = original[idx]
        if _is_pii(cand.get("tags", ())):
            continue
        pid = f"P{len(pages)}"
        pid_of[idx] = pid
        pages[pid] = {"title": scrub(cand.get("title", ""), 160),
                      "summary": scrub(cand.get("summary", ""), max_summary_chars)}
    payload = {"fields": ["source_excerpt", "title", "summary"], "pages": len(pages),
            "withheld_pii": len(original) - len(pages), "source_chars": min(len(source_text), max_source_chars)}
    if not pages:
        return _plain("nothing_sendable", payload=payload)

    state = {"source": scrub(source_text, max_source_chars), "pages": pages}
    questions: Dict[str, Dict[str, Any]] = {}
    for pid in pages:
        questions.update(_choice_pair(
            f"tri_{pid}",
            f"What would ingesting `source` mean for the existing wiki page `pages.{pid}`?",
            _TRIAGE_CRITERIA, cfg, rng,
        ))
    try:
        be = _resolve_backend(cfg, backend, env)
        answer = be.ask(state, questions)
        judged = {pid: _read_choice_pair(answer.answers, f"tri_{pid}", _TRIAGE_OPTIONS, cfg) for pid in pages}
    except DecisionError as exc:
        return _plain(exc.reason, failed=True, be=backend, payload=payload)

    decided: List[tuple] = []
    undecided: List[Dict[str, Any]] = []
    skip: List[Dict[str, Any]] = []
    for idx, cand in enumerate(original):
        if idx not in pid_of:
            cand["decision"] = {"band": "not_sent", "choice": None}
            undecided.append(cand)
            continue
        j = judged[pid_of[idx]]
        cand["decision"] = j
        related = 1.0 - j["probabilities"]["unrelated"]
        if j["band"] == "act" and j["choice"] == "unrelated":
            skip.append(cand)
        elif j["band"] in ("act", "confirm"):
            decided.append((-related, idx, cand))
        else:
            undecided.append(cand)
    decided.sort(key=lambda t: (t[0], t[1]))
    shortlist = [c for _, _, c in decided] + undecided

    acted = [c for c in original if c.get("decision", {}).get("band") == "act"]
    if any(c["decision"]["choice"] == "update" for c in acted):
        verdict = "update_existing"
    elif any(c["decision"]["choice"] == "duplicate" for c in acted):
        verdict = "duplicate_skip"
    elif len(skip) == len(original):
        verdict = "new_page"
    else:
        verdict = "undecided"
    rec = _record("ingest_triage", cfg, backend=be, model=answer.model, latency_ms=answer.latency_ms,
                  usage=answer.usage, payload=payload)
    rec["decided_by"] = "decision_model" if verdict != "undecided" else None
    rec["order_flips"] = sum(1 for j in judged.values() if j["order_flip"])
    return {"verdict": verdict, "shortlist": shortlist, "skip": skip, "decision": rec}


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")


def _source_terms(text: str, label: str, limit: int = 12) -> List[str]:
    from collections import Counter

    from obsidian_wiki.graphrag import _STOP_WORDS

    _front, body = _split(text)
    title_m = re.search(r"^title:\s*[>|]?-?\s*(.+)$", _front, re.M) if _front else None
    heads = re.findall(r"^#{1,3}\s+(.+)$", body, re.M)[:6]
    lead = " ".join(filter(None, [label.replace("-", " ").replace("_", " "),
                                  title_m.group(1) if title_m else "", *heads]))
    terms: List[str] = []
    for w in _WORD_RE.findall(lead):
        if w.lower() not in _STOP_WORDS and w.lower() not in (t.lower() for t in terms):
            terms.append(w)
    counts = Counter(w.lower() for w in _WORD_RE.findall(body) if w.lower() not in _STOP_WORDS and len(w) > 3)
    for w, _n in counts.most_common(limit * 2):
        if len(terms) >= limit:
            break
        if w not in (t.lower() for t in terms):
            terms.append(w)
    return terms[:limit]


def _split(text: str) -> tuple:
    from obsidian_wiki.vault import split_frontmatter

    return split_frontmatter(text)


def triage_source(
    vault: Path,
    source: Path,
    cfg: DecisionConfig,
    *,
    top_n: int = 8,
    backend: Optional[DecisionBackend] = None,
    env: Optional[Mapping[str, str]] = None,
    max_source_chars: int = 1500,
) -> Dict[str, Any]:
    """Find candidate pages for a source file by lexical rank, then triage them."""
    from obsidian_wiki.graphrag import build_index, rank_candidates

    text = source.read_text(encoding="utf-8", errors="replace")
    index = build_index(vault)
    try:
        own = source.resolve().relative_to(vault.resolve()).as_posix()
    except ValueError:
        own = None
    pool = {s: e for s, e in index.items() if e["path"] != own}
    terms = _source_terms(text, source.stem)
    ranked = rank_candidates(pool, terms, top_n=top_n)
    candidates = [
        {"page": c["page"], "title": c["title"], "summary": c["summary"], "score": round(c["score"], 2),
         "tags": pool[c["slug"]]["tags"]}
        for c in ranked
    ]
    _front, body = _split(text)
    result = ingest_triage(body, candidates, cfg, source_label=source.stem, backend=backend, env=env,
                           max_source_chars=max_source_chars)
    for cand in result["shortlist"] + result["skip"]:
        cand.pop("tags", None)
    result["source"] = own or source.name
    result["terms"] = terms
    return result


# ---------------------------------------------------------------------------
# D3: contradiction screen (wiki-lint)
# ---------------------------------------------------------------------------

_CONTRA_OPTIONS = ("contradicts", "corroborates", "new_detail", "unrelated")
_CONTRA_CRITERIA = {
    "contradicts": "The sections make claims about `entity` that cannot both be true: different values, dates, names, or opposite statements.",
    "corroborates": "Both sections state the same facts about `entity`.",
    "new_detail": "One section adds facts about `entity` that the other does not mention, and nothing conflicts.",
    "unrelated": "The sections discuss different aspects; neither says anything the other could confirm or conflict with.",
}
_SKIP_HEADINGS = {"sources", "source", "related", "see also", "references", "links", "backlinks"}
_FENCE_RE = re.compile(r"```.*?```", re.S)


def _sections(body: str) -> List[tuple]:
    body = _FENCE_RE.sub("", body)
    out: List[tuple] = []
    heading = "(intro)"
    buf: List[str] = []
    for line in body.splitlines():
        m = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if m:
            out.append((heading, "\n".join(buf).strip()))
            heading, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    out.append((heading, "\n".join(buf).strip()))
    return [(h, t) for h, t in out if t and h.lower() not in _SKIP_HEADINGS]


def find_section_pairs(
    vault: Path,
    *,
    entity: Optional[str] = None,
    max_pairs: int = 40,
    max_section_chars: int = 1200,
) -> Dict[str, Any]:
    """Pairs of sections on different pages that both talk about the same entity.

    Code only: no model call. An entity is a page under ``entities/`` (or the
    one named by ``entity``); a section mentions it when it links to it or
    names its title. The entity's own page is paired first.
    """
    from obsidian_wiki.graphrag import _resolve_page, build_index

    index = build_index(vault)
    if entity:
        slug = _resolve_page(index, entity)
        targets = [slug] if slug else []
    else:
        targets = sorted(s for s, e in index.items() if e["category"] == "entities"
                         or e["path"].startswith("entities/"))
    pairs: List[Dict[str, Any]] = []
    truncated = False
    for slug in targets:
        ent = index[slug]
        title = ent["title"]
        name_re = re.compile(rf"(?<![\w-]){re.escape(title)}(?![\w-])", re.I)
        link_re = re.compile(rf"\[\[(?:[^\]|#]*/)?{re.escape(slug)}(?:[|#][^\]]*)?\]\]", re.I)
        pages = [slug] + sorted(set(ent["in_links"]) - {slug})
        found: List[Dict[str, Any]] = []
        for page_slug in pages:
            entry = index[page_slug]
            if _is_pii(entry["tags"]):
                continue
            try:
                text = (vault / entry["path"]).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            _front, body = _split(text)
            for heading, section in _sections(body):
                if page_slug == slug or link_re.search(section) or name_re.search(section):
                    found.append({"page": entry["path"], "title": entry["title"], "heading": heading,
                                  "text": section[:max_section_chars]})
        for i in range(len(found)):
            for j in range(i + 1, len(found)):
                a, b = found[i], found[j]
                if a["page"] == b["page"]:
                    continue
                if len(pairs) >= max_pairs:
                    truncated = True
                    break
                pairs.append({"entity": ent["path"], "entity_title": title, "a": a, "b": b})
            if truncated:
                break
        if truncated:
            break
    return {"pairs": pairs, "truncated": truncated, "entities": [index[s]["path"] for s in targets]}


def _strip_text(pair: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in pair.items() if k not in ("a", "b")}
    for side in ("a", "b"):
        out[side] = {k: v for k, v in pair[side].items() if k != "text"}
    return out


def contradiction_screen(
    pairs: Sequence[Dict[str, Any]],
    cfg: DecisionConfig,
    *,
    backend: Optional[DecisionBackend] = None,
    env: Optional[Mapping[str, str]] = None,
    max_workers: int = 4,
    max_section_chars: int = 1200,
) -> Dict[str, Any]:
    """Screen section pairs; return the ones worth reading, in priority order.

    Never decides that a contradiction exists: the output is a reading list
    for the agent. Priorities: 1 confident contradiction, 2 possible
    contradiction, 3 unscreened (disabled, failed, undecided or order flip),
    4 probably compatible. Pairs the model is confident do not conflict go
    to ``skipped``. Disabled or failed: every pair is priority 3.
    """
    items = list(pairs)

    def unscreened(reason: Optional[str], failed: bool = False) -> Dict[str, Any]:
        rec = _record("contradiction_screen", cfg, failed_open=failed, reason=reason,
                      payload={"fields": ["entity_title", "page_title", "heading", "section_text"], "pairs": 0})
        to_read = [{**_strip_text(p), "priority": 3, "decision": None} for p in items]
        return {"to_read": to_read, "skipped": [], "decision": rec}

    if not cfg.enabled:
        return unscreened("disabled")
    if not items:
        return unscreened("no_pairs")
    try:
        be = _resolve_backend(cfg, backend, env)
    except DecisionError as exc:
        return unscreened(exc.reason, failed=True)

    def ask(i: int) -> Dict[str, Any]:
        pair = items[i]
        rng = _rng(cfg, "contra", pair["a"]["page"], pair["a"]["heading"], pair["b"]["page"], pair["b"]["heading"])
        sides = [pair["a"], pair["b"]]
        rng.shuffle(sides)
        state = {
            "entity": scrub(pair["entity_title"], 160),
            "section_1": {"page": scrub(sides[0]["title"], 160), "heading": scrub(sides[0]["heading"], 160),
                          "text": scrub(sides[0]["text"], max_section_chars)},
            "section_2": {"page": scrub(sides[1]["title"], 160), "heading": scrub(sides[1]["heading"], 160),
                          "text": scrub(sides[1]["text"], max_section_chars)},
        }
        questions = _choice_pair(
            "rel",
            "How do `section_1.text` and `section_2.text` relate in what they say about `entity`?",
            _CONTRA_CRITERIA, cfg, rng,
        )
        try:
            answer = be.ask(state, questions)
            judged = _read_choice_pair(answer.answers, "rel", _CONTRA_OPTIONS, cfg)
        except DecisionError as exc:
            return {"error": exc.reason}
        return {"judged": judged, "latency_ms": answer.latency_ms, "model": answer.model, "usage": answer.usage}

    started = time.perf_counter()
    workers = max(1, min(max_workers, len(items)))
    if workers == 1:
        results = [ask(i) for i in range(len(items))]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(ask, range(len(items))))
    wall_ms = (time.perf_counter() - started) * 1000.0

    to_read: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: Dict[str, int] = {}
    usage = {"input_tokens": 0, "output_tokens": 0}
    models = set()
    for pair, res in zip(items, results):
        row = _strip_text(pair)
        if "error" in res:
            errors[res["error"]] = errors.get(res["error"], 0) + 1
            to_read.append({**row, "priority": 3, "decision": {"failed_open": True, "reason": res["error"]}})
            continue
        j = res["judged"]
        models.add(res["model"])
        for k in usage:
            value = res["usage"].get(k)
            if isinstance(value, int):
                usage[k] += value
        j = {**j, "latency_ms": round(res["latency_ms"], 1)}
        if j["band"] == "fallback":
            prio = 3
        elif j["choice"] == "contradicts":
            prio = 1 if j["band"] == "act" else 2
        elif j["band"] == "act":
            skipped.append({**row, "decision": j})
            continue
        else:
            prio = 4
        to_read.append({**row, "priority": prio, "decision": j})
    to_read.sort(key=lambda r: (r["priority"], -((r["decision"] or {}).get("probabilities", {}).get("contradicts", 0.0))))
    all_failed = len(errors) > 0 and sum(errors.values()) == len(items)
    rec = _record("contradiction_screen", cfg, backend=be, model=",".join(sorted(models)) or None,
                  latency_ms=wall_ms, failed_open=bool(errors), reason=("all_failed" if all_failed else None),
                  usage=usage,
                  payload={"fields": ["entity_title", "page_title", "heading", "section_text"],
                           "pairs": len(items), "answered": len(items) - sum(errors.values())})
    if all_failed:
        rec["sent"] = None  # every call errored; whether any reached the backend is unknown
    rec["errors"] = errors
    rec["counts"] = {"pairs": len(items), "to_read": len(to_read), "skipped": len(skipped)}
    return {"to_read": to_read, "skipped": skipped, "decision": rec}
