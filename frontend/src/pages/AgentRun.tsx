import { useEffect, useRef, useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { designApi } from "../designApi";
import { Failed, Loading } from "../components/Status";
import { useLoad } from "../components/useLoad";
import { Topbar } from "../components/Topbar";
import { AgentQuality } from "../components/AgentQuality";
import { Rich } from "../components/Rich";

type Line = { who: "user" | "agent"; text: string; error?: boolean; approval?: boolean; rated?: "good" | "bad" | "fixing" };

/** Chat with one agent. Each conversation is one run (session) in Executions. */
export function AgentRun() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const agent = useLoad(() => api.agent(id), [id]);
  const memory = useLoad(() => api.memory(id), [id]);
  useEffect(() => {   // an agent that remembers: show what was said before and continue that conversation
    if (!memory.data?.remembers) return;
    setSession(memory.data.session_id ?? undefined);
    setLines(memory.data.messages.filter((m) => m.text.trim()).map((m) => ({ who: m.sender === "User" ? "user" : "agent", text: m.text, error: m.error, rated: "good" })));
  }, [memory.data]);
  const design = useLoad(() => designApi.forAgent(id), [id]);
  const samples = design.data?.plan?.sample_questions ?? [];
  const [lines, setLines] = useState<Line[]>([]);
  const [session, setSession] = useState<string | undefined>();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [fix, setFix] = useState("");
  const rate = (i: number, rated: Line["rated"]) => setLines((l) => l.map((x, k) => (k === i ? { ...x, rated } : x)));
  async function sendFeedback(i: number, good: boolean, correction = "") {
    await api.feedback(id, { session_id: session, good, answer: lines[i].text, correction }).catch(() => undefined);
    rate(i, good ? "good" : "bad"); setFix("");
  }
  const logRef = useRef<HTMLDivElement>(null);
  const [params, setParams] = useSearchParams();
  const ask = params.get("ask");
  useEffect(() => {   // "Run again" from Runs: the same question, sent once
    if (!ask || !agent.data) return;
    setParams({}, { replace: true });
    void send(undefined, ask);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ask, agent.data]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [lines, busy]);

  async function send(e?: React.FormEvent, said?: string) {
    e?.preventDefault();
    const message = (said ?? text).trim();
    if (!message || busy) return;
    setText("");
    setLines((l) => [...l, { who: "user", text: message }]);
    setBusy(true);
    try {
      const r = await api.run(id, message, session);
      if (r.session_id) setSession(r.session_id);
      const reply = r.status === "waiting_approval" ? t("run.waiting", { proposal: r.reply })
        : r.status === "failed" ? t("run.failed", { detail: r.reply })
        : r.status === "running" ? t("run.stillRunning") : r.reply || t("run.noReply");
      setLines((l) => [...l, { who: "agent", text: reply, error: r.status === "failed", approval: r.status === "waiting_approval" }]);
    } catch (err) {
      setLines((l) => [...l, { who: "agent", text: t("run.failed", { detail: (err as Error).message }), error: true }]);
    } finally {
      setBusy(false);
    }
  }

  if (agent.loading) return <Loading />;
  if (agent.error || !agent.data) return <Failed message={agent.error || ""} retry={agent.reload} />;

  return (
    <>
      <Topbar title={<>{t("run.title", { name: agent.data.name })}</>} subtitle={t("top.sub.run")}>
        {memory.data?.remembers
          ? <button className="btn ghost" title={t("run.forgetHint")} onClick={() => { if (confirm(t("run.forgetConfirm"))) void api.forget(id).then(() => { setLines([]); memory.reload(); }); }}>{t("run.forget")}<small className="tech">{t("tech.memory")}</small></button>
          : <button className="btn ghost" onClick={() => { setLines([]); setSession(undefined); }}>{t("run.newChat")}</button>}
        <Link className="btn" to={`/agents/${id}/steps`}>{t("agents.steps2")}</Link>
      </Topbar>
      <div className="run-split">
      <section className="card chat">
        <div className="log" ref={logRef} aria-live="polite">
          {lines.length === 0 && <p className="empty">{t("run.empty")}</p>}
          {lines.length === 0 && samples.length > 0 && (
            <div className="examples samples" aria-label={t("run.tryAsking")}>
              <span className="help">{t("run.tryAsking")}</span>
              {samples.map((q) => <button key={q} type="button" className="example" dir="auto" disabled={busy} onClick={() => send(undefined, q)}>{q}</button>)}
            </div>
          )}
          {lines.map((l, i) => (
            <div key={i} className={`bubble ${l.who}${l.error ? " err" : ""}`}>
              {l.who === "agent" ? <Rich text={l.text} /> : l.text}
              {l.approval && <div className="bubble-actions"><Link className="btn primary" to="/approvals">{t("run.openApprovals")}</Link></div>}
              {l.who === "agent" && !l.error && (
                <div className="rate">
                  {l.rated === "good" || l.rated === "bad" ? <small className="help">{t(l.rated === "good" ? "run.thanks" : "run.noted")}</small> : (
                    <>
                      <button type="button" className="icon-btn" title={t("run.good")} aria-label={t("run.good")} onClick={() => sendFeedback(i, true)}><ThumbsUp size={15} /></button>
                      <button type="button" className="icon-btn" title={t("run.bad")} aria-label={t("run.bad")} onClick={() => rate(i, "fixing")}><ThumbsDown size={15} /></button>
                    </>
                  )}
                  {l.rated === "fixing" && (
                    <form className="fix" onSubmit={(e) => { e.preventDefault(); void sendFeedback(i, false, fix.trim()); }}>
                      <input className="input" autoFocus dir="auto" value={fix} onChange={(e) => setFix(e.target.value)} placeholder={t("run.howShould")} />
                      <button className="btn" type="submit">{t("run.sendFix")}</button>
                    </form>
                  )}
                </div>
              )}
              {l.who === "agent" && session && <div className="bubble-how"><Link to={`/executions/${encodeURIComponent(session)}`}>{t("run.howAnswered")}</Link></div>}
            </div>
          ))}
          {busy && <div className="bubble agent" role="status">{t("run.sending")}</div>}
        </div>
        <form className="composer" onSubmit={send}>
          <label htmlFor="msg" className="visually-hidden" style={{ position: "absolute", left: -9999 }}>{t("run.placeholder")}</label>
          <textarea
            id="msg"
            className="input"
            value={text}
            placeholder={t("run.placeholder")}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) send(); }}
          />
          <button className="btn primary" type="submit" disabled={busy || !text.trim()}>{busy ? t("run.sending") : t("run.send")}</button>
        </form>
      </section>
      <AgentQuality agentId={id} />
      </div>
    </>
  );
}
