import { useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../api";
import { useMe } from "../App";
import { useLoad } from "./useLoad";

/** Beside an agent's chat: what it noted for its next runs (long-term memory) and its test questions. */
export function AgentQuality({ agentId }: { agentId: string }) {
  const { t } = useTranslation();
  const me = useMe();
  const builder = me?.role === "builder" || me?.role === "admin";
  const [tab, setTab] = useState<"tests" | "notes">("tests");
  const notes = useLoad(() => api.notes(agentId), [agentId]);
  const tests = useLoad(() => api.tests(agentId), [agentId]);
  const [q, setQ] = useState("");
  const [expect, setExpect] = useState("");
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<string>("");

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim() || !expect.trim()) return;
    try { await api.addTest(agentId, q.trim(), expect.trim()); setQ(""); setExpect(""); tests.reload(); } catch (err) { alert((err as Error).message); }
  }
  async function runAll() {
    setBusy(true); setSummary("");
    try { const r = await api.runTests(agentId); setSummary(t("quality.passed", { passed: r.passed, total: r.total })); tests.reload(); }
    catch (err) { setSummary((err as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <aside className="card quality" aria-label={t("quality.title")}>
      <div className="seg" role="tablist">
        <button role="tab" aria-selected={tab === "tests"} className={tab === "tests" ? "active" : ""} onClick={() => setTab("tests")}>{t("quality.tests")}</button>
        <button role="tab" aria-selected={tab === "notes"} className={tab === "notes" ? "active" : ""} onClick={() => setTab("notes")}>{t("quality.notes")}</button>
      </div>
      {tab === "tests" && (
        <div className="q-body">
          <p className="help">{t("quality.testsHint")}</p>
          <div className="list">
            {(tests.data ?? []).map((c) => (
              <div className="row q-case" key={c.id}>
                <span className={`badge ${c.last ? (c.last.passed ? "ok" : "err") : ""}`}>{c.last ? t(c.last.passed ? "quality.pass" : "quality.fail") : "—"}</span>
                <span className="txt" title={c.last && !c.last.passed ? c.last.missing.join(" · ") : undefined}>
                  <b dir="auto">{c.question}</b><small dir="auto">{t("quality.expects", { expect: c.expect })}</small>
                </span>
                {builder && <button className="icon-btn" aria-label={t("quality.remove")} onClick={() => api.removeTest(agentId, c.id).then(tests.reload)}><Trash2 size={15} /></button>}
              </div>
            ))}
          </div>
          {builder && (
            <>
              <form className="q-add" onSubmit={add}>
                <input className="input" dir="auto" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("quality.question")} aria-label={t("quality.question")} />
                <input className="input" dir="auto" value={expect} onChange={(e) => setExpect(e.target.value)} placeholder={t("quality.expect")} aria-label={t("quality.expect")} />
                <button className="btn" type="submit" disabled={!q.trim() || !expect.trim()}>{t("quality.add")}</button>
              </form>
              <button className="btn primary" disabled={busy || !(tests.data ?? []).length} onClick={runAll}>{busy ? t("quality.running") : t("quality.runAll")}</button>
              {summary && <p className="help" role="status">{summary}</p>}
            </>
          )}
        </div>
      )}
      {tab === "notes" && (
        <div className="q-body">
          <p className="help">{t("quality.notesHint")}</p>
          {(notes.data ?? []).length === 0 && <p className="empty">{t("quality.noNotes")}</p>}
          <div className="list">
            {(notes.data ?? []).map((n) => (
              <div className="row" key={n.id}>
                <span className="txt"><b dir="auto">{n.note}</b></span>
                {builder && <button className="icon-btn" aria-label={t("quality.forget")} title={t("quality.forget")} onClick={() => api.forgetNote(agentId, n.id).then(notes.reload)}><Trash2 size={15} /></button>}
              </div>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}
