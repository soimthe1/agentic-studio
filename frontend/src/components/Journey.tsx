import { AlertTriangle, Check, CircleCheck, FlaskConical, Hammer, Info, Loader2, MessageSquareText, Rocket, ShieldAlert, SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { Design, Finding } from "../designApi";

export const STAGES = ["describe", "shape", "build", "test", "live"] as const;
export type Stage = (typeof STAGES)[number];
type Busy = "" | "think" | "prefs" | "create" | "prove";

/** Where this agent is in its life, from what the draft already holds (no extra state to get out of sync). */
export function stageOf(design: Design | null, busy: Busy): { stage: Stage; working: boolean; warn: boolean } {
  if (!design) return { stage: "describe", working: busy === "think", warn: false };
  if (busy === "create") return { stage: "build", working: true, warn: false };
  if (busy === "prove") return { stage: "test", working: true, warn: false };
  if (design.status !== "created" || !design.agent_id) {
    const empty = !design.plan || (!design.plan.goals.length && !(design.prefs?.capabilities.length));
    return { stage: empty ? "describe" : "shape", working: busy === "think" || busy === "prefs", warn: false };
  }
  if (!design.proof) return { stage: "test", working: false, warn: false };
  const passed = design.proof.verdict === "met" || !!design.proof.approval;   // an approval stop is the right behaviour
  return passed ? { stage: "live", working: false, warn: false } : { stage: "test", working: false, warn: true };
}

const STAGE_ICON = { describe: MessageSquareText, shape: SlidersHorizontal, build: Hammer, test: FlaskConical, live: Rocket };
const ICON = { ok: CircleCheck, info: Info, warn: AlertTriangle, block: ShieldAlert };

/** What happened in each stage, taken from the conversation itself, so the chain and the chat always agree. */
function details(stage: Stage, d: Design | null, t: (k: string, o?: Record<string, unknown>) => string): Finding[] {
  if (!d) return [];
  const w = d.watch ?? {};
  const out: Finding[] = [];
  if (stage === "describe" && d.plan) {
    out.push({ level: "ok", text: t("journey.d.reviewed") });
    const kept = w.facts ? [...w.facts.targets, ...w.facts.times, ...w.facts.formats] : [];
    if (kept.length) out.push({ level: "info", text: t("journey.d.kept", { list: kept.join(", ") }) });
    out.push(...(w.intake ?? []));
  }
  if (stage === "shape" && d.plan) {
    const q = d.plan.questions.length;
    out.push(q ? { level: "warn", text: t("journey.d.questions", { count: q }) } : { level: "ok", text: t("journey.d.noQuestions") });
    if (d.prefs?.capabilities.length) out.push({ level: "ok", text: t("journey.d.uses", { count: d.prefs.capabilities.length }) });
    if (d.plan.missing.length) out.push({ level: "warn", text: t("journey.d.missing", { count: d.plan.missing.length }) });
    out.push(...(w.duplicate ?? []));
  }
  if (stage === "build") out.push(...(w.readiness ?? []), ...(w.build ?? []));
  if (stage === "test" && d.proof) {
    out.push({ level: d.proof.verdict === "met" ? "ok" : "warn", text: t(`create2.verdict.${d.proof.verdict}`) });
    if (d.proof.tools_used?.length) out.push({ level: "info", text: t("journey.d.used", { list: [...new Set(d.proof.tools_used)].join(", ") }) });
    if (d.proof.files?.length) out.push({ level: "ok", text: t("journey.d.files", { count: d.proof.files.length }) });
  }
  if (stage === "live" && d.agent_id && d.proof) {
    if (d.agent_state === "live") out.push({ level: "ok", text: t("journey.d.live") });
    else out.push(d.proof.approval ? { level: "info", text: t("journey.d.waiting") } : { level: "info", text: t("journey.d.ready") });
  }
  return out;
}

/** The agent's journey as one chain: done (with what happened), here now (and what to do), and what comes next. */
export function Journey({ design, busy }: { design: Design | null; busy: Busy }) {
  const { t } = useTranslation();
  const { stage, working, warn } = stageOf(design, busy);
  const at = STAGES.indexOf(stage);
  const done = stage === "live" && design?.agent_state === "live";
  return (
    <nav className="journey jv2" aria-label={t("journey.label")} style={{ ["--fill" as string]: String(Math.max(0, at - (done ? 0 : 0.5)) / (STAGES.length - 1)) }}>
      <div className="journey-head">
        <b>{t("journey.label")}</b>
        <span>{t("journey.progress", { n: at + 1 })}</span>
        <i className="journey-bar" aria-hidden="true"><i style={{ width: `${((at + (done ? 1 : 0.5)) / STAGES.length) * 100}%` }} /></i>
      </div>
      <ol>
        {STAGES.map((s, i) => {
          const state = i < at || (done && i === at) ? "done" : i === at ? (warn ? "warn" : "now") : "next";
          const rows = i < at ? details(s, design, t).slice(0, 1) : i === at ? details(s, design, t).slice(0, 4) : [];
          return (
            <li key={s} className={`${state} st-${s}`} aria-current={i === at ? "step" : undefined}>
              <span className="dot" aria-hidden="true">
                {state === "done" ? <Check size={18} /> : i === at && working ? <Loader2 size={18} className="spin" /> : (() => { const I = STAGE_ICON[s]; return <I size={18} />; })()}
              </span>
              <div className="txt">
                <b>{t(`journey.${s}.name`)}</b>
                <small>{i === at ? t(`journey.${s}.${done ? "done" : warn ? "warn" : working ? "working" : "now"}`) : t(`journey.${s}.what`)}</small>
                {i === at && !done && <p className="why">{t(`journey.${s}.why`)}</p>}
                {rows.length > 0 && (
                  <ul className="sub">
                    {rows.map((f, k) => {
                      const Ico = ICON[f.level];
                      return (
                        <li key={k} className={f.level}><Ico size={14} aria-hidden="true" />
                          <span dir="auto">{f.text}{f.agent_id && <> <Link to={`/agents/${f.agent_id}/run`}>{t("journey.open")}</Link></>}</span></li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
