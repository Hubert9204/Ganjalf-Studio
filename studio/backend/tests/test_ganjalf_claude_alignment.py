# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Claude (Anthropic Messages API) alignment: ping after message_start, message_delta usage that
never wipes the input count, thinking budgets on the chat path, the Models API shape for Anthropic
clients, and a request-id header on Messages answers."""

import ast
import asyncio
import json
from pathlib import Path

from core.inference.anthropic_compat import (
    ANTHROPIC_PING_EVENT,
    AnthropicPassthroughEmitter,
    AnthropicStreamEmitter,
    _message_delta_usage,
)
from models.inference import ChatCompletionRequest, requested_thinking_budget

BACKEND = Path(__file__).resolve().parents[1]


def _events(lines):
    return [json.loads(line.split("data: ", 1)[1]) for line in lines]


def test_ping_follows_message_start_on_both_emitters():
    for emitter in (AnthropicStreamEmitter(), AnthropicPassthroughEmitter()):
        lines = emitter.start("msg_1", "m", input_tokens = 12)
        assert [event["type"] for event in _events(lines)] == ["message_start", "ping"]
        assert lines[1] == ANTHROPIC_PING_EVENT == 'event: ping\ndata: {"type": "ping"}\n\n'


def test_a_full_stream_keeps_anthropic_event_order():
    emitter = AnthropicStreamEmitter()
    lines = emitter.start("msg_1", "m", input_tokens = 7)
    lines += emitter.feed({"type": "content", "text": "<think>plan</think>Hi"})
    lines += emitter.feed({"type": "metadata", "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    lines += emitter.finish("end_turn")
    names = [event["type"] for event in _events(lines)]
    assert names[:2] == ["message_start", "ping"]
    assert names[-2:] == ["message_delta", "message_stop"]
    assert names.count("content_block_start") == names.count("content_block_stop")
    blocks = [event["content_block"]["type"] for event in _events(lines) if event["type"] == "content_block_start"]
    assert blocks == ["thinking", "text"]


def test_message_delta_usage_never_reports_an_unknown_input_count():
    assert _message_delta_usage(None) == {"output_tokens": 0}
    assert _message_delta_usage({"completion_tokens": 9}) == {"output_tokens": 9}
    assert _message_delta_usage(
        {"prompt_tokens": 100, "completion_tokens": 9, "prompt_tokens_details": {"cached_tokens": 40}}
    ) == {"input_tokens": 60, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 40, "output_tokens": 9}


def test_chat_requests_carry_a_thinking_budget():
    def request(**fields):
        return ChatCompletionRequest(messages = [{"role": "user", "content": "hi"}], **fields)

    assert requested_thinking_budget(request()) is None
    assert requested_thinking_budget(request(thinking = {"type": "enabled", "budget_tokens": 512})) == 512
    assert requested_thinking_budget(request(thinking = {"type": "disabled", "budget_tokens": 512})) is None
    assert requested_thinking_budget(
        request(thinking_budget_tokens = 2048, thinking = {"type": "enabled", "budget_tokens": 512})
    ) == 2048


def test_both_gguf_chat_paths_forward_the_budget():
    source = (BACKEND / "routes" / "inference.py").read_text(encoding = "utf-8")
    assert source.count("thinking_budget_tokens = requested_thinking_budget(payload)") == 2


def test_models_list_and_retrieve_take_the_anthropic_shape_on_request(monkeypatch):
    import routes.inference as inf

    async def catalog(quant_pins = False):
        return [{"id": "org/model-GGUF", "object": "model", "created": 1764000000, "owned_by": "org"}]

    monkeypatch.setattr(inf, "_openai_catalog_with_aliases", catalog)

    class _Request:
        def __init__(self, headers):
            self.headers = headers

    plain = asyncio.run(inf.openai_list_models(current_subject = "t", request = _Request({})))
    assert plain == {"object": "list", "data": [{"id": "org/model-GGUF", "object": "model", "created": 1764000000, "owned_by": "org"}]}
    anthropic = asyncio.run(
        inf.openai_list_models(current_subject = "t", request = _Request({"anthropic-version": "2023-06-01"}))
    )
    assert anthropic["has_more"] is False and anthropic["first_id"] == anthropic["last_id"] == "org/model-GGUF"
    entry = anthropic["data"][0]
    assert entry["type"] == "model" and entry["display_name"] == "org/model-GGUF"
    assert entry["created_at"] == "2025-11-24T16:00:00Z" and entry["object"] == "model"
    # Called without a request (as older callers do): the OpenAI shape.
    assert asyncio.run(inf.openai_list_models(current_subject = "t")) == plain


def test_messages_answers_carry_a_request_id():
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from fastapi.testclient import TestClient

    source = (BACKEND / "main.py").read_text(encoding = "utf-8")
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AnthropicRequestIdMiddleware")
    namespace: dict = {}
    exec(
        "from starlette.datastructures import MutableHeaders\nimport uuid as _uuid_for_request_id\n"
        + ast.get_source_segment(source, node),
        namespace,
    )
    assert "app.add_middleware(AnthropicRequestIdMiddleware)" in source
    app = FastAPI()

    @app.post("/v1/messages")
    def messages():
        return StreamingResponse(iter([ANTHROPIC_PING_EVENT]), media_type = "text/event-stream")

    @app.get("/v1/models")
    def models():
        return {}

    app.add_middleware(namespace["AnthropicRequestIdMiddleware"])
    client = TestClient(app)
    assert client.post("/v1/messages").headers["request-id"].startswith("req_")
    assert "request-id" not in client.get("/v1/models").headers


def _chunk(finish = None, usage = None, **delta):
    body = {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage:
        body["usage"] = usage
    return body


def test_tool_arguments_split_across_chunks_stream_as_input_json_deltas():
    emitter = AnthropicPassthroughEmitter()
    lines = emitter.start("msg_1", "m")
    lines += emitter.feed_chunk(
        _chunk(tool_calls = [{"index": 0, "id": "c1", "type": "function", "function": {"name": "Read", "arguments": ""}}])
    )
    for part in ('{"file_pa', 'th": "a.p', 'y"}'):
        lines += emitter.feed_chunk(_chunk(tool_calls = [{"index": 0, "function": {"arguments": part}}]))
    lines += emitter.feed_chunk(_chunk(finish = "tool_calls", usage = {"prompt_tokens": 5, "completion_tokens": 4}))
    lines += emitter.finish()
    events = _events(lines)
    start = next(event for event in events if event["type"] == "content_block_start")
    assert start["content_block"]["type"] == "tool_use" and start["content_block"]["id"].startswith("toolu_")
    partial = "".join(
        event["delta"]["partial_json"] for event in events if event.get("delta", {}).get("type") == "input_json_delta"
    )
    assert json.loads(partial) == {"file_path": "a.py"}
    assert events[-2]["delta"]["stop_reason"] == "tool_use"


def test_a_reply_without_thinking_has_no_thinking_block():
    emitter = AnthropicStreamEmitter()
    lines = emitter.start("msg_1", "m")
    lines += emitter.feed({"type": "content", "text": "Just text."})
    lines += emitter.finish("max_tokens")
    events = _events(lines)
    assert [e["content_block"]["type"] for e in events if e["type"] == "content_block_start"] == ["text"]
    assert events[-2]["delta"]["stop_reason"] == "max_tokens"


def _messages_route(monkeypatch, generate):
    from types import SimpleNamespace

    import routes.inference as inf
    from core.inference.llama_admission import reset_llama_admission_queues
    from models.inference import AnthropicMessagesRequest

    reset_llama_admission_queues()
    monkeypatch.setattr(inf, "current_date_prompt_line", lambda **_kwargs: "")
    backend = SimpleNamespace(
        is_loaded = True,
        is_vision = False,
        supports_tools = True,
        model_identifier = "test-model",
        context_length = 4096,
        count_chat_tokens = lambda *args, **kwargs: 7,
        generate_chat_completion = generate,
        generate_chat_completion_with_tools = generate,
    )
    monkeypatch.setattr(inf, "get_llama_cpp_backend", lambda: backend)

    class _Request:
        state = SimpleNamespace()
        url = SimpleNamespace(path = "/v1/messages")
        method = "POST"
        headers = {}

        async def is_disconnected(self):
            return False

    async def run(**fields):
        payload = AnthropicMessagesRequest(max_tokens = 64, messages = [{"role": "user", "content": "hi"}], **fields)
        response = await inf.anthropic_messages(payload, request = _Request(), current_subject = "t")
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    return run


_OVERFLOW = "llama-server error 400: the request (9000 tokens) exceeds the available context size (4096 tokens), try increasing it"


def test_a_prompt_over_the_context_window_is_a_clear_400(monkeypatch):
    import pytest
    from fastapi import HTTPException

    def overflow(**kwargs):
        raise RuntimeError(_OVERFLOW)
        yield ""

    run = _messages_route(monkeypatch, overflow)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(run())
    assert caught.value.status_code == 400
    error = caught.value.detail["error"]
    assert error["type"] == "invalid_request_error"
    assert "9000 tokens exceeds the 4096-token context window" in error["message"]


def test_a_stream_that_overflows_ends_with_an_error_event_not_message_stop(monkeypatch):
    def overflow(**kwargs):
        raise RuntimeError(_OVERFLOW)
        yield ""

    text = asyncio.run(_messages_route(monkeypatch, overflow)(stream = True))
    names = [line.split("event: ", 1)[1] for line in text.splitlines() if line.startswith("event: ")]
    assert names == ["message_start", "ping", "error"]
    error = json.loads(text.rsplit("data: ", 1)[1])
    assert error["error"]["type"] == "invalid_request_error" and "context window" in error["error"]["message"]
