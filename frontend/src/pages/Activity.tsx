import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, when } from "../api";
import { Empty, Failed, Loading } from "../components/Status";
import { Topbar } from "../components/Topbar";
import { useLoad } from "../components/useLoad";

/** Who did what, when (administrators). Search narrows it; the CSV holds the same rows for auditors. */
export function Activity() {
  const { t, i18n } = useTranslation();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const rows = useLoad(() => api.activity(query), [query]);
  return (
    <>
      <Topbar title={<>{t("activity.title")}<small className="tech">{t("tech.audit")}</small></>} subtitle={t("activity.intro")}>
        <a className="btn" href={`/api/studio/v1/activity.csv?q=${encodeURIComponent(query)}`}>{t("activity.export")}</a>
      </Topbar>
      <section className="card list-card">
        <form className="row-inline" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("activity.search")} aria-label={t("activity.search")} />
          <button className="btn" type="submit">{t("activity.find")}</button>
        </form>
        {rows.loading && <Loading />}
        {rows.error && <Failed message={rows.error} retry={rows.reload} />}
        {rows.data && rows.data.length === 0 && <Empty title={t("activity.noneTitle")} text={t("activity.noneText")} />}
        {rows.data && rows.data.length > 0 && (
          <div className="table-scroll"><table className="activity">
            <thead><tr><th>{t("activity.when")}</th><th>{t("activity.who")}</th><th>{t("activity.what")}</th><th>{t("activity.target")}</th></tr></thead>
            <tbody>
              {rows.data.map((r) => (
                <tr key={r.id}><td>{when(r.at, i18n.language)}</td><td>{r.who}</td><td>{r.action}</td><td dir="auto">{r.target}{r.detail ? ` - ${r.detail}` : ""}</td></tr>
              ))}
            </tbody>
          </table></div>
        )}
      </section>
    </>
  );
}
