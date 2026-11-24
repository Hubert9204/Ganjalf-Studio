// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: the dev servers and watchers the agent left running, with their address and a stop
// button, like Claude Code's background tasks. Hidden while nothing runs.

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useT } from "@/i18n";
import { toast } from "@/lib/toast";
import { TerminalIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  type BackgroundJob,
  jobAge,
  listBackgroundJobs,
  stopBackgroundJob,
} from "../api/background-jobs-api";
import { CHAT_MENU_TRIGGER } from "./chat-header-menu";

const POLL_MS = 5000;

export function BackgroundJobsMenu() {
  const t = useT();
  const [jobs, setJobs] = useState<BackgroundJob[]>([]);
  const [open, setOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setJobs(await listBackgroundJobs());
    } catch {
      // A failed poll keeps the last list.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const running = jobs.filter((job) => job.running);
  if (running.length === 0) return null;

  const stop = async (job: BackgroundJob) => {
    try {
      await stopBackgroundJob(job.id);
      toast.success(t("backgroundJobs.stopped", { command: job.command.slice(0, 40) }));
    } catch {
      toast.error(t("backgroundJobs.stopFailed"));
    }
    void refresh();
  };

  const title = t("backgroundJobs.title", { count: running.length });
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild={true}>
        <button type="button" className={`${CHAT_MENU_TRIGGER} relative`} aria-label={title} title={title}>
          <TerminalIcon className="size-icon" strokeWidth={1.75} />
          <span className="absolute -right-0.5 -top-0.5 flex size-3.5 items-center justify-center rounded-full bg-primary text-[9px] font-semibold text-primary-foreground">
            {running.length}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={6} className="w-96 gap-1 p-2">
        <p className="px-1 pb-1 text-ui-11 text-muted-foreground">{t("backgroundJobs.hint")}</p>
        <ul className="max-h-80 space-y-1.5 overflow-y-auto">
          {running.map((job) => (
            <li key={job.id} className="rounded-md border border-border/60 p-2 text-sm">
              <div className="flex items-start justify-between gap-2">
                <code className="break-all text-ui-12">{job.command}</code>
                <button
                  type="button"
                  className="shrink-0 rounded-md px-2 py-0.5 text-ui-12 text-destructive hover:bg-destructive/10"
                  onClick={() => void stop(job)}
                >
                  {t("backgroundJobs.stop")}
                </button>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-ui-11 text-muted-foreground">
                <span>{t("backgroundJobs.runningFor", { time: jobAge(job.seconds) })}</span>
                {job.addresses.map((address) => (
                  <a
                    key={address}
                    href={address}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary underline-offset-2 hover:underline"
                  >
                    {address}
                  </a>
                ))}
              </div>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
