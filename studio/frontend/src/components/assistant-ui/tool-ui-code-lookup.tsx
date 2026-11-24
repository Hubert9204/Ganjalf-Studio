// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: compact cards for read_file, grep, glob and the background job tools.

import { partsHaveNonEmptyText } from "@/components/assistant-ui/message-derived";
import { useToolAwaitingApproval } from "@/features/chat/tool-approval";
import { stringifyToolResult } from "@/lib/strip-ansi";
import { type ToolCallMessagePartComponent, useAuiState } from "@assistant-ui/react";
import { FileSearchIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { type ComponentProps } from "react";
import { codeLookupDetail, codeLookupLabel } from "./code-lookup-label";
import { ScrollPane } from "./scroll-pane";
import { isToolCallRunning } from "./tool-arg-text";
import { ToolFallbackContent, ToolFallbackRoot, ToolFallbackTrigger } from "./tool-fallback";
import { useToolActivityOpen } from "./use-tool-activity-open";

function LookupIcon({ strokeWidth: _strokeWidth, ...props }: ComponentProps<"svg">) {
  return <HugeiconsIcon icon={FileSearchIcon} {...props} />;
}

export const CodeLookupToolUI: ToolCallMessagePartComponent = ({
  toolName,
  args,
  result,
  status,
  toolCallId,
}) => {
  const running = isToolCallRunning(status);
  const label = codeLookupLabel(String(toolName), args as Record<string, unknown> | undefined, running);
  const text = result == null ? "" : stringifyToolResult(result);
  const detail = running ? undefined : codeLookupDetail(String(toolName), text) || undefined;
  const hasText = useAuiState(({ message }) => partsHaveNonEmptyText(message.content));
  const awaitingApproval = useToolAwaitingApproval(toolCallId);
  const [open, setOpen] = useToolActivityOpen(running, hasText);
  return (
    <ToolFallbackRoot open={open} onOpenChange={setOpen} awaitingApproval={awaitingApproval}>
      <ToolFallbackTrigger toolName={label} status={status} icon={LookupIcon} detail={detail} singleLine />
      <ToolFallbackContent>
        {text ? (
          <ScrollPane
            className="rounded-lg bg-muted/50 p-2"
            scrollerClassName="max-h-64 overflow-auto whitespace-pre font-mono text-xs"
          >
            {text}
          </ScrollPane>
        ) : null}
      </ToolFallbackContent>
    </ToolFallbackRoot>
  );
};
