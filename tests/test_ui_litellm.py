"""The viewer's Ask page through LiteLLM: provider choice, settings, and the call.

litellm and openai are stubbed, so these run without the optional extra.
"""

from __future__ import annotations

import os
import sys
import types
from types import SimpleNamespace
from unittest import mock

import pytest

from obsidian_wiki import ui_tools


class _APIError(Exception):
    pass


class _AuthenticationError(_APIError):
    pass


class _RateLimitError(_APIError):
    pass


class _APIConnectionError(_APIError):
    pass


class _InternalServerError(_APIError):
    pass


class _ServiceUnavailableError(_APIError):
    pass


def _response(content="An answer [[concepts/a.md]].", finish_reason="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)]
    )


@pytest.fixture
def fake_litellm(monkeypatch):
    fake = types.ModuleType("litellm")
    fake.completion = mock.MagicMock(name="litellm.completion", return_value=_response())
    fake.completion_cost = mock.MagicMock(name="litellm.completion_cost", return_value=0.0042)
    fake.suppress_debug_info = False
    fake.exceptions = SimpleNamespace(
        AuthenticationError=_AuthenticationError,
        RateLimitError=_RateLimitError,
        APIConnectionError=_APIConnectionError,
        InternalServerError=_InternalServerError,
        ServiceUnavailableError=_ServiceUnavailableError,
    )
    fake_openai = types.ModuleType("openai")
    fake_openai.APIError = _APIError
    monkeypatch.setitem(sys.modules, "litellm", fake)
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    return fake


