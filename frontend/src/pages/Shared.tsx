import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Icon } from "../components/Icon";
import { Rich } from "../components/Rich";
import { Empty, Failed, Loading } from "../components/Status";
import { Topbar } from "../components/Topbar";
import { useLoad } from "../components/useLoad";

/** Agents colleagues shared: anyone signed in can chat with them (they cannot change them). */
export function SharedAgents() {
  const { t } = useTranslation();
  const list = useLoad(api.shared);
  return (
    <div className="page-fit">
      <Topbar title={t("shared.title")} subtitle={t("shared.sub")} />
      {list.loading && <Loading />}
      {list.error && <Failed message={list.error} retry={list.reload} />}
      {list.data && list.data.length === 0 && <Empty title={t("shared.emptyTitle")} text={t("shared.emptyText")} />}
      {list.data && list.data.length > 0 && (
        <div className="agent-grid">
          {list.data.map((a) => (
            <article className="agent-card" key={a.id}>
              <span className="chip"><Icon name="agents" /></span>
              <div className="txt">
                <b dir="auto">{a.name}</b>
                <small dir="auto">{a.description || " "}</small>
                {a.owner_name && <span className="meta">{t("shared.by", { name: a.owner_name })}</span>}
              </div>
              <div className="agent-actions"><Link className="btn primary" to={`/chat/${a.id}`}>{t("agents.run")}</Link></div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

type Line = { who: "user" | "agent"; text: string; error?: boolean };

/** Chat with a shared agent: share link /chat/<id>; with ?embed=1 it fills an iframe in another internal page. */
export function SharedChat() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const embed = params.get("embed") === "1";
  const { t } = useTranslation();
  const agent = useLoad(() => api.sharedOne(id), [id]);
  const [lines, setLines] = useState<Line[]>([]);
  const [session, setSession] = useState<string | undefined>();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => { logRef.current?.scrollTo({ top: logRef.current.scrollHeight }); }, [lines, busy]);

  async function send(e?: React.FormEvent, said?: string) {
    e?.preventDefault();
    const message = (said ?? text).trim();
    if (!message || busy) return;
    setText("");
    setLines((l) => [...l, { who: "user", text: message }]);
    setBusy(true);
    try {
      const r = await api.sharedRun(id, message, session);
      if (r.session_id) setSession(r.session_id);
      const reply = r.status === "waiting_approval" ? t("shared.waiting") : r.status === "failed" ? t("run.failed", { detail: r.reply }) : r.reply || t("run.noReply");
      setLines((l) => [...l, { who: "agent", text: reply, error: r.status === "failed" }]);
    } catch (err) {
      setLines((l) => [...l, { who: "agent", text: t("run.failed", { detail: (err as Error).message }), error: true }]);
    } finally {
      setBusy(false);
    }
  }

  if (agent.loading) return <Loading />;
  if (agent.error || !agent.data) return <Failed message={agent.error || ""} retry={agent.reload} />;
  const a = agent.data;
  return (
    <div className={`page-fit ${embed ? "embed" : ""}`}>
      {!embed && <Topbar title={a.name} subtitle={a.description || t("shared.sub")} />}
      <section className="card chat">
        <div className="log" ref={logRef} aria-live="polite">
          {lines.length === 0 && <p className="empty">{embed ? a.name : t("run.empty")}</p>}
          {lines.length === 0 && a.samples.length > 0 && (
            <div className="examples samples">
              <span className="help">{t("run.tryAsking")}</span>
              {a.samples.map((q) => <button key={q} type="button" className="example" dir="auto" disabled={busy} onClick={() => send(undefined, q)}>{q}</button>)}
            </div>
          )}
          {lines.map((l, i) => <div key={i} className={`bubble ${l.who}${l.error ? " err" : ""}`} dir="auto">{l.who === "agent" ? <Rich text={l.text} /> : l.text}</div>)}
          {busy && <div className="bubble agent" role="status">{t("run.sending")}</div>}
        </div>
        <form className="composer" onSubmit={send}>
          <textarea className="input" aria-label={t("run.placeholder")} value={text} placeholder={t("run.placeholder")}
            onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) send(); }} />
          <button className="btn primary" type="submit" disabled={busy || !text.trim()}>{busy ? t("run.sending") : t("run.send")}</button>
        </form>
      </section>
    </div>
  );
}
