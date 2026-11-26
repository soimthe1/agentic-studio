// Create an agent by describing it (smart contract). Describe -> Agent Studio answers with what it understood and ONE
// choices card (defaults preselected) -> Review (plain "it will / it will not", generated from the build) -> Create
// -> automatic first run + goal check -> fixes as one-click choices. Drafts are saved on the server (/create/:id).
import { AlertTriangle, Pencil, Bot, CheckCircle2, RotateCcw, Send, ShieldCheck, Sparkles, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { designApi, type Catalog, type Design, type Prefs, type Proof, type Summary } from "../designApi";
import { Failed, Loading } from "../components/Status";
import { useLoad } from "../components/useLoad";
import { Journey } from "../components/Journey";
import { PlanPanels, type Estimates } from "../components/PlanPanels";
import { Topbar } from "../components/Topbar";


/** Watchkeeper errors arrive as {"watchkeeper", "text"}: show only the plain text. */
function plainError(message: string): string {
  try { const d = JSON.parse(message); return d.text || message; } catch { return message; }
}

export function Create() {
  const { id } = useParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const catalog = useLoad(designApi.catalog);
  const estimates = useLoad(() => api.estimates() as Promise<Estimates>);
  const [design, setDesign] = useState<Design | null>(null);
  const [params] = useSearchParams();
  const [text, setText] = useState(params.get("idea") || "");   // a starter idea is filled in, never sent for the person
  const [busy, setBusy] = useState<"" | "think" | "prefs" | "create" | "prove">("");
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<Summary | null>(null);
  const [duplicateOf, setDuplicateOf] = useState<{ text: string; agent_id: string } | null>(null);
  const [editing, setEditing] = useState<{ index: number; text: string } | null>(null);

  async function saveEdit() {
    if (!design || !editing) return;
    const d = await run("think", () => designApi.editTurn(design.id, editing.index, editing.text.trim()));
    if (d) { setDesign(d); setEditing(null); setAnswers({}); setDuplicateOf(null); }
  }
  const review = useRef<HTMLDialogElement>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!id) { setDesign(null); return; }
    designApi.get(id).then(setDesign).catch((e: Error) => setError(e.message));
  }, [id]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [design?.turns.length, busy]);

  const prefsSeq = useRef(0);

  async function run<T>(kind: typeof busy, fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(kind); setError(null);
    try { return await fn(); } catch (e) { setError((e as Error).message); return undefined; } finally { setBusy(""); }
  }

  async function send(message: string) {
    const msg = message.trim();
    if (!msg || busy) return;
    setText("");
    const d = await run("think", () => (design ? designApi.say(design.id, msg) : designApi.start(msg)));
    if (d) { setDesign(d); setAnswers({}); if (!design) nav(`/create/${d.id}`, { replace: true }); }
  }

  async function setPrefs(p: Partial<Prefs>) {
    if (!design) return;
    const mine = ++prefsSeq.current;                                // quick clicks: only the newest answer may land
    setDesign((cur) => (cur ? { ...cur, prefs: { ...cur.prefs!, ...p } } : cur));   // instant feedback; server confirms
    const d = await run("prefs", () => designApi.prefs(design.id, p));
    if (d && mine === prefsSeq.current) setDesign(d);
  }

  async function openReview() {
    if (!design) return;
    const s = await run("prefs", () => designApi.preview(design.id));
    if (s) { setSummary(s); review.current?.showModal(); }
  }

  async function create(allowDuplicate = false) {
    if (!design) return;
    review.current?.close();
    setDuplicateOf(null);
    let dup: { text: string; agent_id: string } | null = null;
    const r = await run("create", () => designApi.create(design.id, allowDuplicate).catch((e: Error) => {
      try { const d = JSON.parse(e.message); if (d.watchkeeper === "duplicate") { dup = d; return undefined; } } catch { /* plain error */ }
      throw e;
    }));
    if (dup) { setDuplicateOf(dup); return; }
    if (!r) return;
    setDesign(r.design);
    const proof = await run("prove", () => designApi.prove(design.id));
    if (proof) setDesign({ ...r.design, proof });
  }

  if (catalog.loading) return <Loading />;
  if (catalog.error || !catalog.data) return <Failed message={catalog.error || ""} retry={catalog.reload} />;
  const cat: Catalog = catalog.data;
  const plan = design?.plan;
  const prefs = design?.prefs;

  return (
    <div className="create">
      <Topbar title={<>{design ? design.title || t("create2.title") : t("create2.title")}</>} subtitle={t("top.sub.create")}>
        {design && <button className="btn ghost" onClick={() => nav("/create")}><RotateCcw size={16} /> {t("create2.newOne")}</button>}
      </Topbar>
      <Journey design={design} busy={busy} />

      <section className="thread card" aria-live="polite">
        {!design && (
          <div className="intro">
            <Sparkles className="intro-mark" aria-hidden="true" />
            <h2>{t("create2.ask")}</h2>
            <p className="help">{t("create2.askHelp")}</p>
            <Templates onPick={(x) => { setText(x); document.getElementById("describe")?.focus(); }} />
          </div>
        )}
        {design?.turns.map((turn, i) => (
          <div key={i} className={`turn ${turn.role}${editing && i > editing.index ? " stale" : ""}`}>
            {turn.role === "assistant" && <Bot size={18} aria-hidden="true" />}
            {editing?.index === i ? (
              <form className="edit-turn" onSubmit={(e) => { e.preventDefault(); saveEdit(); }}>
                <textarea className="input" value={editing.text} autoFocus onChange={(e) => setEditing({ index: i, text: e.target.value })} />
                <small className="help">{t("create2.editHint")}</small>
                <div className="actions start">
                  <button className="btn primary" type="submit" disabled={!editing.text.trim() || !!busy}>{t("create2.editSave")}</button>
                  <button className="btn ghost" type="button" onClick={() => setEditing(null)}>{t("create2.editCancel")}</button>
                </div>
              </form>
            ) : (
              <>
                <p dir="auto">{turn.text}</p>
                {turn.role === "user" && !busy && !editing && (
                  <button className="icon-btn edit" onClick={() => setEditing({ index: i, text: turn.text })} title={t("create2.edit")} aria-label={t("create2.edit")}>
                    <Pencil size={15} />
                  </button>
                )}
              </>
            )}
          </div>
        ))}
        {busy === "think" && <div className="turn assistant thinking" role="status"><Bot size={18} aria-hidden="true" /><p>{t("create2.thinking")}</p></div>}
        {(error || design?.error) && <p className="notice err" role="alert"><AlertTriangle size={16} /> {plainError(error || design?.error || "")}</p>}
        {duplicateOf && (
          <div className="notice warn" role="alert">
            <AlertTriangle size={18} />
            <div>
              <b>{duplicateOf.text}</b>
              <div className="actions start">
                <Link className="btn primary" to={`/agents/${duplicateOf.agent_id}/run`}>{t("journey.useExisting")}</Link>
                <button className="btn" onClick={() => create(true)}>{t("journey.buildAnyway")}</button>
              </div>
            </div>
          </div>
        )}

        {design && plan && prefs && !plan.refuse && (
          <PlanPanels design={design} cat={cat} estimates={estimates.data ?? null} busy={busy} answers={answers} setAnswers={setAnswers}
            submitAnswers={async () => { const d = await run("think", () => designApi.answer(design.id, Object.fromEntries(Object.entries(answers).filter(([, v]) => v)))); if (d) { setDesign(d); setAnswers({}); } }}
            send={send} setPrefs={setPrefs} openReview={openReview} />
        )}
        {plan?.refuse && <p className="notice err" role="alert"><ShieldCheck size={16} /> {plan.refuse}</p>}

        {(busy === "create" || busy === "prove") && <div className="notice info" role="status"><Bot size={18} /> {busy === "create" ? t("create2.building") : t("create2.proving")}</div>}
        {design?.proof && <ProofCard proof={design.proof} agentId={design.agent_id!} onFix={(f) => send(f)} leftOut={design.left_out}
          state={design.agent_state} onPublished={() => setDesign({ ...design, agent_state: "live" })} />}
        <div ref={bottom} />
      </section>

      <form className="composer card" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <label htmlFor="describe" className="sr-only">{t("create2.ask")}</label>
        <textarea id="describe" className="input" value={text} placeholder={design ? t("create2.more") : t("create2.placeholder")}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(text); } }} />
        <button className="btn primary" type="submit" disabled={!text.trim() || !!busy} aria-label={t("run.send")}><Send size={18} /></button>
      </form>

      <dialog ref={review} aria-labelledby="review-title" className="review">
        {summary && (
          <>
            <h2 id="review-title">{summary.name}</h2>
            <h3>{t("create2.willDo")}</h3>
            <ul className="does">{summary.does.map((d) => <li key={d}><CheckCircle2 size={16} /> {d}</li>)}</ul>
            {summary.will_not.length > 0 && (<><h3>{t("create2.willNot")}</h3>
              <ul className="willnot">{summary.will_not.map((d) => <li key={d}><XCircle size={16} /> {d}</li>)}</ul></>)}
            <p className="help">{t("create2.thinksWith", { model: summary.thinks_with })}</p>
            <div className="actions">
              <button className="btn ghost" onClick={() => review.current?.close()}>{t("create2.change")}</button>
              <button className="btn primary" onClick={() => create()}>{design?.agent_id ? t("create2.updateNow") : t("create2.createNow")}</button>
            </div>
          </>
        )}
      </dialog>
    </div>
  );
}

