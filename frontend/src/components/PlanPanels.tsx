// The designer's reply as a short sequence of decision panels (Mashahed pattern): what I understood -> how it
// starts -> what it may do -> how it thinks -> preferences with an honest estimate and one Create button.
// Every option says what you get, what you don't, and how long it takes on THIS server now.
import {
  ArrowRight, Bell, BrainCircuit, CalendarClock, CheckCircle2, ChevronDown, CircleSlash, Clock, Gauge, Hand, Lightbulb,
  MessageSquare, ShieldCheck, SlidersHorizontal, Sparkles, Wrench, XCircle, Zap, Eye,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { api } from "../api";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { Catalog, Design, Prefs } from "../designApi";

export type Estimates = Record<"fast" | "thorough", { seconds: number; measured_runs: number; available: boolean; detail: string }>;

type Props = {
  design: Design; cat: Catalog; estimates: Estimates | null; busy: string;
  answers: Record<string, string>; setAnswers: (a: Record<string, string>) => void; submitAnswers: () => void;
  send: (text: string) => void; setPrefs: (p: Partial<Prefs>) => void; openReview: () => void;
};

const secs = (s: number) => (s < 90 ? `${Math.max(1, Math.round(s))} s` : `${Math.round(s / 60)} min`);

function Cards<T extends string>({ label, value, onPick, cards }: {
  label: string; value: T; onPick: (v: T) => void;
  cards: { v: T; icon: ReactNode; name: string; lead: string; gets: string[]; not: string; meta?: ReactNode; disabled?: string }[];
}) {
  return (
    <div className="mk-cards" role="radiogroup" aria-label={label}>
      {cards.map((c) => (
        <button key={c.v} type="button" role="radio" aria-checked={value === c.v} disabled={!!c.disabled} title={c.disabled}
          className={`mk-card ${value === c.v ? "on" : ""}`} onClick={() => onPick(c.v)}>
          <span className="mk-head">{c.icon}<strong>{c.name}</strong>{value === c.v && <CheckCircle2 className="mk-check" />}</span>
          <small className="mk-lead">{c.lead}</small>
          <ul>{c.gets.map((g) => <li key={g}><CheckCircle2 aria-hidden="true" />{g}</li>)}</ul>
          <small className="mk-not"><XCircle aria-hidden="true" />{c.not}</small>
          {c.meta && <span className="mk-meta">{c.meta}</span>}
          {c.disabled && <span className="mk-meta warn">{c.disabled}</span>}
        </button>
      ))}
    </div>
  );
}

function Panel({ icon, title, lead, children, wide, tech }: { icon: ReactNode; title: string; lead?: string; children: ReactNode; wide?: boolean; tech?: string }) {
  return (
    <section className={`reply-panel ${wide ? "wide" : ""}`}>
      <header><span className="rp-icon">{icon}</span><div><h3>{title}{tech && <small className="tech">{tech}</small>}</h3>{lead && <p>{lead}</p>}</div></header>
      {children}
    </section>
  );
}

export function PlanPanels({ design, cat, estimates, busy, answers, setAnswers, submitAnswers, send, setPrefs, openReview }: Props) {
  const { t } = useTranslation();
  const plan = design.plan!;
  const prefs = design.prefs!;
  const w = design.watch;
  const kept = w?.facts ? [...w.facts.targets, ...w.facts.times, ...w.facts.formats] : [];
  const caps = cat.capabilities.filter((c) => prefs.capabilities.includes(c.id));
  const canChange = cat.capabilities.some((c) => c.side_effect === "write" && c.id !== "notify" && prefs.capabilities.includes(c.id));
  const tools = caps.filter((c) => c.id !== "notify").length;
  const est = estimates?.[prefs.brain];
  const perRun = est ? est.seconds : prefs.brain === "thorough" ? 120 : 25;
  const decided = plan.goals.length > 0 || prefs.capabilities.length > 0;

  return (
    <div className="plan-panels">
      {/* 1. What I understood */}
      <Panel icon={<Sparkles />} title={t("pp.understood")} wide>
        <p className="rp-text" dir="auto">{plan.understood}</p>
        <div className="nc-chips">
          <span className="nc-chip ok"><CheckCircle2 />{t("pp.reviewed")}</span>
          {kept.length > 0 && <span className="nc-chip"><ShieldCheck />{t("pp.kept", { list: kept.join(", ") })}</span>}
          {prefs.trigger === "schedule" && prefs.cron && <span className="nc-chip"><CalendarClock />{prefs.schedule_text || prefs.cron}</span>}
          {(w?.duplicate ?? []).map((d) => <span key={d.agent_id} className={`nc-chip ${d.kind === "duplicate" ? "warn" : ""}`}><Lightbulb />{d.text}</span>)}
        </div>
        {plan.existing_app && (
          <p className={`notice ${plan.existing_app.fully_covered ? "warn" : "info"}`}><Lightbulb size={16} />
            <span><b>{cat.apps.find((a) => a.id === plan.existing_app!.id)?.name} {t("create2.alreadyDoes")}</b> {plan.existing_app.reason}</span></p>
        )}
        {plan.missing.map((m) => (
          <div key={m.need} className="notice warn"><Wrench size={16} /><div><b>{t("create2.noTool")}</b> <span>{m.need}</span>
            <div className="actions start">
              <AutoTool need={m.need} send={send} />
              <WriteTool need={m.need} />
              <Link className="btn" to={`/tools?need=${encodeURIComponent(m.need)}&design=${design.id}`}>{t("create2.createTool")}</Link>
              <button className="btn ghost" onClick={() => send(`Continue without: ${m.need}`)}>{t("create2.skip")}</button>
            </div></div></div>
        ))}
        {plan.questions.length > 0 && (
          <div className="rp-questions">
            {plan.questions.map((q) => (
              <div key={q.id} className="nc-ask">
                <strong dir="auto">{q.text}</strong>
                <div className="nc-choices">
                  {q.options.map((o) => (
                    <button key={o} type="button" dir="auto" className={answers[q.id] === o ? "on" : ""} aria-pressed={answers[q.id] === o}
                      onClick={() => setAnswers({ ...answers, [q.id]: answers[q.id] === o ? "" : o })}>{o}</button>
                  ))}
                </div>
              </div>
            ))}
            <button className="btn primary" disabled={!Object.values(answers).some(Boolean) || !!busy} onClick={submitAnswers}>{t("create2.answer")}</button>
          </div>
        )}
        {plan.goals.length > 0 && (
          <details className="nc-highlights">
            <summary><ChevronDown />{t("pp.willDo")}</summary>
            <ol>{plan.goals.map((g) => <li key={g} dir="auto">{g}</li>)}</ol>
          </details>
        )}
        {(design.skills_applied?.length ?? 0) > 0 && (
          <p className="help skills-applied" dir="auto">{t("skills.applied", { list: design.skills_applied!.join(", ") })}</p>
        )}
        {(plan.suggestions?.length ?? 0) > 0 && (
          <div className="rp-suggest"><span>{t("create2.suggest")}</span>
            {plan.suggestions.map((x) => <button key={x} className="example" disabled={!!busy} onClick={() => send(`${t("create2.also")} ${x}`)}>+ {x}</button>)}
          </div>
        )}
      </Panel>

      {decided && (
        <>
          {/* 2. How it starts */}
          <Panel icon={<CalendarClock />} title={t("pp.startTitle")} lead={t("pp.startLead")} wide>
            <Cards label={t("pp.startTitle")} value={prefs.trigger} onPick={(trigger) => setPrefs({ trigger })} cards={[
              { v: "chat", icon: <MessageSquare />, name: t("create2.chat"), lead: t("pp.chatLead"), gets: [t("pp.chatGet1"), t("pp.chatGet2")], not: t("pp.chatNot"),
                meta: <><Clock />{t("pp.answerIn", { t: secs(perRun) })}</> },
              { v: "schedule", icon: <CalendarClock />, name: t("create2.schedule"), lead: prefs.schedule_text || t("pp.schedLead"),
                gets: [t("pp.schedGet1"), t("pp.schedGet2")], not: t("pp.schedNot"), meta: prefs.cron ? <><CalendarClock /><code>{prefs.cron}</code></> : <>{t("create2.noSchedule")}</> },
              { v: "alert", icon: <Zap />, name: t("create2.alert"), lead: t("pp.alertLead"), gets: [t("pp.alertGet1"), t("pp.alertGet2")], not: t("pp.alertNot") },
              { v: "watch", icon: <Eye />, name: t("create2.watch"), lead: prefs.trigger === "watch" && prefs.schedule_text ? prefs.schedule_text : t("pp.watchLead"),
                gets: [t("pp.watchGet1"), t("pp.watchGet2")], not: t("pp.watchNot") },
            ]} />
            {(prefs.trigger === "schedule" || prefs.trigger === "watch") && (
              <div className="row-inline">
                <label htmlFor="sched">{t("create2.when")}</label>
                <input id="sched" className="input" placeholder={t("create2.whenPh")} defaultValue={prefs.schedule_text || ""}
                  onBlur={(e) => e.target.value && e.target.value !== prefs.schedule_text && send(`Run it ${e.target.value}`)} />
              </div>
            )}
          </Panel>

          {/* 3. What it may do */}
          <Panel icon={<ShieldCheck />} title={t("create2.acts")} lead={t("pp.actsLead")} wide>
            <Cards label={t("create2.acts")} value={prefs.acts} onPick={(acts) => setPrefs({ acts })} cards={[
              { v: "read_only", icon: <CircleSlash />, name: t("create2.readOnly"), lead: t("create2.readOnlyHint"), gets: [t("pp.roGet1"), t("pp.roGet2")], not: t("pp.roNot") },
              { v: "with_approval", icon: <Hand />, name: t("create2.withApproval"), lead: t("create2.withApprovalHint"), gets: [t("pp.apGet1"), t("pp.apGet2")], not: t("pp.apNot"),
                meta: canChange ? <><Hand />{t("pp.apMeta")}</> : undefined },
            ]} />
          </Panel>

          {/* 4. How it thinks: time vs depth, measured here */}
          <Panel icon={<BrainCircuit />} title={t("create2.brain")} tech={t("tech.brain")} lead={t("pp.brainLead")} wide>
            <Cards label={t("create2.brain")} value={prefs.brain} onPick={(brain) => setPrefs({ brain })} cards={(["fast", "thorough"] as const).map((b) => ({
              v: b, icon: b === "fast" ? <Zap /> : <BrainCircuit />, name: t(`create2.${b}`), lead: t(`pp.${b}Lead`),
              gets: [t(`pp.${b}Get1`), t(`pp.${b}Get2`)], not: t(`pp.${b}Not`),
              meta: estimates ? <><Gauge />{t("pp.perRun", { t: secs(estimates[b].seconds) })} · {estimates[b].measured_runs ? t("pp.measured", { n: estimates[b].measured_runs }) : t("pp.notMeasured")}</> : undefined,
              disabled: estimates && !estimates[b].available ? t("pp.unavailable", { detail: estimates[b].detail }) : undefined,
            }))} />
          </Panel>

          {/* 5. Preferences + estimate + Create */}
          <section className="reply-panel prefs-panel">
            <header><span className="rp-icon"><SlidersHorizontal /></span><div><h3>{t("pp.prefsTitle")}</h3><p>{t("pp.prefsLead")}</p></div></header>
            <div className="pp-grid">
              <div>
                <label className="nc-label" htmlFor="agent-name">{t("create.name")}</label>
                <input id="agent-name" className="input" defaultValue={prefs.name} maxLength={80} onBlur={(e) => e.target.value !== prefs.name && setPrefs({ name: e.target.value })} />
                <span className="nc-label">{t("create2.uses")}</span>
                <div className="caps">
                  {cat.capabilities.map((c) => {
                    const on = prefs.capabilities.includes(c.id);
                    const off = c.status !== "ready";
                    return (
                      <label key={c.id} className={`cap ${on ? "on" : ""} ${off ? "off" : ""}`} title={c.description}>
                        <input type="checkbox" checked={on} disabled={off} onChange={() => setPrefs({ capabilities: on ? prefs.capabilities.filter((x) => x !== c.id) : [...prefs.capabilities, c.id] })} />
                        <span><b>{c.label}</b><small>{c.description}</small></span>
                        {off ? <em className="badge err">{t("create2.needsSetup")}</em> : c.test_system ? <em className="badge">{t("create2.testSystem")}</em> : null}
                        {c.side_effect === "write" && <em className="badge warn">{t("create2.changes")}</em>}
                      </label>
                    );
                  })}
                </div>
              </div>
              <div>
                <span className="nc-label">{t("create2.notify")}</span>
                <div className="seg wrap" role="radiogroup" aria-label={t("create2.notify")}>
                  {(["never", "problems", "always"] as const).map((n) => (
                    <button key={n} type="button" role="radio" aria-checked={prefs.notify === n} className={prefs.notify === n ? "active" : ""}
                      onClick={() => setPrefs({ notify: n, capabilities: n !== "never" && !prefs.capabilities.includes("notify") ? [...prefs.capabilities, "notify"] : prefs.capabilities })}>
                      {n !== "never" && <Bell size={14} />}{t(`create2.${n}`)}</button>
                  ))}
                </div>
                {prefs.notify !== "never" && (cat.channels.length ? (
                  <select className="input" aria-label={t("create2.channel")} value={prefs.channel || cat.channels[0].id} onChange={(e) => setPrefs({ channel: e.target.value })}>
                    {cat.channels.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
                  </select>) : <p className="help">{t("create2.noChannel")}</p>)}
                <span className="nc-label">{t("create2.style")}</span>
                <div className="seg wrap" role="radiogroup" aria-label={t("create2.style")}>
                  {(["short", "detailed", "report", "table", "data"] as const).map((d) => (
                    <button key={d} type="button" role="radio" aria-checked={prefs.detail === d} className={prefs.detail === d ? "active" : ""} onClick={() => setPrefs({ detail: d })}>{t(`create2.${d}`)}</button>
                  ))}
                </div>
                <span className="nc-label">{t("create2.effort")}</span>
                <div className="seg wrap" role="radiogroup" aria-label={t("create2.effort")}>
                  {(["quick", "normal", "deep"] as const).map((x) => (
                    <button key={x} type="button" role="radio" aria-checked={(prefs.effort || "normal") === x} className={(prefs.effort || "normal") === x ? "active" : ""}
                      title={t(`create2.effortHint.${x}`)} onClick={() => setPrefs({ effort: x })}>{t(`create2.effort_${x}`)}</button>
                  ))}
                </div>
                {prefs.trigger === "chat" && (
                  <label className="toggle remember">
                    <input type="checkbox" checked={!!prefs.remember} onChange={(e) => setPrefs({ remember: e.target.checked })} />
                    {t("create2.remember")}<small className="tech">{t("tech.memory")}</small>
                  </label>
                )}
                {cat.agents.filter((a) => a.id !== design.agent_id).length > 0 && (
                  <>
                    <span className="nc-label">{t("create2.otherAgents")}</span>
                    <div className="caps compact">
                      {cat.agents.filter((a) => a.id !== design.agent_id).slice(0, 8).map((a) => {
                        const on = prefs.sub_agents.includes(a.id);
                        return (
                          <label key={a.id} className={`cap ${on ? "on" : ""}`}>
                            <input type="checkbox" checked={on} onChange={() => setPrefs({ sub_agents: on ? prefs.sub_agents.filter((x) => x !== a.id) : [...prefs.sub_agents, a.id] })} />
                            <span><b dir="auto">{a.name}</b></span>
                          </label>
                        );
                      })}
                    </div>
                  </>
                )}
              </div>
            </div>
            <footer>
              <p className="nc-estimate"><Clock /><span>{t("pp.estimate", { build: "10 s", test: secs(perRun + 5), run: secs(perRun), tools })}
                {est && !est.available && <> <b className="warn-text">{t("pp.modelDown")}</b></>}</span></p>
              <p className="nc-check"><ShieldCheck /><span>{t(canChange ? "pp.safeChanges" : "pp.safeRead")}</span></p>
              <button className="nc-create" disabled={!!busy || !prefs.capabilities.length} onClick={openReview}>
                <Sparkles />{design.agent_id ? t("create2.update") : t("pp.create")}<ArrowRight className="flip-rtl" />
              </button>
            </footer>
          </section>
        </>
      )}
    </div>
  );
}


/** "Find it for me": Agent Studio reuses a tool that exists, or drafts and tests one from the system's own description
 *  (no code written). No known system covers it -> it asks for the system's address right here. Once the system is
 *  connected (an administrator's own request is connected at once), the plan is made again with it. */
function AutoTool({ need, send }: { need: string; send: (text: string) => void }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const [askAddress, setAskAddress] = useState(false);
  const [address, setAddress] = useState("");
  async function go(addr = "") {
    setBusy(true);
    try {
      const r = await api.autoTool(need, addr);
      setSaid(r.text);
      setAskAddress(r.outcome === "ask_address");
      if (r.outcome === "connected" || r.outcome === "reuse") send(t("create2.nowConnected", { what: r.outcome === "reuse" ? (r.tools ?? []).join(", ") : r.tool_id }));
    } catch (e) { setSaid((e as Error).message); setAskAddress(!!addr); } finally { setBusy(false); }
  }
  if (askAddress) return (
    <form className="auto-addr" onSubmit={(e) => { e.preventDefault(); if (address.trim()) void go(address.trim()); }}>
      <p className="help" role="status">{said}</p>
      <input className="input" dir="ltr" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="http://server:port" aria-label={t("create2.address")} />
      <button className="btn primary" type="submit" disabled={busy || !address.trim()}>{busy ? t("create2.finding") : t("create2.readIt")}</button>
    </form>
  );
  return said ? <p className="help" role="status">{said}</p>
    : <button className="btn primary" disabled={busy} onClick={() => go()}>{busy ? t("create2.finding") : t("create2.findTool")}</button>;
}


/** "Write a tool": Agent Studio writes a Python tool for the need, tries it in the engine and lists its risks; an
 *  administrator reads the code and approves it on the Systems page (changes still ask a person on every call). */
function WriteTool({ need }: { need: string }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  async function go() {
    setBusy(true);
    try { setSaid((await api.codeDraft(need)).text); } catch (e) { setSaid((e as Error).message); } finally { setBusy(false); }
  }
  return said ? <p className="help" role="status">{said} <Link to="/tools">{t("code.openSystems")}</Link></p>
    : <button className="btn" disabled={busy} onClick={go} title={t("code.writeHint")}>{busy ? t("code.writing") : t("code.write")}</button>;
}

