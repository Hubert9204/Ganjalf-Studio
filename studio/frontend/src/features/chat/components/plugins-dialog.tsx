// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

// Plugins: install from GitHub, a URL, a folder, a zip or a marketplace; see what a plugin holds
// before it lands; switch plugins and their hooks on and off; update and remove them.

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { useT } from "@/i18n";
import { toast } from "@/lib/toast";
import { Delete02Icon, PlugSocketIcon, Refresh01Icon, Upload01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { type ChangeEvent, type ReactElement, useCallback, useEffect, useId, useRef, useState } from "react";
import {
  addMarketplace,
  checkPluginUpdates,
  type InstalledPlugin,
  installPlugin,
  listPlugins,
  type Marketplace,
  type PluginContents,
  pluginCommands,
  previewPlugin,
  refreshMarketplace,
  removeMarketplace,
  removePlugin,
  setPluginEnabled,
  setPluginHooks,
  updatePlugin,
  uploadPlugin,
} from "../api/plugins-api";

type Staged = { token: string; plugin: PluginContents };

function message(cause: unknown): string | undefined {
  return cause instanceof Error ? cause.message : undefined;
}

function List({ title, items }: { title: string; items: string[] }): ReactElement | null {
  if (items.length === 0) return null;
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-muted-foreground">
        {title} ({items.length})
      </div>
      <ul className="space-y-0.5 text-ui-13">
        {items.map((item) => (
          <li key={item} className="break-words">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Preview({
  staged,
  busy,
  onInstall,
  onCancel,
}: {
  staged: Staged;
  busy: boolean;
  onInstall: (enableHooks: boolean) => void;
  onCancel: () => void;
}): ReactElement {
  const t = useT();
  const hooksId = useId();
  const [enableHooks, setEnableHooks] = useState(false);
  const plugin = staged.plugin;
  const commands = pluginCommands(plugin);
  const hookCount = Object.values(plugin.hooks).reduce((sum, groups) => sum + groups.length, 0);
  return (
    <section className="space-y-3 rounded-2xl border border-border/70 p-4" aria-label={t("plugins.previewTitle")}>
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-base font-semibold">{plugin.display_name || plugin.name}</h3>
        {plugin.version ? <Badge variant="outline">{plugin.version}</Badge> : null}
        {plugin.installed ? (
          <Badge variant="secondary">{t("plugins.replaces", { version: plugin.installed_version || "?" })}</Badge>
        ) : null}
      </div>
      {plugin.author ? <p className="text-ui-12 text-muted-foreground">{t("plugins.by", { author: plugin.author })}</p> : null}
      {plugin.description ? <p className="text-ui-13">{plugin.description}</p> : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <List title={t("plugins.skills")} items={plugin.skills.map((skill) => skill.name)} />
        <List
          title={t("plugins.commands")}
          items={plugin.commands.map((command) => `/${plugin.name === command.name ? plugin.name : `${plugin.name}-${command.name.replaceAll(":", "-")}`}`)}
        />
        <List title={t("plugins.agents")} items={plugin.agents.map((agent) => `${plugin.name}:${agent.name}`)} />
        <List title={t("plugins.mcpServers")} items={Object.keys(plugin.mcp_servers)} />
      </div>
      {commands.length > 0 ? (
        <div className="space-y-1.5 rounded-xl bg-amber-500/10 p-3">
          <p className="text-ui-12 font-medium">{t("plugins.runsCommands")}</p>
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all text-ui-11">{commands.join("\n")}</pre>
        </div>
      ) : null}
      {plugin.unsupported.length > 0 ? (
        <p className="text-ui-12 text-muted-foreground">{t("plugins.unsupported", { parts: plugin.unsupported.join(", ") })}</p>
      ) : null}
      {plugin.warnings.length > 0 ? (
        <ul className="list-disc space-y-0.5 pl-5 text-ui-12 text-muted-foreground">
          {plugin.warnings.slice(0, 8).map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      {hookCount > 0 ? (
        <label htmlFor={hooksId} className="flex items-center gap-2 text-ui-13">
          <Switch id={hooksId} checked={enableHooks} onCheckedChange={setEnableHooks} />
          {t("plugins.enableHooksNow")}
        </label>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onCancel} disabled={busy}>
          {t("plugins.cancel")}
        </Button>
        <Button type="button" size="sm" onClick={() => onInstall(enableHooks)} disabled={busy}>
          {busy ? <Spinner /> : null}
          {plugin.installed ? t("plugins.update") : t("plugins.install")}
        </Button>
      </div>
    </section>
  );
}

function InstalledRow({
  plugin,
  update,
  busy,
  onToggle,
  onHooks,
  onUpdate,
  onRemove,
}: {
  plugin: InstalledPlugin;
  update: boolean;
  busy: boolean;
  onToggle: (enabled: boolean) => void;
  onHooks: (enabled: boolean) => void;
  onUpdate: () => void;
  onRemove: () => void;
}): ReactElement {
  const t = useT();
  const hooksId = useId();
  const parts = [
    plugin.skills.length ? t("plugins.countSkills", { count: plugin.skills.length }) : null,
    plugin.commands.length ? t("plugins.countCommands", { count: plugin.commands.length }) : null,
    plugin.agents.length ? t("plugins.countAgents", { count: plugin.agents.length }) : null,
    plugin.mcp_server_count ? t("plugins.countMcp", { count: plugin.mcp_server_count }) : null,
  ].filter(Boolean);
  return (
    <div className="space-y-2 rounded-xl border border-border/60 p-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-medium">{plugin.display_name || plugin.name}</span>
            {plugin.version ? <span className="text-ui-11 text-muted-foreground">{plugin.version}</span> : null}
            {plugin.marketplace ? <Badge variant="outline">{plugin.marketplace}</Badge> : null}
            {update ? <Badge variant="secondary">{t("plugins.updateAvailable")}</Badge> : null}
          </div>
          {plugin.description ? <p className="line-clamp-2 text-ui-12 text-muted-foreground">{plugin.description}</p> : null}
          {parts.length ? <p className="text-ui-11 text-muted-foreground">{parts.join(" · ")}</p> : null}
        </div>
        <Switch
          checked={plugin.enabled}
          disabled={busy}
          aria-label={t("plugins.enabled", { name: plugin.name })}
          onCheckedChange={onToggle}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {plugin.hook_events.length > 0 ? (
          <label htmlFor={hooksId} className="mr-auto flex items-center gap-2 text-ui-12">
            <Switch
              id={hooksId}
              checked={plugin.hooks_enabled}
              disabled={busy || !plugin.enabled}
              onCheckedChange={onHooks}
            />
            {t("plugins.hooks", { events: plugin.hook_events.join(", ") })}
          </label>
        ) : (
          <span className="mr-auto" />
        )}
        {plugin.source?.kind !== "local" ? (
          <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={onUpdate}>
            <HugeiconsIcon icon={Refresh01Icon} strokeWidth={2} />
            {t("plugins.update")}
          </Button>
        ) : null}
        <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={onRemove}>
          <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} />
          {t("plugins.remove")}
        </Button>
      </div>
    </div>
  );
}

export function PluginsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }): ReactElement {
  const t = useT();
  const [plugins, setPlugins] = useState<InstalledPlugin[]>([]);
  const [marketplaces, setMarketplaces] = useState<Marketplace[]>([]);
  const [updates, setUpdates] = useState<Record<string, boolean>>({});
  const [source, setSource] = useState("");
  const [staged, setStaged] = useState<Staged | null>(null);
  const [foundMarket, setFoundMarket] = useState<{ source: string; market: Marketplace } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    try {
      const data = await listPlugins();
      setPlugins(data.plugins);
      setMarketplaces(data.marketplaces);
    } catch (cause) {
      toast.error(t("plugins.loadError"), { description: message(cause) });
    }
  }, [t]);

  useEffect(() => {
    if (!open) return;
    // Loads from the server; the state lands after the request, not during the effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload();
    void checkPluginUpdates()
      .then(setUpdates)
      .catch(() => undefined);
  }, [open, reload]);

  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key);
    try {
      await action();
    } catch (cause) {
      toast.error(t("plugins.error"), { description: message(cause) });
    } finally {
      setBusy(null);
    }
  };

  const preview = (text: string) =>
    run("preview", async () => {
      const result = await previewPlugin(text);
      if (result.kind === "plugin") {
        setFoundMarket(null);
        setStaged({ token: result.token, plugin: result.plugin });
      } else {
        setStaged(null);
        setFoundMarket({ source: text, market: result.marketplace });
      }
    });

  const upload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    void run("preview", async () => {
      const result = await uploadPlugin(file);
      if (result.kind === "plugin") setStaged({ token: result.token, plugin: result.plugin });
    });
  };

  const install = (enableHooks: boolean) =>
    staged &&
    run("install", async () => {
      const installed = await installPlugin(staged.token, enableHooks);
      setStaged(null);
      setSource("");
      toast.success(t("plugins.installed", { name: installed.name }));
      if (installed.warnings.length) toast.warning(installed.warnings.slice(0, 3).join("\n"));
      await reload();
    });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-3xl shadow-border ring-0 sm:max-w-2xl">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <HugeiconsIcon icon={PlugSocketIcon} strokeWidth={1.75} className="size-5 text-primary" />
            <DialogTitle>{t("plugins.title")}</DialogTitle>
          </div>
          <DialogDescription>{t("plugins.description")}</DialogDescription>
        </DialogHeader>
        <div className="hover-scrollbar -mr-7 max-h-[min(66dvh,620px)] space-y-5 overflow-y-auto pr-7">
          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (source.trim()) void preview(source.trim());
            }}
          >
            <Input
              value={source}
              onChange={(event) => setSource(event.target.value)}
              placeholder={t("plugins.sourcePlaceholder")}
              aria-label={t("plugins.sourcePlaceholder")}
              className="min-w-0 flex-1"
            />
            <Button type="submit" size="sm" disabled={!source.trim() || busy !== null}>
              {busy === "preview" ? <Spinner /> : null}
              {t("plugins.preview")}
            </Button>
            <input ref={fileRef} type="file" accept=".zip,.tar,.tgz,.gz" className="hidden" onChange={upload} />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy !== null}
              aria-label={t("plugins.upload")}
              title={t("plugins.upload")}
              onClick={() => fileRef.current?.click()}
            >
              <HugeiconsIcon icon={Upload01Icon} strokeWidth={2} />
            </Button>
          </form>

          {staged ? <Preview staged={staged} busy={busy === "install"} onInstall={install} onCancel={() => setStaged(null)} /> : null}

          {foundMarket ? (
            <section className="space-y-2 rounded-2xl border border-border/70 p-4">
              <p className="text-ui-13">{t("plugins.isMarketplace", { name: foundMarket.market.name, count: foundMarket.market.plugins.length })}</p>
              <div className="flex justify-end gap-2">
                <Button type="button" size="sm" variant="outline" onClick={() => setFoundMarket(null)}>
                  {t("plugins.cancel")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  disabled={busy !== null}
                  onClick={() =>
                    void run("market", async () => {
                      await addMarketplace(foundMarket.source);
                      setFoundMarket(null);
                      setSource("");
                      await reload();
                    })
                  }
                >
                  {busy === "market" ? <Spinner /> : null}
                  {t("plugins.addMarketplace")}
                </Button>
              </div>
            </section>
          ) : null}

          <section className="space-y-2">
            <h3 className="px-1 text-xs font-medium text-muted-foreground">{t("plugins.installedTitle")}</h3>
            {plugins.length === 0 ? (
              <p className="px-1 text-ui-13 text-muted-foreground">{t("plugins.none")}</p>
            ) : (
              plugins.map((plugin) => (
                <InstalledRow
                  key={plugin.name}
                  plugin={plugin}
                  update={Boolean(updates[plugin.name])}
                  busy={busy !== null}
                  onToggle={(enabled) => void run(plugin.name, async () => { await setPluginEnabled(plugin.name, enabled); await reload(); })}
                  onHooks={(enabled) => void run(plugin.name, async () => { await setPluginHooks(plugin.name, enabled); await reload(); })}
                  onUpdate={() =>
                    void run(plugin.name, async () => {
                      await updatePlugin(plugin.name);
                      toast.success(t("plugins.updated", { name: plugin.name }));
                      setUpdates((current) => ({ ...current, [plugin.name]: false }));
                      await reload();
                    })
                  }
                  onRemove={() => void run(plugin.name, async () => { await removePlugin(plugin.name); await reload(); })}
                />
              ))
            )}
          </section>

          {marketplaces.map((market) => (
            <section key={market.name} className="space-y-2">
              <div className="flex items-center gap-2 px-1">
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t("plugins.marketplace", { name: market.name })}
                </h3>
                <span className="mr-auto truncate text-ui-11 text-muted-foreground/70">{market.owner}</span>
                <Button
                  type="button"
                  size="icon-xs"
                  variant="ghost"
                  aria-label={t("plugins.refresh")}
                  title={t("plugins.refresh")}
                  disabled={busy !== null}
                  onClick={() => void run(market.name, async () => { await refreshMarketplace(market.name); await reload(); })}
                >
                  <HugeiconsIcon icon={Refresh01Icon} strokeWidth={2} />
                </Button>
                <Button
                  type="button"
                  size="icon-xs"
                  variant="ghost"
                  aria-label={t("plugins.removeMarketplace")}
                  title={t("plugins.removeMarketplace")}
                  disabled={busy !== null}
                  onClick={() => void run(market.name, async () => { await removeMarketplace(market.name); await reload(); })}
                >
                  <HugeiconsIcon icon={Delete02Icon} strokeWidth={2} />
                </Button>
              </div>
              {market.plugins.map((item) => (
                <div key={item.name} className="flex items-center gap-3 rounded-xl border border-border/50 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <span className="text-ui-13 font-medium">{item.name}</span>
                    {item.description ? <p className="line-clamp-2 text-ui-12 text-muted-foreground">{item.description}</p> : null}
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant={item.installed ? "ghost" : "outline"}
                    disabled={busy !== null}
                    onClick={() => void preview(`${item.name}@${market.name}`)}
                  >
                    {item.installed ? t("plugins.reinstall") : t("plugins.install")}
                  </Button>
                </div>
              ))}
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
