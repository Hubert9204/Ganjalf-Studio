"""Ganjalf: honest stop_reason "stop_sequence" for a local GGUF model on /v1/messages."""

from __future__ import annotations

import contextlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.authentication import get_current_subject
from core.inference.llama_cpp import LlamaCppBackend, _earliest_stop, _stop_prefix_suffix
import routes.inference as inference_route
from .llama_backend_double import FakeLlamaCppBackend

STOP = "\n\nHuman:"


def _sse(delta: dict) -> str:
    return "data: " + json.dumps({"choices": [{"index": 0, "delta": delta}]}) + "\n"


def _server(monkeypatch, frames, payloads):
    real = LlamaCppBackend.__new__(LlamaCppBackend)
    real._process = object()
    real._healthy = True
    real._port = 48847
    real._api_key = None
    real._effective_context_length = 4096
    real._supports_reasoning = True
    real._reasoning_always_on = False
    real._reasoning_style = "enable_thinking"
    real._supports_preserve_thinking = False

    @contextlib.contextmanager
    def fake_stream(
        _client,
        _url,
        payload,
        _cancel,
        headers = None,
        first_token_deadline = None,
    ):
        payloads.append(payload)
        yield type("R", (), {"status_code": 200, "chunks": frames, "close": lambda self: None})()

    monkeypatch.setattr(real, "_stream_with_retry", fake_stream)
    monkeypatch.setattr(
        real,
        "_iter_text_cancellable",
        lambda response, _c, first_token_deadline = None: iter(response.chunks),
    )
    monkeypatch.setattr(real, "_maybe_recover_from_mtp_crash", lambda *_a, **_k: False)
    monkeypatch.setattr(
        real,
        "_llama_post_json",
        lambda path, body: {"tokens": list(range(len(body["content"].split())))}
        if path == "/tokenize"
        else None,
    )
    return real


def _frames(*pieces, reasoning = None):
    frames = [_sse({"reasoning_content": reasoning})] if reasoning else []
    frames += [_sse({"content": piece}) for piece in pieces]
    frames.append("data: [DONE]\n")
    return frames


def _drain(
    backend,
    stop_report,
    stop = (STOP,),
):
    return list(
        backend.generate_chat_completion(
            messages = [{"role": "user", "content": "hi"}],
            stop = list(stop),
            stop_report = stop_report,
        )
    )


def test_helpers():
    assert _earliest_stop("a\n\nHuman: b", [STOP, "b"]) == (1, STOP)
    assert _earliest_stop("abc", ["x"]) is None
    assert _stop_prefix_suffix("hello\n\nHu", [STOP]) == 4
    assert _stop_prefix_suffix("hello", [STOP]) == 0


def test_the_generator_cuts_at_the_match_and_never_shows_a_partial(monkeypatch):
    payloads: list = []
    backend = _server(monkeypatch, _frames("Hello wor", "ld\n\nHu", "man: more", " text"), payloads)
    report: dict = {}
    events = _drain(backend, report)
    texts = [e for e in events if isinstance(e, str)]
    meta = [e for e in events if isinstance(e, dict) and e.get("type") == "metadata"]

    assert "stop" not in payloads[0]  # enforced here, not by llama-server
    assert texts[-1] == "Hello world"
    assert all("\n\nH" not in t for t in texts)
    assert all(b.startswith(a) for a, b in zip(texts, texts[1:]))  # cumulative stays monotonic
    assert report == {"hit": STOP}
    assert meta[-1]["finish_reason"] == "stop_sequence"
    assert meta[-1]["usage"]["completion_tokens"] > 0


def test_a_partial_match_at_the_end_is_released(monkeypatch):
    backend = _server(monkeypatch, _frames("Bye\n\nHu"), [])
    report: dict = {}
    texts = [e for e in _drain(backend, report) if isinstance(e, str)]
    assert texts[-1] == "Bye\n\nHu" and report == {}


def test_reasoning_is_not_cut(monkeypatch):
    backend = _server(monkeypatch, _frames("Answer.", reasoning = "I could say \n\nHuman: here"), [])
    report: dict = {}
    texts = [e for e in _drain(backend, report) if isinstance(e, str)]
    assert texts[-1].endswith("</think>Answer.") and report == {}


def test_without_a_report_llama_server_still_gets_the_stops(monkeypatch):
    payloads: list = []
    backend = _server(monkeypatch, _frames("Hello"), payloads)
    list(
        backend.generate_chat_completion(messages = [{"role": "user", "content": "hi"}], stop = [STOP])
    )
    assert payloads[0]["stop"] == [STOP]


class _Gguf(FakeLlamaCppBackend):
    supports_reasoning = False
    supports_tools = False

    def __init__(self, real):
        self._real = real

    def _request_reasoning_kwargs(self, *args, **kwargs):
        return {}

    def count_chat_tokens(self, *args, **kwargs):
        return 3

    def generate_chat_completion(self, **kwargs):
        return self._real.generate_chat_completion(**kwargs)


def _messages(monkeypatch, frames, *, stream):
    backend = _Gguf(_server(monkeypatch, frames, []))
    monkeypatch.setattr(inference_route, "get_llama_cpp_backend", lambda: backend)
    app = FastAPI()
    app.include_router(inference_route.router, prefix = "/v1")
    app.dependency_overrides[get_current_subject] = lambda: "test-user"
    return TestClient(app).post(
        "/v1/messages",
        json = {
            "model": "local",
            "max_tokens": 64,
            "stream": stream,
            "stop_sequences": [STOP, "###"],
            "messages": [{"role": "user", "content": "hi"}],
        },
    )


def test_messages_json_names_the_stop_sequence(monkeypatch):
    response = _messages(monkeypatch, _frames("Sure.", "\n\nHuman: no"), stream = False)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stop_reason"] == "stop_sequence"
    assert body["stop_sequence"] == STOP
    assert body["content"][-1]["text"] == "Sure."


def test_messages_stream_names_the_stop_sequence(monkeypatch):
    response = _messages(monkeypatch, _frames("One ", "two ###", " three"), stream = True)
    assert response.status_code == 200, response.text
    deltas, text = [], ""
    for line in response.text.splitlines():
        if not line.startswith("data: {"):
            continue
        data = json.loads(line[len("data: ") :])
        if data.get("type") == "message_delta":
            deltas.append(data["delta"])
        if data.get("type") == "content_block_delta" and data["delta"].get("type") == "text_delta":
            text += data["delta"]["text"]
    assert deltas[-1]["stop_reason"] == "stop_sequence" and deltas[-1]["stop_sequence"] == "###"
    assert text == "One two "


def test_messages_without_a_match_end_the_turn(monkeypatch):
    body = _messages(monkeypatch, _frames("All done."), stream = False).json()
    assert body["stop_reason"] == "end_turn" and body["stop_sequence"] is None
