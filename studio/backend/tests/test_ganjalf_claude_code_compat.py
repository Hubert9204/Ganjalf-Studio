"""Requests shaped like Claude Code's must validate on /v1/messages."""

from models.inference import AnthropicMessagesRequest


def test_system_turns_between_messages_still_validate():
    request = AnthropicMessagesRequest(
        model = "local",
        messages = [
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "on it"},
            {"role": "system", "content": "context at 80%"},
            {"role": "user", "content": "go on"},
        ],
    )
    assert [m.role for m in request.messages] == ["user", "assistant", "user"]
    texts = [block.text for block in request.messages[-1].content]
    assert "context at 80%" in texts[0] and texts[-1] == "go on"


def test_claude_code_fields_are_accepted():
    request = AnthropicMessagesRequest(
        model = "local",
        max_tokens = 32000,
        stream = True,
        thinking = {"type": "adaptive"},
        output_config = {"effort": "high"},
        context_management = {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
        metadata = {"user_id": "x"},
        tools = [{"name": "Bash", "description": "run", "input_schema": {"type": "object"}}],
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "go", "cache_control": {"type": "ephemeral"}}
                ],
            }
        ],
    )
    assert request.thinking.type == "adaptive"
