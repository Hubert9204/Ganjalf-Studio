# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

"""Ganjalf's agentic protocol in the tool nudge, the tool-error nudge, and the tool-request presence cap."""

from pathlib import Path

import pytest

from core.inference import agentic_protocol as ap

PARTS = Path(__file__).resolve().parents[2] / "ganjalf_prompts" / "sections"
WEB = [{"type": "function", "function": {"name": "web_search", "parameters": {"properties": {}}}}]


@pytest.fixture(autouse = True)
def _default_mode(monkeypatch):
    monkeypatch.delenv("GANJALF_AGENT_PROTOCOL", raising = False)
    monkeypatch.delenv("GANJALF_AGENT_PROTOCOL_DIR", raising = False)
    monkeypatch.delenv("GANJALF_AGENTIC_PRESENCE_PENALTY", raising = False)
    ap._render.cache_clear()


@pytest.mark.parametrize(
    "model_name, family",
    [
        ("unsloth/Qwen3.6-35B-A3B-MTP-GGUF", "qwen"),
        ("Qwen/Qwen3.8-27B", "qwen"),
        ("/models/qwq-32b-q4_k_m.gguf", "qwen"),
        ("unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF", "nemotron"),
        ("google/gemma-4-31b-it", "gemma"),
        ("unsloth/medgemma-27b-it", "gemma"),
        ("nvidia/parakeet-nemotron-asr", None),
        ("Qwen/Qwen3-Embedding-8B", None),
        ("meta-llama/Llama-3.3-70B-Instruct", None),
        ("", None),
        (None, None),
    ],
)
def test_family(model_name, family):
    assert ap.model_family(model_name) == family


def test_qwen_gets_core_and_its_addendum():
    text = ap.agentic_protocol("unsloth/Qwen3.6-35B-A3B-MTP-GGUF", 35)
    core = (PARTS / "core.md").read_text(encoding = "utf-8").strip()
    assert text.startswith(ap.PROTOCOL_MARKER)
    assert text.startswith(core)
    assert "Notes for this model (Qwen)" in text
    assert "Nemotron" not in text


def test_matches_the_built_copy_paste_prompt():
    built = (PARTS.parent / "agentic-nemotron.md").read_text(encoding = "utf-8").strip()
    assert ap.agentic_protocol("NVIDIA-Nemotron-3-Super-120B-A12B", 120) == built


def test_small_unknown_and_off():
    assert ap.agentic_protocol("Qwen3.5-4B", 4) == ""
    assert ap.agentic_protocol("Llama-3.3-70B", 70) == ""


def test_all_mode_gives_unknown_families_the_generic_text(monkeypatch):
    monkeypatch.setenv("GANJALF_AGENT_PROTOCOL", "all")
    text = ap.agentic_protocol("Llama-3.3-70B", 70)
    assert text.startswith(ap.PROTOCOL_MARKER) and "Notes for this model" not in text


def test_off_mode(monkeypatch):
    monkeypatch.setenv("GANJALF_AGENT_PROTOCOL", "off")
    assert ap.agentic_protocol("Qwen3.8-27B", 27) == ""


def test_missing_prompts_folder_falls_back_to_the_plain_nudge(monkeypatch, tmp_path):
    monkeypatch.setenv("GANJALF_AGENT_PROTOCOL_DIR", str(tmp_path / "nowhere"))
    assert ap.agentic_protocol("Qwen3.8-27B", 27) == ""


def test_parts_hold_no_rule_line_so_the_cut_point_is_unambiguous():
    for part in PARTS.glob("*.md"):
        assert "\n---\n" not in part.read_text(encoding = "utf-8"), part.name


def test_a_pasted_preset_keeps_the_only_copy():
    protocol = ap.agentic_protocol("Qwen3.8-27B", 27)
    nudge = ap.with_protocol(protocol, "Tools are available.")
    assert nudge.startswith(protocol)
    assert ap.drop_repeated_protocol("Be brief.", nudge) == nudge
    assert ap.drop_repeated_protocol(protocol + "\n\nExtra rules.", nudge) == "Tools are available."
    assert ap.drop_repeated_protocol(protocol, ap.with_protocol(protocol, "")) == ""
    # A nudge without the protocol is left alone even under a preset.
    assert ap.drop_repeated_protocol(protocol, "Tools are available.") == "Tools are available."


def test_tool_nudge_starts_with_the_protocol_for_local_families():
    from routes.inference import _TOOL_BASE_NUDGE, _build_tool_action_nudge

    qwen = _build_tool_action_nudge(tools = WEB, model_name = "unsloth/Qwen3.8-27B-GGUF")
    assert qwen.startswith(ap.PROTOCOL_MARKER)
    assert qwen.endswith(_build_tool_action_nudge(tools = WEB, model_name = "test-27B"))
    assert _TOOL_BASE_NUDGE in qwen


def test_external_full_access_only_nudge_never_carries_it():
    from routes.inference import _build_tool_action_nudge
    nudge = _build_tool_action_nudge(
        tools = WEB, model_name = "Qwen3.8-27B", full_access = True, full_access_only = True
    )
    assert ap.PROTOCOL_MARKER not in nudge


