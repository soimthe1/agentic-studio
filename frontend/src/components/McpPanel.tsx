import { Copy, KeyRound, Plug, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api";

type Connect = { enabled: boolean; tool: string; url: string; settings: { json: unknown; curl: string } };
type Key = { id: string; name: string; created_at: string; last_used_at: string | null };

function CopyBox({ text, label }: { text: string; label: string }) {
  const { t } = useTranslation();
  const [done, setDone] = useState(false);
  return (
    <div className="copybox">
      <pre dir="ltr">{text}</pre>
      <button type="button" className="btn" onClick={() => { void navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}
        aria-label={`${t("mcp.copy")} ${label}`}><Copy size={14} /> {done ? t("mcp.copied") : t("mcp.copy")}</button>
    </div>
  );
}

/** Use an agent from other tools (MCP): address, a personal access key, ready settings. Plain words first. */
export function McpPanel({ agentId, agentName, onClose }: { agentId: string; agentName: string; onClose: () => void }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);
  const [info, setInfo] = useState<Connect | null>(null);
  const [keys, setKeys] = useState<Key[]>([]);
  const [fresh, setFresh] = useState<string | null>(null);
  const [error, setError] = useState("");

  const loadKeys = () => api.mcpKeys().then(setKeys).catch(() => setKeys([]));
  useEffect(() => {
    ref.current?.showModal();
    api.mcpConnect(agentId).then(setInfo).catch((e: Error) => setError(e.message));
    void loadKeys();
  }, [agentId]);

  const settings = info ? JSON.stringify(info.settings.json, null, 2).replace("<your access key>", fresh ?? "<your access key>") : "";
  const curl = info ? info.settings.curl.replace("<your access key>", fresh ?? "<your access key>") : "";

  return (
    <dialog ref={ref} className="mcp-panel" onClose={onClose} aria-labelledby="mcp-title">
      <header>
        <span className="tile aqua"><Plug size={18} /></span>
        <div><h2 id="mcp-title">{t("mcp.title")}<small className="tech">MCP</small></h2><p className="help">{t("mcp.lead", { name: agentName })}</p></div>
        <button type="button" className="icon-btn" onClick={() => ref.current?.close()} aria-label={t("mcp.close")}><X size={18} /></button>
      </header>
      {error && <p className="notice err">{error}</p>}
      {info && !info.enabled && <p className="notice warn">{t("mcp.notLive")}</p>}
      {info && info.enabled && (
        <ol className="mcp-steps">
          <li><b>{t("mcp.step1")}</b><CopyBox text={info.url} label={t("mcp.step1")} /></li>
          <li><b>{t("mcp.step2")}</b><small className="help">{t("mcp.step2Hint")}</small>
            {fresh ? <><p className="notice warn">{t("mcp.onceOnly")}</p><CopyBox text={fresh} label={t("mcp.step2")} /></>
              : <button type="button" className="btn primary" onClick={() => api.mcpCreateKey(agentName).then((k) => { setFresh(k.key); void loadKeys(); }).catch((e: Error) => setError(e.message))}>
                  <KeyRound size={16} /> {t("mcp.createKey")}</button>}
          </li>
          <li><b>{t("mcp.step3")}</b><small className="help">{t("mcp.step3Hint")}</small><CopyBox text={settings} label={t("mcp.step3")} /></li>
          <li><b>{t("mcp.step4")}</b><small className="help">{t("mcp.step4Hint")}</small><CopyBox text={curl} label={t("mcp.step4")} /></li>
        </ol>
      )}
      {keys.length > 0 && (
        <section className="mcp-keys">
          <h3>{t("mcp.myKeys")}<small className="tech">API keys</small></h3>
          {keys.map((k) => (
            <div key={k.id} className="row">
              <span className="txt"><b>{k.name}</b><small>{k.last_used_at ? t("mcp.lastUsed", { when: k.last_used_at.slice(0, 16).replace("T", " ") }) : t("mcp.neverUsed")}</small></span>
              <button type="button" className="btn ghost" onClick={() => api.mcpRevoke(k.id).then(loadKeys)}><Trash2 size={14} /> {t("mcp.revoke")}</button>
            </div>
          ))}
        </section>
      )}
    </dialog>
  );
}
