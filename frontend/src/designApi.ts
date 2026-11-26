// Smart contract (Agent Designer) client: /api/studio/v1/designs and /capabilities.
import { ApiError } from "./api";

export type Question = { id: string; text: string; options: string[] };
export type Plan = {
  understood: string; name: string; goals: string[]; capabilities: string[]; sample_questions?: string[];
  missing: { need: string; kind: "tool" | "system" | "data" }[];
  existing_app: { id: string; reason: string; fully_covered: boolean } | null;
  similar_agent: { id: string; reason: string } | null;
  trigger: "chat" | "schedule" | "alert" | "watch"; schedule_text: string | null; cron: string | null;
  acts: "read_only" | "with_approval"; notify: "never" | "problems" | "always"; detail: "short" | "detailed" | "report" | "table" | "data";
  instructions: string; questions: Question[]; suggestions: string[]; refuse: string | null; language: "en" | "ar"; truncated: boolean;
};
export type Prefs = {
  name: string; trigger: Plan["trigger"]; cron: string | null; schedule_text: string | null; timezone: string;
  capabilities: string[]; acts: Plan["acts"]; notify: Plan["notify"]; channel: string | null;
  detail: Plan["detail"]; brain: "fast" | "thorough"; effort?: "quick" | "normal" | "deep"; sub_agents: string[]; skills?: string[]; remember?: boolean;
};
export type Proof = { message: string; reply: string; session_id: string | null; verdict: "met" | "partly" | "not_met" | "unknown"; evidence: string; missing: string[]; fixes: string[];
  tools_used?: string[]; files?: string[]; approval?: { id: string; proposal: string } | null };
export type Finding = { level: "ok" | "info" | "warn" | "block"; text: string; kind?: string; agent_id?: string; design_id?: string };
export type Watch = { facts?: { targets: string[]; times: string[]; formats: string[] }; intake?: Finding[]; duplicate?: Finding[]; readiness?: Finding[]; build?: Finding[] };
export type Design = {
  id: string; title: string; status: "draft" | "created"; agent_id: string | null;
  turns: { role: "user" | "assistant"; text: string }[]; plan: Plan | null; prefs: Prefs | null;
  left_out: { capability: string; label: string; reason: string }[]; watch?: Watch; agent_state?: "built" | "live" | "paused" | "retired" | null; error: string | null; proof: Proof | null; updated_at: string;
  skills_applied?: string[];
};
export type Capability = { id: string; label: string; description: string; examples?: string[]; side_effect: string; approval?: string; status: "ready" | "needs_setup"; test_system: boolean };
export type App = { id: string; name: string; purpose: string; already_does: string[] };
export type Catalog = { capabilities: Capability[]; apps: App[]; channels: { id: string; type: string; needs_approval: boolean }[]; agents: { id: string; name: string; description: string }[] };
export type Summary = { name: string; does: string[]; will_not: string[]; thinks_with: string; answer_style: string };
export type DraftRow = { id: string; title: string; status: string; agent_id: string | null; updated_at: string };

const BASE = "/api/studio/v1";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method, credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) {
    window.location.assign("/auth/login");
    throw new ApiError(401, "Signed out");
  }
  if (!r.ok) {
    let detail = r.statusText;
    try { const j = await r.json(); detail = typeof j.detail === "string" ? j.detail : typeof j.detail?.text === "string" ? j.detail.text : JSON.stringify(j.detail); } catch { /* keep */ }
    throw new ApiError(r.status, detail);
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

export const designApi = {
  catalog: () => call<Catalog>("GET", "/capabilities"),
  drafts: () => call<DraftRow[]>("GET", "/designs"),
  get: (id: string) => call<Design>("GET", `/designs/${id}`),
  forAgent: async (agentId: string) => {
    const row = (await call<DraftRow[]>("GET", "/designs")).find((d) => d.agent_id === agentId);
    return row ? call<Design>("GET", `/designs/${row.id}`) : null;
  },
  duplicate: (agentId: string) => call<Design>("POST", `/agents/${agentId}/duplicate`),
  templates: () => call<{ id: string; name: Record<string, string>; templates: Record<string, string>[] }[]>("GET", "/templates"),
  start: (text: string) => call<Design>("POST", "/designs", { text }),
  say: (id: string, text: string) => call<Design>("POST", `/designs/${id}/messages`, { text }),
  editTurn: (id: string, index: number, text: string) => call<Design>("POST", `/designs/${id}/turns/${index}`, { text }),
  answer: (id: string, answers: Record<string, string>) => call<Design>("POST", `/designs/${id}/answers`, { answers }),
  prefs: (id: string, prefs: Partial<Prefs>) => call<Design>("PATCH", `/designs/${id}/prefs`, { prefs }),
  preview: (id: string) => call<Summary>("GET", `/designs/${id}/preview`),
  create: (id: string, allowDuplicate = false) =>
    call<{ design: Design; agent: { id: string; name: string } }>("POST", `/designs/${id}/create${allowDuplicate ? "?allow_duplicate=true" : ""}`),
  prove: (id: string) => call<Proof>("POST", `/designs/${id}/prove`),
  discard: (id: string) => call<void>("DELETE", `/designs/${id}`),
};