@pytest.fixture
def settings_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_tools.time, "sleep", lambda _: None)
    monkeypatch.setattr(ui_tools, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(ui_tools.shutil, "which", lambda _: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


def test_litellm_is_chosen_only_explicitly_and_needs_a_model(fake_litellm, settings_dir):
    assert ui_tools.resolve_provider({"provider": "auto", "model": "gemini/gemini-2.5-flash"}) is None
    assert ui_tools.resolve_provider({"provider": "litellm"}) is None
    assert ui_tools.resolve_provider({"provider": "litellm", "model": "gemini/gemini-2.5-flash"}) == "litellm"


def test_litellm_needs_the_package(settings_dir, monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    assert ui_tools.resolve_provider({"provider": "litellm", "model": "gemini/gemini-2.5-flash"}) is None
    assert ui_tools.public_settings({})["litellm_installed"] is False
    with pytest.raises(ui_tools.UiError) as err:
        ui_tools._ask_litellm("system", "prompt", False, {"model": "gemini/gemini-2.5-flash"})
    assert err.value.status == 501 and "[litellm]" in str(err.value)


def test_settings_store_the_litellm_key_without_exposing_it(fake_litellm, settings_dir):
    shown = ui_tools.save_settings({
        "provider": "litellm",
        "model": "gpt-4.1-mini",
        "litellm_api_base": "http://localhost:4000",
        "litellm_api_key": "sk-proxy-secret-9876",
    })

    assert shown["active_provider"] == "litellm"
    assert shown["litellm_installed"] is True
    assert shown["litellm_api_base"] == "http://localhost:4000"
    assert shown["litellm_key_set"] and shown["litellm_key_hint"] == "…9876"
    assert "secret" not in str(shown)
    if os.name != "nt":  # Windows has no group/other permission bits to check
        assert (settings_dir / "ui-settings.json").stat().st_mode & 0o077 == 0
    assert not ui_tools.save_settings({"litellm_api_key": ""})["litellm_key_set"]


def test_ask_litellm_sends_the_context_and_reports_cost(fake_litellm, settings_dir):
    answer, cost = ui_tools._ask_litellm(
        "system prompt", "vault context", False, {"model": "gemini/gemini-2.5-flash"}
    )

    assert answer == "An answer [[concepts/a.md]]."
    assert cost == pytest.approx(0.0042)
    assert fake_litellm.suppress_debug_info is True
    kwargs = fake_litellm.completion.call_args.kwargs
    assert kwargs["model"] == "gemini/gemini-2.5-flash"
    assert kwargs["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "vault context"},
    ]
    assert kwargs["drop_params"] is True
    # litellm's num_retries needs tenacity, which litellm does not install.
    assert "num_retries" not in kwargs
    # No key or base unless set: LiteLLM reads GEMINI_API_KEY, AWS credentials, ...
    for absent in ("api_key", "api_base", "web_search_options", "extra_body"):
        assert absent not in kwargs


def test_ask_litellm_web_search_and_proxy_settings(fake_litellm, settings_dir):
    ui_tools._ask_litellm(
        "s", "p", True,
        {"model": "litellm_proxy/gpt-5-nano", "litellm_api_base": "http://localhost:4000",
         "litellm_api_key": "sk-proxy"},
    )

    kwargs = fake_litellm.completion.call_args.kwargs
    assert kwargs["web_search_options"] == {"search_context_size": "medium"}
    assert kwargs["api_base"] == "http://localhost:4000"
    assert kwargs["api_key"] == "sk-proxy"
    # The proxy forwards requests unchanged, so it is asked to drop unsupported params.
    assert kwargs["extra_body"] == {"drop_params": True}


def test_unpriced_models_report_no_cost(fake_litellm, settings_dir):
    fake_litellm.completion_cost.side_effect = Exception("This model isn't mapped yet")
    assert ui_tools._ask_litellm("s", "p", False, {"model": "ollama/qwen3"})[1] is None
    fake_litellm.completion_cost.side_effect = None
    fake_litellm.completion_cost.return_value = 0.0
    assert ui_tools._ask_litellm("s", "p", False, {"model": "ollama/qwen3"})[1] is None


def test_transient_errors_are_retried_and_others_are_not(fake_litellm, settings_dir):
    fake_litellm.completion.side_effect = [_ServiceUnavailableError("busy"), _response("second try")]
    assert ui_tools._ask_litellm("s", "p", False, {"model": "gemini/gemini-2.5-flash"})[0] == "second try"
    assert fake_litellm.completion.call_count == 2

    fake_litellm.completion.reset_mock()
    fake_litellm.completion.side_effect = _RateLimitError("slow down")
    with pytest.raises(ui_tools.UiError):
        ui_tools._ask_litellm("s", "p", False, {"model": "gemini/gemini-2.5-flash"})
    assert fake_litellm.completion.call_count == ui_tools.LITELLM_ATTEMPTS

    fake_litellm.completion.reset_mock()
    fake_litellm.completion.side_effect = _AuthenticationError("bad key")
    with pytest.raises(ui_tools.UiError):
        ui_tools._ask_litellm("s", "p", False, {"model": "gemini/gemini-2.5-flash"})
    assert fake_litellm.completion.call_count == 1


@pytest.mark.parametrize(
    "error, status, text",
    [
        (_AuthenticationError("bad key"), 401, "rejected the API key"),
        (_RateLimitError("slow down"), 429, "rate limit"),
        (_APIConnectionError("refused"), 502, "couldn't reach"),
        (_APIError("Unknown model id"), 502, "Unknown model id"),
    ],
)
def test_provider_errors_become_readable_ui_errors(fake_litellm, settings_dir, error, status, text):
    fake_litellm.completion.side_effect = error
    with pytest.raises(ui_tools.UiError) as err:
        ui_tools._ask_litellm("s", "p", False, {"model": "gemini/gemini-2.5-flash"})
    assert err.value.status == status and text in str(err.value)


def test_a_filtered_empty_answer_is_a_refusal(fake_litellm, settings_dir):
    fake_litellm.completion.return_value = _response(content=None, finish_reason="content_filter")
    with pytest.raises(ui_tools.UiError) as err:
        ui_tools._ask_litellm("s", "p", False, {"model": "azure/gpt-4.1-mini"})
    assert err.value.status == 422


def test_ask_routes_to_litellm(fake_litellm, settings_dir, tmp_path, monkeypatch):
    ui_tools.save_settings({"provider": "litellm", "model": "gemini/gemini-2.5-flash", "web": False})
    monkeypatch.setattr(ui_tools, "_context", lambda vault, q: ("PACK", [{"path": "concepts/a.md", "title": "A"}]))

    result = ui_tools.ask(tmp_path, "What do I know about A?")

    assert result["provider"] == "litellm"
    assert result["cost_usd"] == pytest.approx(0.0042)
    assert result["pages"] == [{"path": "concepts/a.md", "title": "A"}]
    sent = fake_litellm.completion.call_args.kwargs["messages"][1]["content"]
    assert sent.startswith("PACK") and sent.endswith("Question: What do I know about A?")


@pytest.mark.parametrize(
    "model, known, searches, expect_web",
    [
        ("ollama/qwen3", True, False, False),  # known, no web search
        ("gemini/gemini-2.5-flash", True, True, True),  # known, searches
        ("litellm_proxy/team-model", True, False, True),  # proxy alias: unknown client-side
        ("custom/new-model", False, False, True),  # not in LiteLLM's map
    ],
)
def test_web_search_is_only_promised_to_models_that_can_search(
    fake_litellm, settings_dir, tmp_path, monkeypatch, model, known, searches, expect_web
):
    def model_info(model):
        if not known:
            raise Exception("This model isn't mapped yet.")
        return {}

    fake_litellm.get_model_info = mock.MagicMock(side_effect=model_info)
    fake_litellm.supports_web_search = mock.MagicMock(return_value=searches)
    ui_tools.save_settings({"provider": "litellm", "model": model, "web": True})
    monkeypatch.setattr(ui_tools, "_context", lambda vault, q: ("PACK", []))

    result = ui_tools.ask(tmp_path, "What changed this week?")

    kwargs = fake_litellm.completion.call_args.kwargs
    system = kwargs["messages"][0]["content"]
    assert result["web"] is expect_web
    assert ("web_search_options" in kwargs) is expect_web
    assert ("Search the web" in system) is expect_web