function ProofCard({ proof, agentId, onFix, leftOut, state, onPublished }: { proof: Proof; agentId: string; onFix: (f: string) => void;
  leftOut: Design["left_out"]; state?: string | null; onPublished: () => void }) {
  const { t } = useTranslation();
  const ok = proof.verdict === "met";
  const [publishing, setPublishing] = useState(false);
  const [err, setErr] = useState("");
  async function publish() {
    setPublishing(true); setErr("");
    try { await api.publish(agentId, "Published from the designer"); onPublished(); } catch (e) { setErr((e as Error).message); } finally { setPublishing(false); }
  }
  return (
    <div className={`card inner proof ${proof.verdict}`}>
      <h3>{ok ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />} {t(`create2.verdict.${proof.verdict}`)}</h3>
      {proof.evidence && <p>{proof.evidence}</p>}
      <ul className="facts">
        <li>{proof.tools_used?.length ? t("create2.factTools", { list: [...new Set(proof.tools_used)].join(", ") }) : t("create2.factNoTools")}</li>
        {proof.files && proof.files.length > 0 && (
          <li>{t("create2.factFiles")} {proof.files.map((f) => <a key={f} href={api.fileUrl(f)} download>{f}</a>)}</li>
        )}
        {proof.approval && <li>{t("create2.factApproval")} <Link to="/approvals">{t("run.openApprovals")}</Link></li>}
      </ul>
      {proof.reply && <details><summary>{t("create2.firstReply")}</summary><pre className="reply">{proof.reply}</pre></details>}
      {proof.missing.length > 0 && <ul className="willnot">{proof.missing.map((m) => <li key={m}><XCircle size={16} /> {m}</li>)}</ul>}
      {leftOut.length > 0 && <p className="help">{t("create2.leftOut", { list: leftOut.map((x) => `${x.label} (${x.reason})`).join(", ") })}</p>}
      {proof.fixes.length > 0 && <div className="examples">{proof.fixes.map((f) => <button key={f} className="example" onClick={() => onFix(f)}>{f}</button>)}</div>}
      {(ok || proof.approval) && state !== "live" && (
        <div className="go-live">
          <div><b>{t("life.readyTitle")}</b><p>{t("life.readyText")}</p></div>
          <button className="nc-create" onClick={publish} disabled={publishing}>{publishing ? t("life.publishing") : t("life.publish")}</button>
        </div>
      )}
      {state === "live" && <p className="notice ok"><CheckCircle2 size={16} /> {t("life.isLive")}</p>}
      {err && <p className="notice err">{err}</p>}
      <div className="actions start">
        <Link className="btn primary" to={`/agents/${agentId}/run`}>{t("create2.useIt")}</Link>
        <Link className="btn" to={`/agents/${agentId}/steps`}>{t("create2.seeSteps")}</Link>
      </div>
    </div>
  );
}

/** Ready-made descriptions by team: a click fills the box; the person changes any words, then sends. */
function Templates({ onPick }: { onPick: (text: string) => void }) {
  const { t, i18n } = useTranslation();
  const teams = useLoad(designApi.templates);
  const [team, setTeam] = useState(0);
  const lang = i18n.language === "ar" ? "ar" : "en";
  if (!teams.data?.length) return null;
  const now = teams.data[Math.min(team, teams.data.length - 1)];
  return (
    <div className="templates">
      <p className="help">{t("create2.templatesHint")}</p>
      <div className="seg" role="tablist" aria-label={t("create2.templates")}>
        {teams.data.map((x, i) => (
          <button key={x.id} type="button" role="tab" aria-selected={i === team} className={i === team ? "active" : ""} onClick={() => setTeam(i)}>{x.name[lang] ?? x.name.en}</button>
        ))}
      </div>
      <div className="examples">
        {now.templates.map((x) => <button key={x.en} type="button" className="example" dir="auto" onClick={() => onPick(x[lang] ?? x.en)}>{x[lang] ?? x.en}</button>)}
      </div>
    </div>
  );
}
