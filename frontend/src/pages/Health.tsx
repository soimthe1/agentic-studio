import { CircleAlert, CircleCheck, CircleMinus, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, when, type HealthItem } from "../api";
import { Failed, Loading } from "../components/Status";
import { Topbar } from "../components/Topbar";
import { useLoad } from "../components/useLoad";

const GROUPS: { key: HealthItem["group"]; title: string }[] = [
  { key: "models", title: "health.models" },
  { key: "systems", title: "health.systems" },
  { key: "channels", title: "health.channels" },
  { key: "app", title: "health.app" },
  { key: "engine", title: "health.engine" },
];

function State({ ok }: { ok: boolean | null }) {
  const { t } = useTranslation();
  if (ok === true) return <span className="state ok"><CircleCheck size={16} aria-hidden="true" />{t("health.ok")}</span>;
  if (ok === false) return <span className="state err"><CircleAlert size={16} aria-hidden="true" />{t("health.problem")}</span>;
  return <span className="state info"><CircleMinus size={16} aria-hidden="true" />{t("health.info")}</span>;
}

// Three columns: what agents think and talk with | the systems they read and change (can be many: own column,
// problems first, search) | Agent Studio itself and the engine.
const COLUMNS: HealthItem["group"][][] = [["models", "channels"], ["systems"], ["app", "engine"]];

function Group({ title, rows, grow }: { title: string; rows: HealthItem[]; grow: boolean }) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const bad = rows.filter((r) => r.ok === false).length;
  const shown = [...rows].filter((r) => !q || (r.name + " " + r.detail).toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => Number(a.ok !== false) - Number(b.ok !== false));
  return (
    <section className={`card health-card${grow ? " grow" : ""}`}>
      <div className="hc-head">
        <h2>{title}</h2>
        <span className={`badge ${bad ? "err" : "ok"}`}>{bad ? t("health.problemsShort", { count: bad }) : t("health.countOk", { count: rows.length })}</span>
      </div>
      {rows.length > 6 && <input className="input hc-search" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("health.find")} aria-label={t("health.find")} />}
      <ul className="health-list">
        {shown.map((i) => (
          <li key={i.name} className={i.ok === false ? "bad" : ""}>
            <div className="h-name">
              <b dir="auto" title={i.name}>{i.name}</b>
              {i.test_system && <span className="badge">{t("create2.testSystem")}</span>}
            </div>
            <State ok={i.ok} />
            <small dir="auto" title={i.detail}>{i.detail}{i.ms ? ` · ${i.ms} ms` : ""}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Everything Agent Studio and its agents depend on, checked now (house standard System health page). */
export function Health() {
  const { t, i18n } = useTranslation();
  const h = useLoad(api.system);
  const items = h.data?.items ?? [];

  return (
    <div className="page-fit">
      <Topbar title={t("health.title")} subtitle={t("health.sub")}>
        <button className="btn" onClick={h.reload} disabled={h.loading}>
          <RefreshCw size={16} aria-hidden="true" className={h.loading ? "spin" : ""} /> {h.loading ? t("health.checking") : t("health.recheck")}
        </button>
      </Topbar>
      {h.error && <Failed message={h.error} retry={h.reload} />}
      {h.loading && !h.data && <Loading />}
      {h.data && (
        <>
          <div className={`health-banner ${h.data.ok ? "ok" : "err"}`} role="status">
            {h.data.ok ? <CircleCheck size={22} aria-hidden="true" /> : <CircleAlert size={22} aria-hidden="true" />}
            <b>{h.data.ok ? t("health.allGood") : t("health.problems", { count: h.data.problems })}</b>
            <span>{t("health.checkedAt", { when: when(h.data.checked_at, i18n.language) })}</span>
          </div>
          <div className="health-cols">
            {COLUMNS.map((col, c) => (
              <div className="health-col" key={c}>
                {col.map((key) => {
                  const g = GROUPS.find((x) => x.key === key)!;
                  const rows = items.filter((i) => i.group === key);
                  if (!rows.length) return null;
                  return <Group key={key} title={t(g.title)} rows={rows} grow={key === "systems"} />;
                })}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
