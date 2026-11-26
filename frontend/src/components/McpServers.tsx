import { Plug, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api";
import { useLoad } from "./useLoad";

type Tool = { name: string; description: string };

/** MCP servers the agents can use: check one (lists its tools), connect it (administrators), disconnect it. */
export function McpServers({ canConnect, open, onClose }: { canConnect: boolean; open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const list = useLoad(api.mcpServers);
  const [form, setForm] = useState({ name: "", url: "", purpose: "", key_header: "x-api-key", key_env: "", key: "", changes: false });
  const [tools, setTools] = useState<Tool[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const set = (k: keyof typeof form, v: string | boolean) => { setForm((f) => ({ ...f, [k]: v })); setTools(null); };

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setMsg("");
    try { await fn(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <>
      {open && (
        <section className="card inner connect" style={{ marginBottom: 24 }}>
          <h2>{t("mcps.title")}<small className="tech">MCP</small></h2>
          <p className="help">{t("mcps.lead")}</p>
          <div className="skill-edit mcp-form">
            <label>{t("mcps.name")}<input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} /></label>
            <label>{t("mcps.url")}<input className="input" dir="ltr" placeholder="https://server/mcp" value={form.url} onChange={(e) => set("url", e.target.value)} /></label>
            <label>{t("mcps.purpose")}<input className="input" value={form.purpose} onChange={(e) => set("purpose", e.target.value)} /></label>
            <label>{t("mcps.keyHeader")}<input className="input" dir="ltr" value={form.key_header} onChange={(e) => set("key_header", e.target.value)} /></label>
            <label>{t("mcps.keyEnv")}<input className="input" dir="ltr" placeholder="MCP_SALES_KEY" value={form.key_env} onChange={(e) => set("key_env", e.target.value)} />
              <small className="help">{t("mcps.keyEnvHint")}</small></label>
            <label>{t("mcps.keyOnce")}<input className="input" type="password" value={form.key} onChange={(e) => set("key", e.target.value)} autoComplete="off" />
              <small className="help">{t("mcps.keyOnceHint")}</small></label>
            <label className="toggle"><input type="checkbox" checked={form.changes} onChange={(e) => set("changes", e.target.checked)} /> {t("mcps.changes")}</label>
          </div>
          <div className="actions start">
            <button className="btn" disabled={busy || form.url.length < 8 || form.name.length < 2}
              onClick={() => run(async () => setTools((await api.mcpCheck(form)).tools))}>{busy && !tools ? t("mcps.checking") : t("mcps.check")}</button>
            {canConnect && tools && (
              <button className="btn primary" disabled={busy} onClick={() => run(async () => { await api.mcpConnectServer({ ...form, key: "" }); onClose(); list.reload(); })}>
                <Plug size={16} /> {t("mcps.connect")}</button>
            )}
            <button className="btn ghost" onClick={onClose}>{t("mcps.cancel")}</button>
          </div>
          {tools && (
            <div className="list">
              <p className="help">{t("mcps.found", { count: tools.length })}{!canConnect && ` ${t("mcps.askAdmin")}`}</p>
              {tools.map((x) => <div key={x.name} className="row"><span className="txt"><b dir="ltr">{x.name}</b><small dir="auto">{x.description}</small></span></div>)}
            </div>
          )}
          {msg && <p className="notice err" role="alert">{msg}</p>}
        </section>
      )}
      {(list.data?.length ?? 0) > 0 && (
        <section className="card" style={{ marginBottom: 24 }}>
          <h2>{t("mcps.connected")}<small className="tech">MCP servers</small></h2>
          <div className="list">
            {list.data!.map((s) => (
              <div className="row" key={s.id}>
                <span className="chip"><Plug size={18} /></span>
                <span className="txt"><b>{s.name}</b><small dir="ltr">{s.url}</small>
                  <small>{t("mcps.tools", { count: s.tools.length })}: {s.tools.map((x) => x.name).join(", ")}{s.changes ? ` · ${t("mcps.changesShort")}` : ""}</small></span>
                {canConnect && <button className="btn ghost" onClick={() => run(async () => { await api.mcpDisconnect(s.id); list.reload(); })}><Trash2 size={14} /> {t("mcps.disconnect")}</button>}
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
