import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Archive, Copy, Pause, Pencil, Play, Plug, Rocket, Share2, Trash2, Workflow } from "lucide-react";
import { McpPanel } from "../components/McpPanel";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Agent, when } from "../api";
import { Icon } from "../components/Icon";
import { designApi } from "../designApi";
import { Empty, Failed, Loading } from "../components/Status";
import { useLoad } from "../components/useLoad";
import { HealthBadge } from "../components/HealthBadge";
import { Topbar } from "../components/Topbar";

export function Agents() {
  const { t, i18n } = useTranslation();
  const [mcpFor, setMcpFor] = useState<Agent | null>(null);
  const navigate = useNavigate();
  async function share(a: Agent) {
    try {
      const on = !a.shared;
      const r = await api.share(a.id, on);
      if (on) {
        const link = `${window.location.origin}${r.link}`;
        await navigator.clipboard?.writeText(link).catch(() => undefined);
        alert(t("shared.copied", { link, embed: `<iframe src="${link}?embed=1" style="width:100%;height:600px;border:0"></iframe>` }));
      }
      agents.reload();
    } catch (e) { alert((e as Error).message); }
  }
  async function duplicate(a: Agent) {
    try { const d = await designApi.duplicate(a.id); navigate(`/create/${d.id}`); } catch (e) { alert((e as Error).message); }
  }
  const agents = useLoad(api.agents);
  const [params] = useSearchParams();
  const [q, setQ] = useState(params.get("q") || "");
  const drafts = useLoad(designApi.drafts);
  useEffect(() => setQ(params.get("q") || ""), [params]);  // the top-row search lands here

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (agents.data ?? []).filter((a) => !needle || `${a.name} ${a.description}`.toLowerCase().includes(needle));
  }, [agents.data, q]);

  async function remove(a: Agent) {
    if (!window.confirm(t("agents.confirmDelete", { name: a.name }))) return;
    await api.deleteAgent(a.id);
    agents.reload();
  }

  const draftsOnly = (drafts.data ?? []).filter((d) => d.status === "draft");
  const [showRetired, setShowRetired] = useState(false);
  const [lifeErr, setLifeErr] = useState("");
  async function life(a: Agent, action: "publish" | "pause" | "resume" | "retire") {
    setLifeErr("");
    try { if (action === "publish") await api.publish(a.id); else await api.lifecycle(a.id, action); agents.reload(); }
    catch (e) { setLifeErr(`${a.name}: ${(e as Error).message}`); }
  }
  const draftFor = (id: string) => (drafts.data ?? []).find((d) => d.agent_id === id);

  return (
    <div className="page-fit">
      <Topbar title={t("agents.title")} subtitle={q ? t("agents.filtered", { q }) : t("top.sub.agents")}>
        {q && <Link className="btn ghost" to="/agents">{t("agents.clear")}</Link>}
        <label className="toggle"><input type="checkbox" checked={showRetired} onChange={(e) => setShowRetired(e.target.checked)} /> {t("life.showRetired")}</label>
        <Link className="btn primary" to="/create">{t("agents.new")}</Link>
      </Topbar>
      {lifeErr && <p className="notice err" role="alert">{lifeErr}</p>}

      {mcpFor && <McpPanel agentId={mcpFor.id} agentName={mcpFor.name} onClose={() => setMcpFor(null)} />}
      <div className="agents-layout">
        <section className="card fill">
          {agents.loading && <Loading />}
          {agents.error && <Failed message={agents.error} retry={agents.reload} />}
          {agents.data && agents.data.length === 0 && (
            <Empty title={t("agents.emptyTitle")} text={t("agents.emptyText")}>
              <Link className="btn primary" to="/create">{t("agents.new")}</Link>
            </Empty>
          )}
          {agents.data && agents.data.length > 0 && shown.length === 0 && <p className="empty">{t("agents.noMatch", { q })}</p>}
          <div className="agent-grid">
            {shown.filter((a) => showRetired || a.state !== "retired").map((a) => {
              const draft = draftFor(a.id);
              return (
                <article className="agent-card" key={a.id}>
                  <span className="chip"><Icon name="agents" /></span>
                  <div className="txt">
                    <b dir="auto">{a.name}</b>
                    <small dir="auto">{a.description || " "}</small>
                    <span className="meta">
                      {t("agents.steps", { n: a.steps })} · {when(a.updated_at, i18n.language)}
                      <span className={`badge state-${a.state ?? "built"}`}>{t(`life.state.${a.state ?? "built"}`)}{a.state === "live" && a.live_version ? ` v${a.live_version}` : ""}</span>
                      {a.state === "live" && <HealthBadge health={a.health} />}
                      {a.needs_approval && <span className="badge warn">{t("dash.withApproval")}</span>}
                      {a.shared && <span className="badge ok">{t("shared.badge")}</span>}
                      {!!a.feedback && a.feedback.good + a.feedback.bad > 0 && (
                        <span className="badge" title={t("agents.ratings", { good: a.feedback.good, bad: a.feedback.bad })}>
                          {t("agents.helpful", { pct: Math.round((100 * a.feedback.good) / (a.feedback.good + a.feedback.bad)) })}</span>)}
                      {a.last_check && a.last_check.verdict !== "unknown" && (
                        <Link className={`badge ${a.last_check.verdict === "met" ? "ok" : a.last_check.verdict === "partly" ? "warn" : "err"}`}
                          to="/executions" title={a.last_check.missing.join(" · ") || undefined}>
                          {t(`agents.lastCheck.${a.last_check.verdict}`)}</Link>)}
                      {!!a.feedback?.corrections_waiting && draft && (
                        <Link className="badge warn" to={`/create/${draft.id}`}>{t("agents.toApply", { count: a.feedback.corrections_waiting })}</Link>)}
                    </span>
                  </div>
                  <div className="agent-actions">
                    {a.state === "paused" || a.state === "retired"
                      ? <button className="btn" onClick={() => life(a, "resume")}><Play size={16} />{t("life.resume")}</button>
                      : <Link className="btn primary" to={`/agents/${a.id}/run`}>{t("agents.run")}</Link>}
                    {(a.state ?? "built") === "built" && <button className="icon-btn" title={t("life.publish")} aria-label={`${t("life.publish")} ${a.name}`} onClick={() => life(a, "publish")}><Rocket size={18} /></button>}
                    {a.state === "live" && <button className="icon-btn" title={t("life.pause")} aria-label={`${t("life.pause")} ${a.name}`} onClick={() => life(a, "pause")}><Pause size={18} /></button>}
                    {a.state !== "retired" && <button className="icon-btn" title={t("life.retire")} aria-label={`${t("life.retire")} ${a.name}`} onClick={() => life(a, "retire")}><Archive size={18} /></button>}
                    {a.state === "live" && <button className={`icon-btn${a.shared ? " on" : ""}`} title={t(a.shared ? "shared.stop" : "shared.share")} aria-pressed={!!a.shared} aria-label={`${t(a.shared ? "shared.stop" : "shared.share")} ${a.name}`} onClick={() => share(a)}><Share2 size={18} /></button>}
                    {a.state === "live" && <button className="icon-btn" title={t("mcp.title") + " (MCP)"} aria-label={`${t("mcp.title")} ${a.name}`} onClick={() => setMcpFor(a)}><Plug size={18} /></button>}
                    <button className="icon-btn" title={t("agents.copy")} aria-label={`${t("agents.copy")} ${a.name}`} onClick={() => duplicate(a)}><Copy size={18} /></button>
                    <Link className="icon-btn" to={`/agents/${a.id}/steps`} title={t("agents.steps2")} aria-label={`${t("agents.steps2")} ${a.name}`}><Workflow size={18} /></Link>
                    {draft && <Link className="icon-btn" to={`/create/${draft.id}`} title={t("agents.change")} aria-label={`${t("agents.change")} ${a.name}`}><Pencil size={18} /></Link>}
                    <button className="icon-btn danger" onClick={() => remove(a)} title={t("agents.delete")} aria-label={`${t("agents.delete")} ${a.name}`}><Trash2 size={18} /></button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
        <aside className="card fill">
          <h2>{t("agents.drafts")}</h2>
          {draftsOnly.length === 0 && <p className="help">{t("agents.noDrafts")}</p>}
          <div className="list">
            {draftsOnly.map((d) => (
              <Link className="row" key={d.id} to={`/create/${d.id}`} style={{ textDecoration: "none", color: "inherit" }}>
                <span className="txt"><b>{d.title}</b><small>{t("agents.updated", { when: when(d.updated_at, i18n.language) })}</small></span>
                <Pencil size={16} aria-hidden="true" />
              </Link>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
