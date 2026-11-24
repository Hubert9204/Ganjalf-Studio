// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: the agent's task list (todo_write), shown as a checklist like Claude Code's.
import { type ToolCallMessagePartComponent } from "@assistant-ui/react";
import {
  CheckmarkCircle02Icon,
  CircleIcon,
  Loading03Icon,
  TaskDone01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useT } from "@/i18n";
import {
  ToolFallbackContent,
  ToolFallbackRoot,
  ToolFallbackTrigger,
} from "./tool-fallback";
import { todoItems, todoSummary } from "./todo-items";

function TaskListIcon(props: { className?: string }) {
  return <HugeiconsIcon icon={TaskDone01Icon} strokeWidth={1.75} {...props} />;
}

export const TodoToolUI: ToolCallMessagePartComponent<{ todos?: unknown }> = ({ args, status }) => {
  const t = useT();
  const items = todoItems(args?.todos);
  if (items.length === 0) return null;
  // Open by default: the plan is the point of the card.
  return (
    <ToolFallbackRoot defaultOpen>
      <ToolFallbackTrigger
        toolName={t("agentTools.tasks")}
        status={status}
        icon={TaskListIcon}
        detail={todoSummary(items)}
        singleLine
      />
      <ToolFallbackContent>
        <ul className="space-y-1.5 text-sm" aria-label={t("agentTools.tasks")}>
          {items.map((item, index) => {
            const done = item.status === "completed";
            const active = item.status === "in_progress";
            return (
              <li key={`${index}-${item.content}`} className="flex items-start gap-2">
                <HugeiconsIcon
                  icon={done ? CheckmarkCircle02Icon : active ? Loading03Icon : CircleIcon}
                  strokeWidth={1.75}
                  className={
                    done
                      ? "mt-0.5 size-4 shrink-0 text-primary"
                      : active
                        ? "mt-0.5 size-4 shrink-0 animate-spin text-foreground"
                        : "mt-0.5 size-4 shrink-0 text-muted-foreground"
                  }
                />
                <span
                  className={
                    done
                      ? "text-muted-foreground line-through"
                      : active
                        ? "font-medium"
                        : ""
                  }
                >
                  {active && item.activeForm ? item.activeForm : item.content}
                </span>
              </li>
            );
          })}
        </ul>
      </ToolFallbackContent>
    </ToolFallbackRoot>
  );
};
