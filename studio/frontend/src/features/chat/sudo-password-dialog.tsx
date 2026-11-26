// SPDX-License-Identifier: AGPL-3.0-only
// Ganjalf: the box where the user types the sudo password for an agent command.
"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { authFetch } from "@/features/auth";
import { useT } from "@/i18n";
import { type SudoPrompt, useSudoPromptStore } from "./sudo-prompt-store";

async function answer(id: string, sessionId: string, password: string | null): Promise<void> {
  try {
    await authFetch("/api/inference/sudo-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt_id: id, session_id: sessionId, password }),
    });
  } catch {
    // The tool stops waiting on its own; nothing to retry.
  }
}

export function SudoPasswordDialog() {
  const prompt = useSudoPromptStore((s) => s.prompt);
  // Keyed by request: a new request (or a retry after a wrong password) starts empty.
  return prompt ? <SudoPasswordBox key={prompt.id} prompt={prompt} /> : null;
}

function SudoPasswordBox({ prompt }: { prompt: SudoPrompt }) {
  const close = useSudoPromptStore((s) => s.close);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const t = useT();

  useEffect(() => {
    // The backend gives up at expires_at; the box must not outlive it.
    const timer = setTimeout(() => close(prompt.id), Math.max(0, prompt.expiresAt - Date.now()));
    return () => clearTimeout(timer);
  }, [prompt, close]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    const typed = password;
    setPassword("");
    await answer(prompt.id, prompt.sessionId, typed);
    close(prompt.id);
  };
  const dismiss = () => {
    void answer(prompt.id, prompt.sessionId, null);
    close(prompt.id);
  };

  return (
    <Dialog open onOpenChange={(open) => (open ? undefined : dismiss())}>
      <DialogContent
        className="sm:max-w-md"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          inputRef.current?.focus();
        }}
      >
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{t("sudoPrompt.title")}</DialogTitle>
            <DialogDescription>{t("sudoPrompt.description")}</DialogDescription>
          </DialogHeader>
          {prompt.command ? (
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted px-3 py-2 font-mono text-xs">
              {prompt.command}
            </pre>
          ) : null}
          <div className="flex flex-col gap-1.5">
            <label htmlFor="ganjalf-sudo-password" className="text-sm font-medium">
              {t("sudoPrompt.label")}
            </label>
            <Input
              id="ganjalf-sudo-password"
              ref={inputRef}
              type="password"
              autoComplete="off"
              value={password}
              disabled={busy}
              onChange={(event) => setPassword(event.target.value)}
            />
            {prompt.wrong > 0 ? (
              <p className="text-sm text-destructive">{t("sudoPrompt.wrong")}</p>
            ) : null}
            <p className="text-xs text-muted-foreground">{t("sudoPrompt.remembered")}</p>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={dismiss} disabled={busy}>
              {t("sudoPrompt.cancel")}
            </Button>
            <Button type="submit" disabled={!password || busy}>
              {t("sudoPrompt.run")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
