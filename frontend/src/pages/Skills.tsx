import { useState } from "react";
import { useTranslation } from "react-i18next";
import { skillApi, type SkillCard } from "../api";
import { Icon } from "../components/Icon";
import { Empty, Failed, Loading } from "../components/Status";
import { Topbar } from "../components/Topbar";
import { useLoad } from "../components/useLoad";

/** Skills: the organisation's know-how (how a job is done well). Agents get matching skills automatically. */
export function Skills() {
  const { t } = useTranslation();
  const list = useLoad(skillApi.list);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  async function decide(id: string, d: "approve" | "reject") {
    setBusy(id); setMsg("");
    try { await skillApi.decide(id, d); list.reload(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(null); }
  }

  return (
    <>
      <Topbar title={<>{t("skills.title")}<small className="tech">{t("tech.skills")}</small></>} subtitle={t("skills.intro")}>
        {!open && <button className="btn primary" onClick={() => setOpen(true)}>{t("skills.new")}</button>}
      </Topbar>
      {open && <NewSkill onDone={() => { setOpen(false); list.reload(); }} />}
      {msg && <p className="notice err" role="alert">{msg}</p>}
      {list.loading && <Loading />}
      {list.error && <Failed message={list.error} retry={list.reload} />}
      {list.data && (
        <>
          {list.data.requests.length > 0 && (
            <section className="card" style={{ marginBottom: 24 }}>
              <h2>{t("skills.requests")}</h2>
              <div className="list">
                {list.data.requests.map((r) => (
                  <div className="row" key={r.id}>
                    <span className="chip"><Icon name="catalog" /></span>
                    <span className="txt"><b>{r.spec.name}</b><small>{r.spec.when_to_use} · {r.spec.requested_by}</small></span>
                    <span className={`badge ${r.status === "rejected" ? "err" : "warn"}`}>{t(`tools.status.${r.status}`)}</span>
                    {list.data!.can_approve && r.status === "draft" && (
                      <>
                        <button className="btn primary" disabled={busy !== null} onClick={() => decide(r.id, "approve")}>{t("appr.approve")}</button>
                        <button className="btn ghost" disabled={busy !== null} onClick={() => decide(r.id, "reject")}>{t("appr.reject")}</button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
          <section className="card list-card">
            <h2>{t("skills.library")}</h2>
            {list.data.skills.length === 0 && <Empty title={t("skills.noneTitle")} text={t("skills.noneText")} />}
            <div className="skill-grid">
              {list.data.skills.map((s) => (
                <article className="skill" key={s.id}>
                  <header><b dir="auto">{s.name}</b><span className="badge">v{s.version}</span></header>
                  {s.when_to_use && <p className="help" dir="auto">{s.when_to_use}</p>}
                  <ol dir="auto">{s.steps.map((x) => <li key={x}>{x}</li>)}</ol>
                  {s.output_format && <p dir="auto"><small>{t("skills.format")}: {s.output_format}</small></p>}
                  <small>{s.used_by.length ? t("tools.usedBy", { list: s.used_by.map((a) => a.name).join(", ") }) : t("tools.unused")}</small>
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </>
  );
}

function NewSkill({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [card, setCard] = useState<SkillCard | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function write() {
    setBusy(true); setError("");
    try { setCard(await skillApi.draft(text)); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function submit() {
    if (!card) return;
    setBusy(true); setError("");
    try { await skillApi.request({ ...card, steps: card.steps.map((x) => x.trim()).filter(Boolean) }); onDone(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const set = (k: keyof SkillCard, v: string | string[]) => setCard((c) => (c ? { ...c, [k]: v } : c));

  return (
    <section className="card inner connect" style={{ marginBottom: 24 }}>
      <h2>{t("skills.new")}</h2>
      <label htmlFor="sk-text">{t("skills.describe")}</label>
      <textarea id="sk-text" className="input" rows={3} dir="auto" value={text} onChange={(e) => setText(e.target.value)} placeholder={t("skills.placeholder")} />
      <div className="actions start">
        <button className="btn primary" disabled={busy || text.trim().length < 10} onClick={write}>{busy && !card ? t("skills.writing") : t("skills.write")}</button>
      </div>
      {card && (
        <div className="skill-edit">
          <label>{t("skills.name")}<input className="input" dir="auto" value={card.name} onChange={(e) => set("name", e.target.value)} /></label>
          <label>{t("skills.when")}<input className="input" dir="auto" value={card.when_to_use} onChange={(e) => set("when_to_use", e.target.value)} /></label>
          <label>{t("skills.steps")}<textarea className="input" rows={5} dir="auto" value={card.steps.join("\n")} onChange={(e) => set("steps", e.target.value.split("\n"))} /></label>
          <label>{t("skills.format")}<input className="input" dir="auto" value={card.output_format} onChange={(e) => set("output_format", e.target.value)} /></label>
          <div className="actions start">
            <button className="btn primary" disabled={busy || !card.name.trim() || !card.steps.some((x) => x.trim())}
              onClick={submit}>{t("skills.submit")}</button>
          </div>
        </div>
      )}
      {error && <p className="notice err" role="alert">{error}</p>}
    </section>
  );
}
