// Client for the Agent Studio API (/api/studio/v1). The web app never calls the engine directly.
export type Agent = { id: string; name: string; description: string; updated_at: string | null; steps: number; needs_approval: boolean; state?: AgentState; live_version?: number | null; shared?: boolean;
  feedback?: { good: number; bad: number; corrections_waiting: number };
  last_check?: { at: string; verdict: "met" | "partly" | "not_met" | "unknown"; missing: string[]; retried: unknown } | null;
  health?: { status: "working_well" | "needs_attention" | "not_run_yet"; reason: string; last_run_at: string | null; recent_ok: number; recent_failed: number } };
export type LearnedOp = { id: string; method: string; path: string; summary: string; kind: "read" | "change"; query: string[]; body: string[]; path_params: string[]; matches_need: boolean };
export type Discovered = { address: string; found: boolean; detail?: string; title?: string; description?: string; reads?: number; changes?: number; connected?: string[] };
export type Learned = { title: string; description: string; base_url: string; contract_url: string; operations: LearnedOp[]; existing: { id: string; base_url: string }[];
  sign_in: { type: "ad_login"; login_path: string } | null };
export type ToolRequest = { id: string; tool_id: string; status: "draft" | "approved" | "rejected"; updated_at: string; decided_by: string | null;
  spec: { name: string; base_url: string; operations: LearnedOp[]; requested_by: string; update_of?: string;
    test?: { at: string; passed: boolean; results: { id: string; summary: string; ok: boolean | null; detail: string }[] } } };
export type ToolsView = { connected: { id: string; kind?: "system" | "code"; managed?: boolean; base_url?: string; purpose?: string; risk_level?: string; name: string; test_system: boolean; built_in: boolean; reads: string[]; changes: string[];
  version: number | null; used_by: { id: string; name: string }[]; sign_in: { account: string; saved: boolean } | null }[]; requests: ToolRequest[]; can_approve: boolean };
export type HealthItem = { group: "models" | "systems" | "channels" | "app" | "engine"; name: string; ok: boolean | null; detail: string; ms: number; test_system?: boolean };
export type Health = { checked_at: string; ok: boolean; problems: number; items: HealthItem[] };
export type FileRow = { name: string; bytes: number; format: string; modified_at: string };
export type AgentState = "built" | "live" | "paused" | "retired";
export type Approval = { id: string; agent_id: string; agent_name: string; request_id: string; proposal: string; asked_at: string | null; choices: string[] };
export type RunResult = { status: "done" | "waiting_approval" | "failed" | "running"; reply: string; session_id: string | null; job_id?: string; approval?: Approval | null };
export type Me = { id: string; username: string; is_admin: boolean; engine_console_url: string | null; role: "user" | "builder" | "admin"; local_accounts?: boolean; needs_setup?: boolean };
export type ModelProfile = { provider: "openai" | "ollama"; base_url: string; model: string; has_key?: boolean; api_key?: string | null };
export type ModelsView = { default: ModelProfile; reasoning: ModelProfile; needs_setup: boolean; saved_here: boolean; engine?: string };
export type Account = { username: string; name: string; role: "user" | "builder" | "admin"; created_at: string };
export type Run = { session_id: string; agent_id: string; agent_name: string; started_at: string; last_at: string; messages: number; error: boolean; first_message: string; tokens_in?: number; tokens_out?: number };
export type SharedAgent = { id: string; name: string; description: string; owner_name: string; samples: string[] };
export type TestCase = { id: number; question: string; expect: string; last: { passed: boolean; verdict: string; missing: string[]; at: string; session_id?: string } | null };
export type ToolStep = { name: string; ok: boolean; input: unknown; output?: string };
export type Msg = { id: string; agent_id: string; session_id: string; sender: string; sender_name: string; text: string; timestamp: string; error: boolean; tools?: ToolStep[] };
export type Dashboard = { needs_attention: number; agents: number; runs_7d: number; approvals_waiting: number; runs_by_day: number[]; failed_7d: number; success_rate_7d: number | null; recent_agents: Agent[] };

