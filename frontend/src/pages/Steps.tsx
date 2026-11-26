// An agent's steps, drawn by Agent Studio (React Flow) from the Agent Studio definition, in plain words.
// Read-only: changes are made by describing them (Create -> same draft) so the director keeps every rule
// (approvals, allowed tools) intact. Layout is computed here (start -> agent -> result across the middle, the model
// above the agent, tools below), so every agent reads the same way whatever positions the engine stored.
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Bell, Bot, BrainCircuit, CalendarClock, FileText, GitMerge, MessageSquare, MessageSquareReply, Plug, ShieldCheck, Users, Wrench, type LucideIcon } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { designApi, type Design } from "../designApi";
import { Failed, Loading } from "../components/Status";
import { useLoad } from "../components/useLoad";
import { Topbar } from "../components/Topbar";

type Step = { id: string; component: string; params: Record<string, unknown>; position?: { x: number; y: number }; tool?: boolean };
type Conn = { from: string; output: string; to: string; input: string };
type Definition = { steps: Step[]; connections: Conn[] };
type Palette = { components: Record<string, { label: string; group: string; group_label: string }>; capabilities: { id: string; label: string; component: string; app?: string }[] };
type Kind = "start" | "model" | "agent" | "tool" | "approval" | "logic" | "notify" | "output";

async function get<T>(path: string): Promise<T> {
  const r = await fetch("/api/studio/v1" + path, { credentials: "same-origin" });
  if (r.status === 401) { window.location.assign("/auth/login"); throw new Error("Signed out"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: r.statusText }))).detail);
  return r.json();
}

const ICON: Record<Kind, LucideIcon> = { start: MessageSquare, model: BrainCircuit, agent: Bot, tool: Wrench, approval: ShieldCheck, logic: GitMerge, notify: Bell, output: MessageSquareReply };

function kindOf(s: Step, conns: Conn[]): Kind {
  const c = s.component;
  if (s.tool || conns.some((x) => x.from === s.id && x.output === "tool")) return "tool";
  if (c === "Agent") return "agent";
  if (c.includes("LanguageModel")) return "model";
  if (c === "ChatInput" || c.includes("Trigger") || c.includes("Webhook")) return "start";
  if (c === "HumanInput") return "approval";
  if (c === "ChatOutput") return "output";
  if (/notify|teams|mail/i.test(c)) return "notify";
  return "logic";
}

function detail(step: Step, pal: Palette): string {
  const p = step.params;
  if (step.component === "ScheduleTrigger") return `${p.cron_expression ?? ""} ${p.timezone ?? ""}`.trim();
  if (step.component === "RunFlow") return String(p.flow_name_selected ?? "");
  if (typeof p.channel === "string") return p.channel;
  if (typeof p.app === "string") return pal.capabilities.find((c) => c.component === step.component && c.app === p.app)?.label ?? String(p.app);
  if (p.model && typeof p.model === "object") return String((p.model as { name?: string }).name ?? "");
  return "";
}

/** start -> ... -> result across the middle (longest path from the start), model above the agent, tools fanned below. */
function layout(steps: Step[], conns: Conn[], kinds: Record<string, Kind>) {
  const X = 300, pos: Record<string, { x: number; y: number }> = {};
  const main = steps.filter((s) => !["tool", "model"].includes(kinds[s.id]));
  const rank: Record<string, number> = {};
  main.forEach((s) => { rank[s.id] = kinds[s.id] === "start" ? 0 : -1; });
  for (let i = 0; i < main.length; i++) {           // longest-path ranks (graphs here are tiny and acyclic)
    for (const c of conns) {
      if (c.output === "tool" || !(c.from in rank) || !(c.to in rank) || rank[c.from] < 0) continue;
      rank[c.to] = Math.max(rank[c.to], rank[c.from] + 1);
    }
  }
  const byRank: Record<number, string[]> = {};
  main.forEach((s) => { const r = rank[s.id] < 0 ? 0 : rank[s.id]; (byRank[r] ||= []).push(s.id); });
  Object.entries(byRank).forEach(([r, ids]) => ids.forEach((id, i) => { pos[id] = { x: Number(r) * X, y: (i - (ids.length - 1) / 2) * 150 }; }));
  for (const s of steps) {
    const target = conns.find((c) => c.from === s.id)?.to;
    const anchor = (target && pos[target]) || { x: X, y: 0 };
    if (kinds[s.id] === "model") pos[s.id] = { x: anchor.x, y: anchor.y - 170 };
  }
  const tools = steps.filter((s) => kinds[s.id] === "tool");
  tools.forEach((s, i) => {
    const target = conns.find((c) => c.from === s.id)?.to;
    const anchor = (target && pos[target]) || { x: X, y: 0 };
    pos[s.id] = { x: anchor.x + (i - (tools.length - 1) / 2) * 250, y: anchor.y + 190 };
  });
  return pos;
}

function StepNode({ data }: NodeProps) {
  const d = data as { label: string; detail: string; kind: Kind; kindLabel: string };
  const Ico = ICON[d.kind];
  return (
    <div className={`flow-node k-${d.kind}`}>
      <Handle type="target" position={d.kind === "tool" ? Position.Top : Position.Left} id="in" />
      <span className="fn-ico"><Ico size={18} strokeWidth={1.8} /></span>
      <span className="fn-txt">
        <small>{d.kindLabel}</small>
        <b>{d.label}</b>
        {d.detail && <em title={d.detail}>{d.detail}</em>}
      </span>
      <Handle type="source" position={d.kind === "tool" || d.kind === "model" ? (d.kind === "tool" ? Position.Top : Position.Bottom) : Position.Right} id="out" />
    </div>
  );
}
const nodeTypes = { step: StepNode };

