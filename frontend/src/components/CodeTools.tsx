import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type ToolRequest } from "../api";
import { useLoad } from "./useLoad";

export type CodeSpec = {
  kind: "code"; code: string; need: string; missing?: { module: string; package: string }[]; bring?: string;
  inspect: { level: "low" | "medium" | "high"; hosts: string[]; secrets: string[];
    methods: { name: string; args: string[]; required: string[]; doc: string; change: boolean }[];
    risks: { kind: string; level: string; text: string; line: number; method?: string }[] };
};

/** A tool written by AI, under review: what it does, every risk in plain words, its code, the values it needs,
 *  missing libraries (how to bring them), and trying one operation for real in the engine. */
export function CodeReview({ r, onChange }: { r: ToolRequest; onChange: () => void }) {
  const { t } = useTranslation();
  const spec = r.spec as unknown as CodeSpec;
  const info = spec.inspect;
  const [open, setOpen] = useState(r.status === "draft");
  const [method, setMethod] = useState(info.methods.find((m) => !m.change)?.name ?? info.methods[0]?.name ?? "");
  const [args, setArgs] = useState("{}");
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [vals, setVals] = useState<Record<string, string>>({});

  async function tryIt() {
    setBusy(true); setOut("");
    try {
      const res = await api.codeTry(r.id, method, JSON.parse(args || "{}"));
      setOut(res.results.map((x) => `${x.ok ? "✓" : "✗"} ${x.summary}: ${x.detail}`).join("\n")); onChange();
    } catch (e) { setOut((e as Error).message); } finally { setBusy(false); }
  }
  async function save(name: string) {
    try { await api.codeSecret(r.tool_id, name, vals[name] || ""); setVals({ ...vals, [name]: "" }); setOut(t("code.saved", { name })); }
    catch (e) { setOut((e as Error).message); }
  }

  return (
    <div className="code-review">
      <div className="cr-head">
        <span className={`badge risk-${info.level}`}>{t(`code.risk.${info.level}`)}</span>
        <span className="help">{t("code.ops", { count: info.methods.length })}{info.hosts.length ? ` · ${t("code.talksTo", { hosts: info.hosts.join(", ") })}` : ""}</span>
        <button className="btn ghost" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? t("code.hide") : t("code.review")}</button>
      </div>
      {open && (
        <div className="cr-body">
          {info.risks.length > 0 && (
            <ul className="cr-risks">
              {info.risks.map((x, i) => <li key={i} className={`risk-${x.level}`}><b>{t(`code.risk.${x.level}`)}</b> {x.text}{x.method ? ` (${x.method})` : ""} · {t("code.line", { n: x.line })}</li>)}
            </ul>
          )}
          <ul className="cr-ops">
            {info.methods.map((m) => <li key={m.name}><code>{m.name}({m.args.join(", ")})</code> {m.doc} {m.change && <span className="badge warn">{t("code.asksApproval")}</span>}</li>)}
          </ul>
          {!!spec.missing?.length && <pre className="cr-bring">{spec.bring}</pre>}
          {info.secrets.map((n) => (
            <form key={n} className="cr-secret" onSubmit={(e) => { e.preventDefault(); void save(n); }}>
              <label>{n}<input className="input" type="password" autoComplete="new-password" value={vals[n] || ""} onChange={(e) => setVals({ ...vals, [n]: e.target.value })} /></label>
              <button className="btn" type="submit" disabled={!vals[n]}>{t("code.saveValue")}</button>
            </form>
          ))}
          <details><summary>{t("code.showCode")}</summary><pre className="cr-code" dir="ltr">{spec.code}</pre></details>
          <div className="cr-try">
            <select className="input" value={method} onChange={(e) => setMethod(e.target.value)} aria-label={t("code.operation")}>
              {info.methods.map((m) => <option key={m.name} value={m.name}>{m.name}{m.change ? ` (${t("code.asksApproval")})` : ""}</option>)}
            </select>
            <input className="input" dir="ltr" value={args} onChange={(e) => setArgs(e.target.value)} aria-label={t("code.args")} placeholder='{"limit": 5}' />
            <button className="btn" disabled={busy} onClick={tryIt}>{busy ? t("tools.testing") : t("code.tryIt")}</button>
          </div>
          {out && <pre className="cr-out" role="status">{out}</pre>}
        </div>
      )}
    </div>
  );
}

/** Libraries tools written by AI can use: bundled with the app, brought by people (air-gapped), and how to bring more. */
export function Libraries({ canInstall }: { canInstall: boolean }) {
  const { t } = useTranslation();
  const k = useLoad(api.toolkit);
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState("");
  async function install() {
    setBusy(true); setOut("");
    try { const r = await api.toolkitInstall(""); setOut(r.output); k.reload(); } catch (e) { setOut((e as Error).message); } finally { setBusy(false); }
  }
  if (!k.data) return null;
  return (
    <section className="card libraries">
      <div className="card-head"><h2>{t("libs.title")}</h2><span className="help">{t("libs.sub", { python: k.data.python, os: k.data.os })}</span></div>
      <p className="libs-line"><b>{t("libs.bundled")}</b> {Object.keys(k.data.packages).join(", ")}</p>
      {k.data.added.length > 0 && <p className="libs-line"><b>{t("libs.added")}</b> {k.data.added.join(", ")}</p>}
      {k.data.wheels.length > 0 && (
        <p className="libs-line"><b>{t("libs.waiting")}</b> {t("libs.files", { count: k.data.wheels.length })}
          {canInstall && <button className="btn primary" disabled={busy} onClick={install}>{busy ? t("libs.installing") : t("libs.install")}</button>}</p>
      )}
      <details><summary>{t("libs.howTo")}</summary><pre className="cr-bring">{t("libs.steps", { folder: k.data.toolkit })}</pre></details>
      {out && <pre className="cr-out">{out}</pre>}
    </section>
  );
}