const BASE = "/api/studio/v1";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) {
    window.location.assign("/auth/login");
    throw new ApiError(401, "Signed out");
  }
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = typeof j.detail === "string" ? j.detail
        : typeof j.detail?.text === "string" ? j.detail.text : JSON.stringify(j.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(r.status, detail);
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

export const api = {
  me: () => call<Me>("GET", "/me"),
  dashboard: () => call<Dashboard>("GET", "/dashboard"),
  agents: () => call<Agent[]>("GET", "/agents"),
  agent: (id: string) => call<Agent>("GET", `/agents/${id}`),
  createAgent: (name: string, description: string) => call<Agent>("POST", "/agents", { name, description }),
  deleteAgent: (id: string) => call<void>("DELETE", `/agents/${id}`),
  run: (id: string, message: string, session_id?: string) =>
    call<RunResult>("POST", `/agents/${id}/run`, { message, session_id }),
  approvals: () => call<Approval[]>("GET", "/approvals"),
  publish: (id: string, note = "") => call<{ state: AgentState; live_version: number }>("POST", `/agents/${id}/publish`, { note }),
  lifecycle: (id: string, action: "pause" | "resume" | "retire") => call<{ state: AgentState }>("POST", `/agents/${id}/${action}`),
  versions: (id: string) => call<{ state: AgentState; live_version: number | null; versions: { version: number; note: string; created_by: string; created_at: string }[] }>("GET", `/agents/${id}/versions`),
  restoreVersion: (id: string, n: number) => call<{ state: AgentState }>("POST", `/agents/${id}/versions/${n}/restore`),
  files: () => call<FileRow[]>("GET", "/files"),
  system: () => call<Health>("GET", "/system"),
  estimates: () => call<unknown>("GET", "/estimates"),
  tools: () => call<ToolsView>("GET", "/tools"),
  mcpConnect: (agentId: string) => call<{ enabled: boolean; tool: string; url: string; settings: { json: unknown; curl: string } }>("GET", `/agents/${agentId}/mcp/connect`),
  mcpKeys: () => call<{ id: string; name: string; created_at: string; last_used_at: string | null }[]>("GET", "/mcp/keys"),
  mcpCreateKey: (label: string) => call<{ id: string; name: string; key: string }>("POST", "/mcp/keys", { label: label.slice(0, 60) }),
  mcpRevoke: (id: string) => call<void>("DELETE", `/mcp/keys/${id}`),
  memory: (agentId: string) => call<{ remembers: boolean; session_id: string | null; messages: Msg[] }>("GET", `/agents/${agentId}/memory`),
  forget: (agentId: string) => call<void>("DELETE", `/agents/${agentId}/memory`),
  feedback: (agentId: string, body: { session_id?: string; good: boolean; answer: string; correction?: string }) =>
    call<void>("POST", `/agents/${agentId}/feedback`, body),
  mcpServers: () => call<{ id: string; name: string; url: string; tools: { name: string; description: string }[]; changes: boolean }[]>("GET", "/mcp/servers"),
  mcpCheck: (body: Record<string, unknown>) => call<{ tools: { name: string; description: string }[] }>("POST", "/mcp/servers/check", body),
  mcpConnectServer: (body: Record<string, unknown>) => call<{ id: string }>("POST", "/mcp/servers", body),
  mcpDisconnect: (id: string) => call<void>("DELETE", `/mcp/servers/${id}`),
  activity: (q: string) => call<{ id: number; at: string; who: string; action: string; target: string; detail: string }[]>("GET", `/activity?q=${encodeURIComponent(q)}`),
  starters: (toolId: string) => call<{ tool_id: string; ideas: { kind: string; text: string }[] }>("GET", `/tools/${encodeURIComponent(toolId)}/starters`),
  share: (id: string, on: boolean) => call<{ shared: boolean; link: string }>("POST", `/agents/${id}/share`, { on }),
  shared: () => call<SharedAgent[]>("GET", "/shared"),
  sharedOne: (id: string) => call<SharedAgent>("GET", `/shared/${id}`),
  sharedRun: (id: string, message: string, session_id?: string) => call<RunResult>("POST", `/shared/${id}/run`, { message, session_id }),
  removeTool: (id: string, force = false) => call<{ removed: string; agents_affected: string[] }>("DELETE", `/tools/${encodeURIComponent(id)}${force ? "?force=true" : ""}`),
  codeDraft: (need: string, details = "", update_of = "") => call<{ outcome: "drafted" | "reuse" | "none"; text: string; request_id?: string; tool_id?: string; level?: string }>("POST", "/tools/code/draft", { need, details, update_of }),
  codeTry: (requestId: string, method: string, args: Record<string, unknown>) => call<{ passed: boolean; results: { summary: string; ok: boolean | null; detail: string }[] }>("POST", `/tools/code/${requestId}/try`, { method, args }),
  codeSecret: (toolId: string, name: string, value: string) => call<void>("POST", `/tools/code/${encodeURIComponent(toolId)}/secret`, { name, value }),
  toolkit: () => call<{ python: string; os: string; packages: Record<string, string>; programs: string[]; added: string[]; wheels: string[]; toolkit: string }>("GET", "/toolkit"),
  toolkitInstall: (packages: string) => call<{ ok: boolean; output: string }>("POST", "/toolkit/install", { packages }),
  autoTool: (need: string, address = "") => call<{ outcome: "drafted" | "connected" | "reuse" | "none" | "ask_address"; text: string; request_id?: string; tool_id?: string; tools?: string[] }>("POST", "/tools/auto", { need, address }),
  usage: (days = 7) => call<{ days: number; tokens: number; runs: number; agents: { agent_id: string; agent_name: string; runs: number; failed: number; tokens_in: number; tokens_out: number }[] }>("GET", `/usage?days=${days}`),
  notes: (id: string) => call<{ id: number; at: string; note: string }[]>("GET", `/agents/${id}/notes`),
  forgetNote: (id: string, noteId: number) => call<void>("DELETE", `/agents/${id}/notes/${noteId}`),
  tests: (id: string) => call<TestCase[]>("GET", `/agents/${id}/tests`),
  addTest: (id: string, question: string, expect: string) => call<{ id: number }>("POST", `/agents/${id}/tests`, { question, expect }),
  removeTest: (id: string, caseId: number) => call<void>("DELETE", `/agents/${id}/tests/${caseId}`),
  runTests: (id: string) => call<{ passed: number; total: number; cases: TestCase[] }>("POST", `/agents/${id}/tests/run`),
  abilities: () => call<{ agents: number; live: number; with_approval: number; systems: number; test_systems: number; known_addresses: number;
    skills: number; files: number; channels: number; internet: boolean; models: string[] }>("GET", "/abilities"),
  discover: () => call<{ systems: Discovered[] }>("GET", "/tools/discover"),
  learnTool: (address: string, need: string, trust_cert = false) => call<Learned>("POST", "/tools/learn", { address, need, trust_cert }),
  requestTool: (body: { name: string; purpose: string; base_url: string; contract_url: string; sign_in: string; account: string; password?: string; login_path?: string; trust_cert?: boolean; operations: LearnedOp[]; update_of?: string }) =>
    call<ToolRequest>("POST", "/tools/requests", body),
  decideTool: (id: string, decision: "approve" | "reject", force = false) => call<ToolRequest>("POST", `/tools/requests/${id}/${decision}${force ? "?force=true" : ""}`),
  trySignIn: (body: { base_url: string; login_path: string; account: string; password: string; trust_cert?: boolean }) =>
    call<{ ok: boolean; detail: string }>("POST", "/tools/sign-in/try", body),
  saveSignIn: (tool: string, account: string, password: string) =>
    call<{ ok: boolean; detail: string }>("POST", `/tools/${tool}/sign-in`, { account, password }),
  checkSignIn: (tool: string) => call<{ ok: boolean; detail: string; account: string }>("POST", `/tools/${tool}/sign-in/check`),
  testTool: (id: string) => call<NonNullable<ToolRequest["spec"]["test"]>>("POST", `/tools/requests/${id}/test`),
  uploadFile: async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    const r = await fetch(`${BASE}/files`, { method: "POST", body, credentials: "include" });
    if (!r.ok) { let d = r.statusText; try { d = (await r.json()).detail ?? d; } catch { /* keep */ } throw new Error(String(d)); }
  },
  deleteFile: (name: string) => call<void>("DELETE", `/files/${encodeURIComponent(name)}`),
  fileUrl: (name: string) => `${BASE}/files/${encodeURIComponent(name)}`,
  decide: (id: string, agent_id: string, decision: "approve" | "reject") =>
    call<RunResult>("POST", `/approvals/${id}`, { agent_id, decision }),
  models: () => call<ModelsView>("GET", "/setup/models"),
  testModel: (p: ModelProfile) => call<{ ok: boolean; error?: string; models?: string[]; model_available?: boolean }>("POST", "/setup/models/test", p),
  saveModels: (body: { default: ModelProfile; reasoning: ModelProfile | null }) => call<ModelsView>("PUT", "/setup/models", body),
  accounts: () => call<Account[]>("GET", "/accounts"),
  addAccount: (body: { username: string; name: string; password: string; role: string }) => call<Account>("POST", "/accounts", body),
  changeAccount: (username: string, body: { role?: string; password?: string }) => call<Account>("PATCH", `/accounts/${encodeURIComponent(username)}`, body),
  removeAccount: (username: string) => call<void>("DELETE", `/accounts/${encodeURIComponent(username)}`),
  myPassword: (current: string, next: string) => call<void>("POST", "/accounts/me/password", { current, new: next }),
  executions: () => call<Run[]>("GET", "/executions"),
  execution: (sessionId: string) => call<Msg[]>("GET", `/executions/${encodeURIComponent(sessionId)}`),
};

export function when(iso: string | null | undefined, lang: string): string {
  if (!iso) return "";
  const normalized = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z";
  return new Date(normalized).toLocaleString(lang === "ar" ? "ar-AE" : "en-GB", { dateStyle: "medium", timeStyle: "short" });
}

// Skills: know-how cards (Build area). Agents get matching approved skills automatically.
export type SkillCard = { name: string; when_to_use: string; steps: string[]; output_format: string; tools: string[]; example: string };
export type Skill = SkillCard & { id: string; version: number; approved_by: string; used_by: { id: string; name: string }[] };
export type SkillRequest = { id: string; skill_id: string; status: "draft" | "approved" | "rejected"; spec: SkillCard & { requested_by: string }; updated_at: string };
export const skillApi = {
  list: () => call<{ skills: Skill[]; requests: SkillRequest[]; can_approve: boolean }>("GET", "/skills"),
  draft: (text: string) => call<SkillCard>("POST", "/skills/draft", { text }),
  request: (card: SkillCard) => call<SkillRequest>("POST", "/skills", card),
  decide: (id: string, d: "approve" | "reject") => call<SkillRequest>("POST", `/skills/requests/${id}/${d}`),
};
