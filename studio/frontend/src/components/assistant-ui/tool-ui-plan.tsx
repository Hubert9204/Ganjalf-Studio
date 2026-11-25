// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: the plan the model presented in plan mode (exit_plan_mode), with approve / change.

import { PLAN_APPROVED_TEXT, planJustPresented, usePlanModeStore } from "@/features/chat";
import { useT } from "@/i18n";
import { type ToolCallMessagePartComponent, useAui } from "@assistant-ui/react";
import { Task01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useEffect, useRef } from "react";
import { toolArgText } from "./tool-arg-text";
import { ToolFallbackContent, ToolFallbackRoot, ToolFallbackTrigger } from "./tool-fallback";

function PlanIcon(props: { className?: string }) {
  return <HugeiconsIcon icon={Task01Icon} strokeWidth={1.75} {...props} />;
}

export const PlanToolUI: ToolCallMessagePartComponent<{ plan?: unknown }> = ({ args, status }) => {
  const t = useT();
  const aui = useAui();
  const plan = toolArgText(args?.plan);
  const planMode = usePlanModeStore((s) => s.planMode);
  const setPlanMode = usePlanModeStore((s) => s.setPlanMode);
  const statusType = status?.type;
  const seenStatus = useRef<string | undefined>(undefined);
  useEffect(() => {
    // Plan presented: plan mode switches itself off, so the next message builds it.
    if (planJustPresented(seenStatus.current, statusType)) setPlanMode(false);
    seenStatus.current = statusType;
  }, [statusType, setPlanMode]);
  if (!plan) return null;
  const approve = () => {
    setPlanMode(false);
    aui.composer().setText(PLAN_APPROVED_TEXT);
  };
  return (
    <ToolFallbackRoot defaultOpen>
      <ToolFallbackTrigger toolName={t("planMode.cardTitle")} status={status} icon={PlanIcon} singleLine />
      <ToolFallbackContent>
        <div className="space-y-3">
          <div className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-3 text-sm">
            {plan}
          </div>
          {status?.type === "complete" ? (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="rounded-md bg-primary px-3 py-1 text-ui-12 font-medium text-primary-foreground hover:bg-primary/90"
                onClick={approve}
              >
                {t("planMode.approve")}
              </button>
              <span className="text-ui-11 text-muted-foreground">
                {planMode ? t("planMode.approveHint") : t("planMode.approvedHint")}
              </span>
            </div>
          ) : null}
        </div>
      </ToolFallbackContent>
    </ToolFallbackRoot>
  );
};
