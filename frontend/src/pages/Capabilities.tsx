import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { Topbar } from "../components/Topbar";
import { useLoad } from "../components/useLoad";
import { GROUPS } from "./features";
import { FlowChart } from "../components/FlowChart";

/** Everything Agent Studio can do: groups on the left, their features on the right, live counts from this system on top. */
export function Capabilities() {
  const { t, i18n } = useTranslation();
  const ar = i18n.language.startsWith("ar");
  const [open, setOpen] = useState(GROUPS[0].id);
  const [view, setView] = useState<"flow" | "list">("flow");
  const live = useLoad(api.abilities);
  const g = GROUPS.find((x) => x.id === open) ?? GROUPS[0];
  const total = GROUPS.reduce((n, x) => n + x.items.length, 0);
  const fresh = GROUPS.reduce((n, x) => n + x.items.filter((f) => f.isNew).length, 0);
  const f = live.data;

  return (
    <div className="page-fit caps-page">
      <Topbar title={t("capsPage.title")} subtitle={t("capsPage.sub", { total, fresh })}>
        <div className="seg" role="tablist" aria-label={t("capsPage.view")}>
          <button role="tab" aria-selected={view === "flow"} className={view === "flow" ? "active" : ""} onClick={() => setView("flow")}>{t("capsPage.flow")}</button>
          <button role="tab" aria-selected={view === "list"} className={view === "list" ? "active" : ""} onClick={() => setView("list")}>{t("capsPage.list")}</button>
        </div>
      </Topbar>
      {f && (
        <div className="caps-proof" aria-label={t("capsPage.here")}>
          <span><b>{f.agents}</b>{t("capsPage.agents")}</span>
          <span><b>{f.live}</b>{t("capsPage.live")}</span>
          <span><b>{f.systems}</b>{t("capsPage.systems")}</span>
          <span><b>{f.skills}</b>{t("capsPage.skills")}</span>
          <span><b>{f.with_approval}</b>{t("capsPage.approval")}</span>
          <span><b>{f.files}</b>{t("capsPage.files")}</span>
          <span><b>{f.models.join(", ") || "—"}</b>{t(f.internet ? "can.p.webOn" : "can.p.webOff")}</span>
        </div>
      )}
      {view === "flow" && (
        <section className="card flow-card">
          <p className="help">{t("capsPage.flowHint")}</p>
          <FlowChart ar={ar} />
        </section>
      )}
      {view === "list" && <div className="caps-split">
        <nav className="card caps-groups" aria-label={t("capsPage.groups")}>
          {GROUPS.map((x) => (
            <button key={x.id} className={x.id === open ? "active" : ""} aria-pressed={x.id === open} onClick={() => setOpen(x.id)}>
              <span className="tile cyan"><Icon name={x.icon} /></span>
              <span className="cg-txt"><b>{ar ? x.ar : x.en}</b><small>{t("capsPage.count", { count: x.items.length })}</small></span>
            </button>
          ))}
        </nav>
        <section className="card caps-items" aria-live="polite">
          <h2>{ar ? g.ar : g.en}</h2>
          <div className="caps-grid">
            {g.items.map((x) => {
              const body = (
                <>
                  <b dir="auto">{ar ? x.ar : x.en}{x.isNew && <span className="badge ok">{t("capsPage.new")}</span>}</b>
                  <small dir="auto">{ar ? x.dar : x.den}</small>
                  {x.tech && <span className="tech">{x.tech}</span>}
                </>
              );
              return x.to ? <Link key={x.en} className="caps-item link" to={x.to}>{body}</Link> : <div key={x.en} className="caps-item">{body}</div>;
            })}
          </div>
        </section>
      </div>}
    </div>
  );
}
