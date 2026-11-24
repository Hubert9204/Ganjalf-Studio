// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

import { installLocalStorageFake, readSrc } from "./helpers/kit.ts";

installLocalStorageFake();
register("./store-settings-resolver.mjs", import.meta.url);

const { applyQwenThinkingParams } = await import(
  "../src/features/chat/utils/qwen-params.ts"
);
const { resolveQwenThinkingParams } = await import(
  "../src/features/chat/utils/qwen-sampling-table.ts"
);
const { useChatRuntimeStore } = await import(
  "../src/features/chat/stores/chat-runtime-store.ts"
);

test("Qwen3.8 reuses the Qwen3.6 sampling table in both modes", () => {
  for (const thinkingOn of [true, false]) {
    const qwen36 = resolveQwenThinkingParams(
      "unsloth/Qwen3.6-27B-GGUF",
      thinkingOn,
    );
    const qwen38 = resolveQwenThinkingParams(
      "unsloth/Qwen3.8-27B-GGUF",
      thinkingOn,
    );

    assert.deepEqual(qwen38, qwen36);
    // Ganjalf: thinking pins presence to 0; non-thinking keeps the family's 1.5.
    assert.equal(qwen38?.presencePenalty, thinkingOn ? 0 : 1.5);
  }
});

test("an Ollama Qwen3.5 MLX tag gets the table by its checkpoint", () => {
  const checkpoint = "/h/.studio_links/0c918e29a9/mlx/qwen3.5-4b-mlx";
  assert.equal(resolveQwenThinkingParams(checkpoint, true)?.presencePenalty, 0);
  assert.equal(resolveQwenThinkingParams(checkpoint, false)?.presencePenalty, 1.5);
});

test("the Qwen3.8 Think toggle puts the mode's presence in the live chat settings", () => {
  for (const thinkingOn of [true, false]) {
    const store = useChatRuntimeStore.getState();
    useChatRuntimeStore.setState({
      params: {
        ...store.params,
        checkpoint: "unsloth/Qwen3.8-27B-GGUF",
        presencePenalty: 0.7,
      },
      activePresetSource: "builtin-default",
    });

    applyQwenThinkingParams(thinkingOn);

    assert.equal(
      useChatRuntimeStore.getState().params.presencePenalty,
      thinkingOn ? 0 : 1.5,
    );
  }
});

test("every status merge is wired to the active Qwen thinking table", () => {
  const source = readSrc(
    "features/chat/lib/apply-inference-status-to-store.ts",
  );
  assert.match(
    source,
    /if \(status\.inference && supportsReasoning\) \{[\s\S]*?resolveQwenThinkingParams\(\s*checkpointId,\s*reasoningAlwaysOn \|\| current\.reasoningEnabled,\s*\)/,
  );
});

test("Qwen3.8 does not change the generic Qwen3 presence penalty", () => {
  assert.equal(
    resolveQwenThinkingParams("unsloth/Qwen3-8B-GGUF", true)?.presencePenalty,
    undefined,
  );
});