def test_memory_only_nudge_stays_without_it():
    from routes.inference import _build_tool_action_nudge
    memory = [{"type": "function", "function": {"name": "update_memory", "parameters": {}}}]
    assert ap.PROTOCOL_MARKER not in _build_tool_action_nudge(
        tools = memory, model_name = "Qwen3.8-27B"
    )


def test_append_to_system_message_drops_the_repeat():
    from routes.inference import _append_to_system_message

    protocol = ap.agentic_protocol("Qwen3.8-27B", 27)
    nudge = ap.with_protocol(protocol, "Tools are available.")
    merged = _append_to_system_message([{"role": "system", "content": protocol}], nudge)
    assert merged[0]["content"].count(ap.PROTOCOL_MARKER) == 1
    assert merged[0]["content"].endswith("Tools are available.")


def test_tool_error_nudge_asks_for_a_changed_retry():
    from core.inference.tool_call_parser import TOOL_ERROR_NUDGE

    assert TOOL_ERROR_NUDGE.startswith("\n\n")
    assert "never the identical call" in TOOL_ERROR_NUDGE
    assert "Do not report this step as done" in TOOL_ERROR_NUDGE
    # tools.py reserves room for it in every failed result; keep it short.
    assert len(TOOL_ERROR_NUDGE) < 300


class TestAgenticPresenceCap:
    @staticmethod
    def _presence(
        monkeypatch,
        *,
        agentic,
        explicit = None,
        saved = None,
        env = None,
        thinking = False,
    ):
        from utils.inference import inference_config as cfg

        if env is not None:
            monkeypatch.setenv("GANJALF_AGENTIC_PRESENCE_PENALTY", env)
        monkeypatch.delenv("UNSLOTH_SAMPLING_PRESENCE_PENALTY", raising = False)
        monkeypatch.setattr(
            cfg, "_recommended_sampling", lambda model_id: {"presence_penalty": 1.5}
        )
        monkeypatch.setattr(cfg, "_saved_sampling", lambda model_id: saved or {})
        effective = cfg.resolve_effective_sampling(
            "unsloth/Qwen3.8-27B-GGUF",
            {"presence_penalty": explicit},
            thinking = thinking,
            agentic = agentic,
        )
        return effective["presence_penalty"]

    def test_a_tool_request_gets_the_cap(self, monkeypatch):
        assert self._presence(monkeypatch, agentic = True) == 0.0

    def test_a_plain_chat_keeps_the_family_value(self, monkeypatch):
        assert self._presence(monkeypatch, agentic = False) == 1.5

    def test_the_client_value_still_wins(self, monkeypatch):
        assert self._presence(monkeypatch, agentic = True, explicit = 1.2) == 1.2

    def test_a_saved_default_still_wins(self, monkeypatch):
        assert self._presence(monkeypatch, agentic = True, saved = {"presence_penalty": 1.0}) == 1.0

    def test_thinking_recommends_zero_even_without_tools(self, monkeypatch):
        # Ganjalf: Qwen3.5/3.6/3.8 with thinking default to 0; the cap's "off" does not bring 1.5 back.
        assert self._presence(monkeypatch, agentic = False, thinking = True) == 0.0
        assert self._presence(monkeypatch, agentic = True, thinking = True, env = "off") == 0.0

    def test_thinking_keeps_an_explicit_or_saved_value(self, monkeypatch):
        assert self._presence(monkeypatch, agentic = False, thinking = True, explicit = 1.5) == 1.5
        assert (
            self._presence(
                monkeypatch, agentic = False, thinking = True, saved = {"presence_penalty": 1.0}
            )
            == 1.0
        )

    def test_env_sets_or_disables_it(self, monkeypatch):
        assert self._presence(monkeypatch, agentic = True, env = "0.5") == 0.5
        assert self._presence(monkeypatch, agentic = True, env = "off") == 1.5
        assert self._presence(monkeypatch, agentic = True, env = "banana") == 0.0


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"tools": [{"type": "function"}]}, True),
        ({"tools": [{"type": "function"}], "tool_choice": "none"}, False),
        ({"enable_tools": True}, True),
        ({"tools": None, "enable_tools": False}, False),
    ],
)
def test_payload_offers_tools(fields, expected):
    from types import SimpleNamespace

    from routes.inference import _payload_offers_tools

    payload = SimpleNamespace(
        **{"tools": None, "enable_tools": None, "tool_choice": None, **fields}
    )
    assert _payload_offers_tools(payload) is expected


@pytest.mark.parametrize(
    "choice, expected",
    [(None, True), ({"type": "auto"}, True), ({"type": "none"}, False), ("none", False)],
)
def test_anthropic_offers_tools(choice, expected):
    from types import SimpleNamespace

    from routes.inference import _anthropic_offers_tools

    payload = SimpleNamespace(tools = [{"name": "x"}], enable_tools = None, tool_choice = choice)
    assert _anthropic_offers_tools(payload) is expected
