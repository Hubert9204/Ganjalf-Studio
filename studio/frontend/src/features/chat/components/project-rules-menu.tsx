// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: the "always allow" rules saved from approval cards, per project, with a way to take
// each back (like Claude Code's /permissions). Hidden while there are none.

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useT } from "@/i18n";
import { toast } from "@/lib/toast";
import { ShieldCheckIcon } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import {
  type ProjectRules,
  listAllPermissionRules,
  projectLabel,
  removePermissionRule,
} from "../api/permission-rules-api";
import { CHAT_MENU_TRIGGER } from "./chat-header-menu";

const REFRESH_MS = 30000;

export function ProjectRulesMenu() {
  const t = useT();
  const [projects, setProjects] = useState<Record<string, ProjectRules>>({});
  const [open, setOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setProjects(await listAllPermissionRules());
    } catch {
      // Keep the last list.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, REFRESH_MS);
    // A card that just saved a rule should show up without waiting for the timer.
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  const entries = Object.entries(projects).filter(
    ([, rules]) => rules.commands.length > 0 || rules.tools.length > 0,
  );
  if (entries.length === 0) return null;

  const remove = async (project: string, rule: { command_prefix?: string; tool?: string }) => {
    try {
      await removePermissionRule(project, rule);
    } catch {
      toast.error(t("permissionRules.removeFailed"));
    }
    void refresh();
  };

  const title = t("permissionRules.title");
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild={true}>
        <button type="button" className={CHAT_MENU_TRIGGER} aria-label={title} title={title}>
          <ShieldCheckIcon className="size-icon" strokeWidth={1.75} />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={6} className="w-96 gap-1 p-2">
        <p className="px-1 pb-1 text-ui-11 text-muted-foreground">{t("permissionRules.hint")}</p>
        <ul className="max-h-80 space-y-2 overflow-y-auto">
          {entries.map(([project, rules]) => (
            <li key={project} className="rounded-md border border-border/60 p-2 text-sm">
              <p className="mb-1 truncate text-ui-12 font-medium" title={project}>
                {projectLabel(project)}
              </p>
              <ul className="space-y-1">
                {rules.tools.includes("edit_file") ? (
                  <RuleRow
                    label={t("permissionRules.edits")}
                    onRemove={() => void remove(project, { tool: "edit_file" })}
                    removeLabel={t("permissionRules.remove")}
                  />
                ) : null}
                {rules.commands.map((command) => (
                  <RuleRow
                    key={command}
                    label={<code className="break-all text-ui-12">{command}</code>}
                    onRemove={() => void remove(project, { command_prefix: command })}
                    removeLabel={t("permissionRules.remove")}
                  />
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function RuleRow({
  label,
  onRemove,
  removeLabel,
}: {
  label: ReactNode;
  onRemove: () => void;
  removeLabel: string;
}) {
  return (
    <li className="flex items-start justify-between gap-2 text-ui-12">
      <span className="min-w-0">{label}</span>
      <button
        type="button"
        className="shrink-0 rounded-md px-2 py-0.5 text-ui-11 text-destructive hover:bg-destructive/10"
        onClick={onRemove}
      >
        {removeLabel}
      </button>
    </li>
  );
}
