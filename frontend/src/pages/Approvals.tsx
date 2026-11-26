import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, when, type Approval, type RunResult } from "../api";
import { Icon } from "../components/Icon";
import { Empty, Failed, Loading } from "../components/Status";
import { useLoad } from "../components/useLoad";
import { Topbar } from "../components/Topbar";

/** Actions agents want to take, waiting for a person. Nothing changes in any system until someone approves. */
export function Approvals() {
  const { t, i18n } = useTranslation();
  const list = useLoad(api.approvals);
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<Record<string, { decision: string; result?: RunResult; error?: string }>>({});

  async function decide(a: Approval, decision: "approve" | "reject") {
    setBusy(a.id);
    try {
      const result = await api.decide(a.id, a.agent_id, decision);
      setDone((d) => ({ ...d, [a.id]: { decision, result } }));
    } catch (err) {
      setDone((d) => ({ ...d, [a.id]: { decision, error: (err as Error).message } }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <Topbar title={<>{t("appr.title")}<small className="tech">{t("tech.approvals")}</small></>} subtitle={t("appr.intro")}>
        <button className="btn ghost" onClick={() => { setDone({}); list.reload(); }}>{t("appr.refresh")}</button>
      </Topbar>
      <section className="card list-card">
        {list.loading && <Loading />}
        {list.error && <Failed message={list.error} retry={list.reload} />}
        {list.data && list.data.length === 0 && <Empty title={t("appr.emptyTitle")} text={t("appr.emptyText")} />}
        <div className="list">
          {(list.data ?? []).map((a) => {
            const d = done[a.id];
            const failed = Boolean(d?.error) || d?.result?.status === "failed";
            return (
              <article className="approval" key={a.id}>
                <header>
                  <span className="chip"><Icon name="approvals" /></span>
                  <span className="txt"><b>{a.agent_name}</b><small>{when(a.asked_at, i18n.language)}</small></span>
                </header>
                <p className="proposal">{a.proposal}</p>
                {!d && (
                  <div className="actions">
                    <button className="btn primary" disabled={busy !== null} onClick={() => decide(a, "approve")}>
                      {busy === a.id ? t("appr.working") : t("appr.approve")}
                    </button>
                    <button className="btn ghost" disabled={busy !== null} onClick={() => decide(a, "reject")}>{t("appr.reject")}</button>
                  </div>
                )}
                {d && (
                  <div className={`outcome ${failed ? "err" : "ok"}`} role="status">
                    <b>{d.decision === "approve" ? t("appr.approved") : t("appr.rejected")}</b>
                    <p>{d.error ? t("run.failed", { detail: d.error })
                      : d.result?.reply || (d.decision === "approve" ? t("run.noReply") : t("appr.nothingChanged"))}</p>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>
    </>
  );
}
