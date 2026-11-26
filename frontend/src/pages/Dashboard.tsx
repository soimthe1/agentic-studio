import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api, when } from "../api";
import { Icon, type IconName } from "../components/Icon";
import { Empty, Failed, Loading } from "../components/Status";
import { HealthBadge } from "../components/HealthBadge";
import { Topbar } from "../components/Topbar";
import { useLoad } from "../components/useLoad";
import { logoUrl } from "../brand";
import { useMe } from "../App";

type Tone = "cyan" | "aqua" | "lime";

function Stat({ label, value, icon, tone, to, hint }: { label: string; value: string | number; icon: IconName; tone: Tone; to?: string; hint?: string }) {
  const body = (
    <>
      <div className="stat-top">
        <span className="label">{label}</span>
        <span className={`tile ${tone}`}><Icon name={icon} /></span>
      </div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </>
  );
  return to ? <Link to={to} className="card stat link">{body}</Link> : <div className="card stat">{body}</div>;
}

/** Runs per day as a smooth line; the last point is today. */
function Trend({ points }: { points: number[] }) {
  const max = Math.max(1, ...points);
  const w = 600, h = 120, step = w / (points.length - 1);
  const xy = points.map((p, i) => [i * step, h - 8 - (p / max) * (h - 24)] as const);
  const d = xy.map(([x, y], i) => {
    if (i === 0) return `M${x},${y}`;
    const [px, py] = xy[i - 1];
    const cx = (px + x) / 2;
    return `C${cx},${py} ${cx},${y} ${x},${y}`;
  }).join(" ");
  return (
    <svg className="trend" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label={points.join(", ")}>
      <defs>
        <linearGradient id="trendFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="var(--tw-electric-cyan)" stopOpacity=".28" />
          <stop offset="1" stopColor="var(--tw-electric-cyan)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${d} L${w},${h} L0,${h} Z`} fill="url(#trendFill)" />
      <path d={d} fill="none" stroke="var(--tw-electric-cyan)" strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      <circle cx={xy[xy.length - 1][0]} cy={xy[xy.length - 1][1]} r="5" fill="var(--tw-neon-lime)" />
    </svg>
  );
}

export function Dashboard() {
  const { t, i18n } = useTranslation();
  const d = useLoad(api.dashboard);
  const me = useMe();

  return (
    <div className="page-fit dash">
      <Topbar title={t("dash.welcome")} subtitle={t("top.sub.dashboard")} />
      {me?.needs_setup && <div className="notice warn"><p>{t("setup.needed")} <Link to="/settings">{t("setup.go")}</Link></p></div>}

      <section className="card hero">
        <h2>{t("dash.heroTitle")}</h2>
        <p>{t("dash.heroText")}</p>
        <p className="tags">{t("dash.heroTags")}</p>
        <img className="hero-mark" src={logoUrl()} alt="" aria-hidden="true" />
      </section>

      {d.loading && <Loading />}
      {d.error && <Failed message={d.error} retry={d.reload} />}
      {d.data && (
        <div className="dash-body">
          <section className="grid cols-4 section" aria-label={t("dash.summary")}>
            <Stat label={t("dash.agents")} value={d.data.agents} icon="agents" tone="cyan" to="/agents"
              hint={d.data.needs_attention ? t("dash.attention", { count: d.data.needs_attention }) : t("dash.allWell")} />
            <Stat label={t("dash.runs7d")} value={d.data.runs_7d} icon="run" tone="aqua" to="/executions" />
            <Stat label={t("dash.approvals")} value={d.data.approvals_waiting} icon="approvals" tone="lime" to="/approvals"
              hint={d.data.approvals_waiting ? t("dash.needsYou") : t("dash.nothingWaiting")} />
            <Stat label={t("dash.success7d")} value={d.data.success_rate_7d === null ? "—" : `${d.data.success_rate_7d}%`} icon="trace" tone="cyan"
              hint={d.data.success_rate_7d === null ? t("dash.noRuns") : d.data.failed_7d ? t("dash.failed", { n: d.data.failed_7d }) : undefined} />
          </section>

          <section className="grid dash-split section">
            <div className="card">
              <div className="card-head">
                <h2>{t("dash.yourAgents")}</h2>
                <Link to="/agents">{t("dash.viewAll")}</Link>
              </div>
              {d.data.recent_agents.length === 0 ? (
                <Empty title={t("dash.noAgentsTitle")} text={t("dash.noAgentsText")}>
                  <Link className="btn primary" to="/create">{t("agents.new")}</Link>
                </Empty>
              ) : (
                <div className="list">
                  {d.data.recent_agents.slice(0, 6).map((a) => (
                    <div className="row" key={a.id}>
                      <span className="chip"><Icon name="agents" /></span>
                      <span className="txt">
                        <b dir="auto">{a.name}</b>
                        <small dir="auto">{a.description || t("agents.updated", { when: when(a.updated_at, i18n.language) })}</small>
                      </span>
                      <HealthBadge health={a.health} />
                      <Link className="icon-btn" to={`/agents/${a.id}/run`} aria-label={`${t("agents.run")} ${a.name}`}>
                        <Icon name="run" />
                      </Link>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="card">
              <div className="card-head"><h2>{t("dash.activity")}</h2><span className="help">{t("dash.last14")}</span></div>
              <Trend points={d.data.runs_by_day} />
            </div>
          </section>
        </div>
      )}

      <Usage />
    </div>
  );
}

/** AI use per agent over 7 days: runs and model tokens (what each agent costs the model servers). */
function Usage() {
  const { t } = useTranslation();
  const u = useLoad(() => api.usage(7));
  if (!u.data) return null;
  const top = u.data.agents.slice(0, 5);
  const max = Math.max(1, ...top.map((a) => a.tokens_in + a.tokens_out));
  return (
    <section className="card usage">
      <div className="card-head">
        <h2>{t("usage.title")}</h2>
        <span className="help">{t("usage.total", { runs: u.data.runs, tokens: u.data.tokens.toLocaleString() })}</span>
        <Link to="/capabilities">{t("usage.allFeatures")}</Link>
      </div>
      {top.length === 0 ? <p className="help">{t("dash.noRuns")}</p> : (
        <div className="usage-rows">
          {top.map((a) => (
            <div className="usage-row" key={a.agent_id}>
              <span className="u-name" dir="auto">{a.agent_name}</span>
              <span className="u-bar" aria-hidden="true"><i style={{ width: `${(100 * (a.tokens_in + a.tokens_out)) / max}%` }} /></span>
              <span className="u-num">{t("usage.row", { runs: a.runs, tokens: (a.tokens_in + a.tokens_out).toLocaleString() })}{a.failed ? ` · ${t("dash.failed", { n: a.failed })}` : ""}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
