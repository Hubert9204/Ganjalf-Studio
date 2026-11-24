# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

# Used when a request leaves max_tool_calls_per_message unset (API clients). Ganjalf's UI sends no cap
# (Max) by default; see GANJALF_TOOL_FAILURE_STREAK for how such a run stops.
DEFAULT_MAX_TOOL_CALLS_PER_MESSAGE = 50