export function Steps() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const agent = useLoad(() => api.agent(id), [id]);
  const def = useLoad(() => get<Definition>(`/agents/${id}/definition`), [id]);
  const pal = useLoad(() => get<Palette>("/palette"));
  const mcp = useLoad(() => get<{ enabled: boolean; tool: string; url: string }>(`/agents/${id}/mcp`), [id]);
  const design = useLoad<Design | null>(async () => {
    const mine = (await designApi.drafts()).find((d) => d.agent_id === id);
    return mine ? designApi.get(mine.id) : null;
  }, [id]);

  const graph = useMemo(() => {
    if (!def.data || !pal.data) return null;
    const conns = def.data.connections;
    const kinds = Object.fromEntries(def.data.steps.map((s) => [s.id, kindOf(s, conns)])) as Record<string, Kind>;
    const pos = layout(def.data.steps, conns, kinds);
    const nodes: Node[] = def.data.steps.map((s) => {
      const c = pal.data!.components[s.component];
      return { id: s.id, type: "step", position: pos[s.id] ?? { x: 0, y: 0 },
        data: { label: c?.label ?? s.component, detail: detail(s, pal.data!), kind: kinds[s.id], kindLabel: t(`steps.kind.${kinds[s.id]}`) } };
    });
    const edges: Edge[] = conns.map((c, i) => {
      const tool = c.output === "tool", model = kinds[c.from] === "model";
      return {
        id: `e${i}`, source: c.from, target: c.to, sourceHandle: "out", targetHandle: "in", type: "smoothstep",
        animated: !tool && !model, className: tool ? "e-tool" : model ? "e-model" : "e-main",
        markerEnd: tool || model ? undefined : { type: MarkerType.ArrowClosed, width: 18, height: 18 },
        label: c.output === "branch_approve" ? t("steps.approve") : c.output === "branch_reject" ? t("steps.reject") : undefined,
      };
    });
    return { nodes, edges };
  }, [def.data, pal.data, t]);

  if (agent.loading || def.loading || pal.loading) return <Loading />;
  const err = agent.error || def.error || pal.error;
  if (err || !graph) return <Failed message={err || ""} retry={() => { agent.reload(); def.reload(); pal.reload(); }} />;

  const prefs = design.data?.prefs;
  const tools = graph.nodes.filter((n) => (n.data as { kind: Kind }).kind === "tool").map((n) => (n.data as { detail: string; label: string }).detail || (n.data as { label: string }).label);
  const model = graph.nodes.find((n) => (n.data as { kind: Kind }).kind === "model");
  const how: { icon: LucideIcon; title: string; text: string }[] = [
    { icon: prefs?.trigger === "schedule" ? CalendarClock : MessageSquare, title: t("steps.how.start"),
      text: prefs?.trigger === "schedule" ? (prefs.schedule_text || prefs.cron || "") : prefs?.trigger === "alert" ? t("steps.how.onAlert") : t("steps.how.onAsk") },
    { icon: BrainCircuit, title: t("steps.how.thinks"), text: model ? (model.data as { detail: string }).detail : "—" },
    { icon: Wrench, title: t("steps.how.uses"), text: tools.join(", ") || t("steps.how.nothing") },
    ...(design.data?.skills_applied?.length ? [{ icon: FileText, title: t("steps.how.follows"), text: design.data.skills_applied.join(", ") }] : []),
    ...(prefs?.sub_agents?.length ? [{ icon: Users, title: t("steps.how.team"), text: t("steps.how.teamText", { n: prefs.sub_agents.length }) }] : []),
    { icon: ShieldCheck, title: t("steps.how.changes"), text: prefs?.acts === "with_approval" ? t("steps.how.asksFirst") : t("steps.how.readOnly") },
    ...(mcp.data?.enabled ? [{ icon: Plug, title: t("steps.how.mcp"), text: t("steps.how.mcpText", { url: mcp.data.url }) }] : []),
    { icon: MessageSquareReply, title: t("steps.how.answers"), text: prefs?.notify && prefs.notify !== "never" ? `${t("steps.how.notifies")} ${prefs.channel ?? ""}`.trim() : t("steps.how.inChat") },
  ];

  return (
    <>
      <Topbar title={<>{agent.data?.name}<small className="tech">{t("steps.title")}</small></>} subtitle={t("top.sub.steps")}>
        <Link className="btn primary" to={`/agents/${id}/run`}>{t("agents.run")}</Link>
      </Topbar>
      <div className="steps-layout">
        <section className="card steps-canvas" aria-label={t("steps.title")}>
          <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.25 }}
            nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} proOptions={{ hideAttribution: true }}>
            <Background gap={24} size={1.2} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </section>
        <aside className="card steps-how">
          <h2>{t("steps.how.title")}</h2>
          <ol>
            {how.map((h) => (
              <li key={h.title}><span className="sh-ico"><h.icon size={16} /></span><span><b>{h.title}</b><small dir="auto">{h.text}</small></span></li>
            ))}
          </ol>
          <p className="help">{t("steps.howToChange")}</p>
          {design.data && <Link className="btn" to={`/create/${design.data.id}`}>{t("agents.change")}</Link>}
        </aside>
      </div>
    </>
  );
}
