import { Fragment } from "react";
import { Check, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { api, type ToolStep, when } from "../api";
import { Icon } from "../components/Icon";
import { Rich } from "../components/Rich";
import { Empty, Failed, Loading } from "../components/Status";
import { useLoad } from "../components/useLoad";
import { Topbar } from "../components/Topbar";

export function Executions() {
  const { t, i18n } = useTranslation();
  const runs = useLoad(api.executions);
  return (
    <>
      <Topbar title={<>{t("exec.title")}<small className="tech">{t("tech.executions")}</small></>} subtitle={t("top.sub.executions")} />
      <section className="card list-card">
        {runs.loading && <Loading />}
        {runs.error && <Failed message={runs.error} retry={runs.reload} />}
        {runs.data && runs.data.length === 0 && <Empty title={t("exec.emptyTitle")} text={t("exec.emptyText")} />}
        <div className="list">
          {(runs.data ?? []).map((r) => (
            <Link className="row" key={`${r.agent_id}-${r.session_id}`} to={`/executions/${encodeURIComponent(r.session_id)}`} style={{ textDecoration: "none", color: "inherit" }}>
              <span className="chip"><Icon name="run" /></span>
              <span className="txt">
                <b>{r.agent_name}</b>
                <small>{r.first_message || " "}</small>
              </span>
              <span className="meta">{when(r.started_at, i18n.language)} · {t("exec.messages")}: {r.messages}{(r.tokens_in || r.tokens_out) ? ` · ${t("exec.tokens", { n: ((r.tokens_in ?? 0) + (r.tokens_out ?? 0)).toLocaleString() })}` : ""}</span>
              <span className={`badge ${r.error ? "err" : "ok"}`}>{r.error ? t("exec.error") : t("exec.ok")}</span>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}

export function ExecutionDetail() {
  const { sessionId = "" } = useParams();
  const { t, i18n } = useTranslation();
  const msgs = useLoad(() => api.execution(sessionId), [sessionId]);
  return (
    <>
      <Topbar title={<>{t("exec.title")}<small className="tech">{t("tech.executions")}</small></>} subtitle={t("top.sub.executions")}>
        <Link className="btn ghost" to="/executions">{t("exec.back")}</Link>
        {(() => {   // run again with the same question (n8n-style replay): opens the agent's chat and asks it once more
          const first = (msgs.data ?? []).find((m) => m.sender === "User" && m.text.trim());
          return first ? <Link className="btn" to={`/agents/${first.agent_id}/run?ask=${encodeURIComponent(first.text)}`}>{t("exec.runAgain")}</Link> : null;
        })()}
      </Topbar>
      <section className="card list-card">
        {msgs.loading && <Loading />}
        {msgs.error && <Failed message={msgs.error} retry={msgs.reload} />}
        <ol className="timeline">
          {(msgs.data ?? []).map((m) => m.sender === "User" ? (
            <li key={m.id} className="tl asked"><span className="tl-dot" aria-hidden="true" />
              <div><b>{t("exec.asked")}</b><small>{when(m.timestamp, i18n.language)}</small><p dir="auto">{m.text}</p></div></li>
          ) : (
            <Fragment key={m.id}>
              {(m.tools ?? []).map((s, k) => (
                <li key={k} className={`tl step ${s.ok ? "ok" : "bad"}`}><span className="tl-dot" aria-hidden="true">{s.ok ? <Check size={12} /> : <X size={12} />}</span>
                  <div><b dir="auto">{stepTitle(s)}</b><small>{gotWhat(s, t)}</small>
                    {s.output && <details><summary>{t("exec.showData")}</summary><pre dir="auto">{s.output.slice(0, 1500)}</pre></details>}</div></li>
              ))}
              <li className={`tl answer ${m.error ? "bad" : ""}`}><span className="tl-dot" aria-hidden="true" />
                <div><b>{m.error ? t("exec.failed") : t("exec.answered")}</b><small>{when(m.timestamp, i18n.language)}</small><Rich text={m.text} /></div></li>
            </Fragment>
          ))}
        </ol>
      </section>
    </>
  );
}

/** "Read SQL Server Monitor: list findings (severity: critical)" from what the tool was called with. */
function stepTitle(s: ToolStep): string {
  const words = (x: unknown) => String(x ?? "").replace(/[_-]+/g, " ").trim();
  const inp = (s.input && typeof s.input === "object" ? s.input : {}) as Record<string, unknown>;
  const filters = inp.filters && typeof inp.filters === "object" ? Object.entries(inp.filters as Record<string, unknown>).map(([k, v]) => `${words(k)}: ${words(v)}`) : [];
  if (inp.app) return `${words(inp.app)}${inp.operation ? ": " + words(inp.operation) : ""}${inp.target ? " (" + words(inp.target) + ")" : ""}${filters.length ? " (" + filters.join(", ") + ")" : ""}`;
  if (inp.operation) {   // a tool with operations (e.g. written by AI): show what it did and with what
    const args = inp.arguments && typeof inp.arguments === "object" ? Object.values(inp.arguments as Record<string, unknown>).map((v) => String(v ?? "").trim()).filter(Boolean) : [];
    return `${words(inp.operation)}${args.length ? " (" + args.join(", ") + ")" : ""}`;
  }
  return words(s.name);
}

/** What came back, in one plain line (count of items, or size), never raw data. */
function gotWhat(s: ToolStep, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (!s.ok) return t("exec.stepFailed");
  const out = s.output ?? "";
  try {
    const d = JSON.parse(out);
    const items = Array.isArray(d) ? d.length : Array.isArray(d?.items) ? (d.total ?? d.items.length) : null;
    if (items !== null) return t("exec.gotItems", { count: items });
    if (d?.truncated) return t("exec.gotPart");
  } catch { /* plain text */ }
  return out ? t("exec.gotSize", { kb: Math.max(1, Math.round(out.length / 1024)) }) : t("exec.gotNothing");
}
