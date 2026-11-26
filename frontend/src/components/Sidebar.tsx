import { LayoutDashboard, PanelLeftClose, PanelLeftOpen, Plus, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";
import { api, type Agent, type Me } from "../api";
import { logoUrl } from "../brand";
import { Icon, type IconName } from "./Icon";

type Item = { to: string; key: string; icon: IconName | "dashboard"; badge?: number };

/** Grouped navigation (house pattern): one Create button, then Work, Build, Recent agents, System. Builder-only
 *  entries are not shown to people who cannot use them (the API refuses them anyway). */
export function Sidebar({ me }: { me: Me }) {
  const { t, i18n } = useTranslation();
  const builder = me.role === "builder" || me.role === "admin";
  const [rail, setRail] = useState(() => { try { return localStorage.getItem("agent_studio.rail") === "1"; } catch { return false; } });
  const [waiting, setWaiting] = useState(0);
  const [recent, setRecent] = useState<Agent[]>([]);

  useEffect(() => {
    const load = () => {
      api.approvals().then((a) => setWaiting(a.length)).catch(() => undefined);
      api.agents().then((a) => setRecent([...a].filter((x) => x.state !== "retired")
        .sort((x, y) => (y.updated_at || "").localeCompare(x.updated_at || "")).slice(0, 4))).catch(() => undefined);
    };
    load();
    const id = window.setInterval(load, 60000);   // once a minute and when the tab comes back, not on every page
    window.addEventListener("focus", load);
    return () => { window.clearInterval(id); window.removeEventListener("focus", load); };
  }, []);

  function toggle() {
    setRail((r) => { try { localStorage.setItem("agent_studio.rail", r ? "0" : "1"); } catch { /* not remembered */ } return !r; });
  }

  const link = (n: Item) => (
    <NavLink key={n.to} to={n.to} end={n.to === "/"} title={rail ? t(`nav.${n.key}`) : undefined}>
      {n.icon === "dashboard" ? <span className="ico" aria-hidden="true"><LayoutDashboard size={20} strokeWidth={1.6} /></span> : <Icon name={n.icon} />}
      <span className="nav-label">{t(`nav.${n.key}`)}{i18n.exists(`navTech.${n.key}`) && <small className="tech">{t(`navTech.${n.key}`)}</small>}</span>
      {!!n.badge && <span className="nav-badge" aria-label={t("nav.waitingCount", { count: n.badge })}>{n.badge}</span>}
    </NavLink>
  );

  return (
    <aside className={`sidebar ${rail ? "rail" : ""}`}>
      <NavLink to="/" className="brand" aria-label={t("brand")}>
        <img src={logoUrl()} alt="" />
        <span><b>{t("brand")}</b><small>{t("tagline")}</small></span>
      </NavLink>
      {builder && (
        <NavLink to="/create" className="side-create" title={rail ? t("nav.createAgent") : undefined}>
          <Plus aria-hidden="true" /><span className="nav-label">{t("nav.createAgent")}</span>
        </NavLink>
      )}
      <nav className="nav" aria-label={t("nav.main")}>
        <div className="side-group">
          {link({ to: "/", key: "dashboard", icon: "dashboard" })}
          {link({ to: "/capabilities", key: "capabilities", icon: "catalog" })}
        </div>
        <div className="side-group">
          <div className="side-heading">{t("nav.work")}</div>
          {link({ to: "/agents", key: "agents", icon: "agents" })}
          {link({ to: "/shared", key: "shared", icon: "agents" })}
          {link({ to: "/approvals", key: "approvals", icon: "approvals", badge: waiting })}
          {link({ to: "/executions", key: "executions", icon: "run" })}
          {link({ to: "/files", key: "files", icon: "database" })}
        </div>
        {builder && (
          <div className="side-group">
            <div className="side-heading">{t("nav.build")}</div>
            {link({ to: "/tools", key: "tools", icon: "tools" })}
            {link({ to: "/skills", key: "skills", icon: "catalog" })}
          </div>
        )}
        {recent.length > 0 && (
          <div className="side-group side-recents">
            <div className="side-heading">{t("nav.recent")}</div>
            {recent.map((a) => (
              <NavLink key={a.id} to={`/agents/${a.id}/run`} title={a.name} className="side-recent">
                <i className={`life-dot ${a.state ?? "built"}`} aria-label={t(`life.state.${a.state ?? "built"}`)} />
                <span className="nav-label" dir="auto">{a.name}</span>
              </NavLink>
            ))}
          </div>
        )}
        <div className="side-group">
          <div className="side-heading">{t("nav.system")}</div>
          {link({ to: "/system", key: "health", icon: "trace" })}
          {me.role === "admin" && link({ to: "/activity", key: "activity", icon: "catalog" })}
          {link({ to: "/settings", key: "settings", icon: "settings" })}
          {me.engine_console_url && (
            <a href={me.engine_console_url} target="_blank" rel="noopener" title={rail ? t("engineConsole") : undefined}>
              <span className="ico" aria-hidden="true"><Wrench size={20} strokeWidth={1.6} /></span><span className="nav-label">{t("engineConsole")}</span>
            </a>
          )}
        </div>
      </nav>
      <button className="side-collapse" onClick={toggle} aria-expanded={!rail}>
        {rail ? <PanelLeftOpen aria-hidden="true" size={18} /> : <PanelLeftClose aria-hidden="true" size={18} />}
        <span className="nav-label">{t(rail ? "nav.expand" : "nav.collapse")}</span>
      </button>
    </aside>
  );
}
