import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { api, when, type Discovered, type Learned, type LearnedOp } from "../api";
import { Icon } from "../components/Icon";
import { Empty, Failed, Loading } from "../components/Status";
import { useLoad } from "../components/useLoad";
import { Topbar } from "../components/Topbar";
import { CodeReview, Libraries } from "../components/CodeTools";
import { McpServers } from "../components/McpServers";

/** Reusable tools: systems Agent Studio can use, requests for new ones, and connecting a new system from its contract. */
export function Tools() {
  const { t, i18n } = useTranslation();
  const [params] = useSearchParams();
  const need = params.get("need") || "";
  const back = params.get("design");
  const list = useLoad(api.tools);
  const [open, setOpen] = useState(Boolean(need));
  const [mcpOpen, setMcpOpen] = useState(false);
  const [start, setStart] = useState("");             // address handed over from Discover
  const [changing, setChanging] = useState<{ id: string; name: string; ops: string[] } | null>(null);   // a new version of a connected system
  async function remove(c: { id: string; name: string }) {
    if (!window.confirm(t("tools.removeConfirm", { name: c.name }))) return;
    try { await api.removeTool(c.id); list.reload(); }
    catch (e) {
      const m = (e as Error).message;
      if (m.includes("would lose") && window.confirm(m + "\n\n" + t("tools.removeAnyway"))) {
        try { await api.removeTool(c.id, true); list.reload(); } catch (e2) { setMsg((e2 as Error).message); }
      } else setMsg(m);
    }
  }
  async function changeCode(c: { id: string; name: string }) {
    const what = window.prompt(t("tools.changeAsk", { name: c.name }));
    if (!what?.trim()) return;
    setBusy(c.id); setMsg("");
    try { setMsg((await api.codeDraft(what.trim(), "", c.id)).text); list.reload(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(null); }
  }
  const [found, setFound] = useState<Discovered[] | null>(null);
  const [looking, setLooking] = useState(false);
  async function discover() {
    setLooking(true); setMsg("");
    try { setFound((await api.discover()).systems); } catch (e) { setMsg((e as Error).message); } finally { setLooking(false); }
  }
  const [busy, setBusy] = useState<string | null>(null);

  const [msg, setMsg] = useState("");
  const [ideas, setIdeas] = useState<{ tool: string; list: { kind: string; text: string }[] } | null>(null);
  async function showIdeas(tool: string) {
    if (ideas?.tool === tool) { setIdeas(null); return; }
    try { setIdeas({ tool, list: (await api.starters(tool)).ideas }); } catch (e) { setMsg((e as Error).message); }
  }
  async function decide(id: string, decision: "approve" | "reject", force = false) {
    setBusy(id); setMsg("");
    try {
      const r = await api.decideTool(id, decision, force);
      list.reload();
      if (r.status === "approved") void showIdeas(r.tool_id);   // a new system: offer agents that use it
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(null); }
  }
  async function test(id: string) {
    setBusy(id); setMsg("");
    try { await api.testTool(id); list.reload(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(null); }
  }

  return (
    <>
      <Topbar title={<>{t("tools.title")}<small className="tech">{t("tech.tools")}</small></>} subtitle={t("tools.intro")}>
        <button className="btn" disabled={looking} onClick={discover} title={t("tools.discoverHint")}>{looking ? t("tools.discovering") : t("tools.discover")}</button>
        {!mcpOpen && <button className="btn" onClick={() => setMcpOpen(true)}>{t("mcps.open")}<small className="tech">MCP</small></button>}
        {!open && <button className="btn primary" onClick={() => { setStart(""); setOpen(true); }}>{t("tools.connect")}</button>}
      </Topbar>
      {found && (
        <section className="card discover" style={{ marginBottom: 24 }}>
          <h2>{t("tools.discovered")}</h2>
          <p className="help">{t("tools.discoverHow")}</p>
          {found.length === 0 && <Empty title={t("tools.discoverNoneTitle")} text={t("tools.discoverNoneText")} />}
          <div className="list">
            {found.map((d) => (
              <div className="row" key={d.address}>
                <span className="chip"><Icon name={d.found ? "catalog" : "database"} /></span>
                <span className="txt">
                  <b>{d.found ? d.title : d.address}</b>
                  <small>{d.found ? `${d.address} · ${t("tools.reads", { n: d.reads })} · ${t("tools.changes", { n: d.changes })}` : d.detail}</small>
                </span>
                {d.found && (d.connected?.length
                  ? <span className="badge ok">{t("tools.alreadyConnected", { id: d.connected.join(", ") })}</span>
                  : <button className="btn primary" onClick={() => { setStart(d.address); setOpen(true); }}>{t("tools.makeTool")}</button>)}
                {!d.found && <span className="badge">{t("tools.noContract")}</span>}
              </div>
            ))}
          </div>
        </section>
      )}
      <McpServers canConnect={!!list.data?.can_approve} open={mcpOpen} onClose={() => setMcpOpen(false)} />
      {open && <Connect key={start + (changing?.id ?? "")} start={start} need={need} updateOf={changing?.id} keepName={changing?.name} preselect={changing?.ops}
        onDone={() => { setOpen(false); setChanging(null); list.reload(); }} back={back} />}
      {msg && <p className="notice err" role="alert">{msg}</p>}
      {list.loading && <Loading />}
      {list.error && <Failed message={list.error} retry={list.reload} />}
      {list.data && (
        <>
          {list.data.requests.length > 0 && (
            <section className="card" style={{ marginBottom: 24 }}>
              <h2>{t("tools.requests")}</h2>
              <div className="list">
                {list.data.requests.map((r) => (
                  <div className="row" key={r.id}>
                    <span className="chip"><Icon name="tools" /></span>
                    <span className="txt">
                      <b>{r.spec.name}</b>
                      <small>{(r.spec as { kind?: string }).kind === "code" ? t("code.writtenByAi") : r.spec.base_url} · {r.spec.operations.length} {t("tools.operations")} · {r.spec.requested_by}{r.spec.update_of ? ` · ${t("tools.newVersionOf", { id: r.spec.update_of })}` : ""}</small>
                      {(r.spec as { kind?: string }).kind === "code" && <CodeReview r={r} onChange={list.reload} />}
                      {r.spec.test && r.status === "draft" && (
                        <span className={`test-line ${r.spec.test.passed ? "ok" : "err"}`}>
                          {r.spec.test.passed ? t("tools.testPassed") : t("tools.testFailed")}: {r.spec.test.results.map((x) => `${x.summary} — ${x.detail}`).join(" · ")}
                        </span>
                      )}
                    </span>
                    <span className="meta">{when(r.updated_at, i18n.language)}</span>
                    <span className={`badge ${r.status === "approved" ? "ok" : r.status === "rejected" ? "err" : "warn"}`}>{t(`tools.status.${r.status}`)}</span>
                    {r.status === "draft" && (
                      <button className="btn" disabled={busy !== null} onClick={() => test(r.id)}>{busy === r.id ? t("tools.testing") : t("tools.test")}</button>
                    )}
                    {list.data!.can_approve && r.status === "draft" && (
                      <>
                        <button className="btn primary" disabled={busy !== null || !r.spec.test?.passed} title={r.spec.test?.passed ? undefined : t("tools.testFirst")}
                          onClick={() => decide(r.id, "approve")}>{t("appr.approve")}</button>
                        {!r.spec.test?.passed && <button className="btn ghost" disabled={busy !== null} onClick={() => decide(r.id, "approve", true)}>{t("tools.approveAnyway")}</button>}
                        <button className="btn ghost" disabled={busy !== null} onClick={() => decide(r.id, "reject")}>{t("appr.reject")}</button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
          <Libraries canInstall={list.data.can_approve} />
          <section className="card">
            <h2>{t("tools.connected")}</h2>
            {list.data.connected.length === 0 && <Empty title={t("tools.noneTitle")} text={t("tools.noneText")} />}
            <div className="sys-grid">
              {list.data.connected.map((c) => (
                <article className="sys-tile" key={c.id}>
                  <header>
                    <span className="chip"><Icon name="database" /></span>
                    <b dir="auto" title={c.name}>{c.name}</b>
                    {c.test_system && <span className="badge">{t("create2.testSystem")}</span>}
                    <button className="btn ghost sys-ideas" onClick={() => showIdeas(c.id)} aria-expanded={ideas?.tool === c.id}>{t("tools.ideas")}</button>
                    {c.managed && <button className="btn ghost sys-ideas" disabled={busy === c.id} title={t("tools.changeHint")}
                      onClick={() => c.kind === "code" ? void changeCode(c)
                        : (setChanging({ id: c.id, name: c.name, ops: [...c.reads, ...c.changes] }), setStart(c.base_url || ""), setOpen(true))}>
                      {busy === c.id ? t("code.writing") : t("tools.change")}</button>}
                    {c.managed && list.data!.can_approve && <button className="icon-btn danger" title={t("tools.remove")} aria-label={`${t("tools.remove")} ${c.name}`} onClick={() => remove(c)}><Trash2 size={16} /></button>}
                  </header>
                  <small>{c.kind === "code" ? `${t("code.writtenByAi")} · ` : ""}{c.built_in ? t("tools.builtIn") : `${t("tools.reads", { n: c.reads.length })} · ${t("tools.changes", { n: c.changes.length })}`}{c.version ? ` · v${c.version}` : ""}{c.risk_level ? ` · ${t(`code.risk.${c.risk_level}`)}` : ""}</small>
                  <small dir="auto">{c.used_by.length ? t("tools.usedBy", { list: c.used_by.map((a) => a.name).join(", ") }) : t("tools.unused")}</small>
                  {c.sign_in && <SignIn tool={c.id} state={c.sign_in} onSaved={list.reload} />}
                  {ideas?.tool === c.id && (
                    <div className="ideas">
                      <p className="help">{ideas.list.length ? t("tools.ideasLead", { name: c.name }) : t("tools.noIdeas")}</p>
                      {ideas.list.map((x) => (
                        <Link key={x.text} className="idea" to={`/create?idea=${encodeURIComponent(x.text)}`}>
                          <span dir="auto">{x.text}</span><b>{t("tools.useIdea")}</b>
                        </Link>
                      ))}
                    </div>
                  )}
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </>
  );
}

function Connect({ need, onDone, back, start = "", updateOf, keepName, preselect }: { need: string; onDone: () => void; back: string | null; start?: string;
  updateOf?: string; keepName?: string; preselect?: string[] }) {
  const { t } = useTranslation();
  const [address, setAddress] = useState(start);
  const [what, setWhat] = useState(need);
  const [learned, setLearned] = useState<Learned | null>(null);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [signIn, setSignIn] = useState<"none" | "ad_login" | "token">("none");
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [trust, setTrust] = useState(false);
  const [signCheck, setSignCheck] = useState<{ ok: boolean; detail: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  useEffect(() => { if (start) void read(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  async function read(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true); setError("");
    try {
      const l = await api.learnTool(address, what, trust);
      setLearned(l);
      setName(l.title);
      setPurpose(l.description.slice(0, 300));
      setPicked(Object.fromEntries(l.operations.map((o) => [o.id, preselect ? preselect.includes(o.id) : o.matches_need])));
      if (keepName) setName(keepName);
      if (l.sign_in) setSignIn("ad_login");   // the system signs people in: ask for a user id and password here
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  async function trySign() {
    if (!learned) return;
    setBusy(true); setError(""); setSignCheck(null);
    try { setSignCheck(await api.trySignIn({ base_url: learned.base_url, login_path: learned.sign_in?.login_path || "", account, password, trust_cert: trust })); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  async function request() {
    if (!learned) return;
    setBusy(true); setError("");
    try {
      await api.requestTool({ name, purpose, base_url: learned.base_url, contract_url: learned.contract_url, sign_in: signIn, account,
        password: signIn === "ad_login" ? password : "", login_path: learned.sign_in?.login_path || "", trust_cert: trust,
        operations: learned.operations.filter((o) => picked[o.id]), ...(updateOf ? { update_of: updateOf } : {}) });
      setSent(true);
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  if (sent) {
    return (
      <section className="card inner" role="status" style={{ marginBottom: 24 }}>
        <h2>{t("tools.sentTitle")}</h2>
        <p>{t("tools.sentText")}</p>
        <div className="actions start">
          {back && <Link className="btn primary" to={`/create/${back}`}>{t("tools.backToAgent")}</Link>}
          <button className="btn" onClick={onDone}>{t("tools.close")}</button>
        </div>
      </section>
    );
  }

  const group = (kind: LearnedOp["kind"]) => learned!.operations.filter((o) => o.kind === kind);
  const count = learned ? learned.operations.filter((o) => picked[o.id]).length : 0;
  return (
    <section className="card inner connect" style={{ marginBottom: 24 }}>
      <h2>{t("tools.connectTitle")}</h2>
      <form onSubmit={read} className="grid cols-2">
        <div className="field">
          <label htmlFor="addr">{t("tools.address")}</label>
          <input id="addr" className="input" placeholder="http://server:8000" value={address} onChange={(e) => setAddress(e.target.value)} />
          <small className="help">{t("tools.addressHint")}</small>
          {(address.startsWith("https") || trust) && (
            <label className="toggle"><input type="checkbox" checked={trust} onChange={(e) => setTrust(e.target.checked)} /> {t("tools.trustCert")}</label>
          )}
        </div>
        <div className="field">
          <label htmlFor="need">{t("tools.need")}</label>
          <input id="need" className="input" value={what} onChange={(e) => setWhat(e.target.value)} />
        </div>
        <div className="actions start"><button className="btn primary" disabled={busy || address.length < 8}>{busy && !learned ? t("tools.reading") : t("tools.read")}</button></div>
      </form>
      {error && <p className="notice err" role="alert">{error}</p>}
      {learned && (
        <>
          {learned.existing.length > 0 && (
            <p className="notice warn">{t("tools.existing", { list: learned.existing.map((x) => x.id).join(", ") })}</p>
          )}
          <p className="help">{t("tools.found", { title: learned.title, n: learned.operations.length })}</p>
          {(["read", "change"] as const).map((kind) => group(kind).length > 0 && (
            <fieldset key={kind}>
              <legend>{t(kind === "read" ? "tools.readOps" : "tools.changeOps")}</legend>
              <div className="caps">
                {group(kind).map((o) => (
                  <label key={o.id} className={`cap ${picked[o.id] ? "on" : ""}`}>
                    <input type="checkbox" checked={!!picked[o.id]} onChange={() => setPicked({ ...picked, [o.id]: !picked[o.id] })} />
                    <span><b>{o.summary}</b><small>{o.method} {o.path}</small></span>
                    {kind === "change" && <em className="badge warn">{t("create2.changes")}</em>}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
          <div className="grid cols-2">
            <div className="field"><label htmlFor="tname">{t("tools.name")}</label>
              <input id="tname" className="input" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} /></div>
            <div className="field"><label htmlFor="tpurpose">{t("tools.purpose")}</label>
              <input id="tpurpose" className="input" value={purpose} maxLength={400} onChange={(e) => setPurpose(e.target.value)} /></div>
          </div>
          <fieldset><legend>{t("tools.signIn")}</legend>
            <div className="row-inline">
              {(["none", "ad_login", "token"] as const).map((s) => (
                <label key={s} className="radio"><input type="radio" name="signin" checked={signIn === s} onChange={() => setSignIn(s)} /> {t(`tools.signin.${s}`)}</label>
              ))}
            </div>
            {signIn === "ad_login" && (
              <div className="signin-row">
                <input className="input" placeholder={t("tools.account")} aria-label={t("tools.account")} autoComplete="off" dir="ltr"
                  value={account} onChange={(e) => { setAccount(e.target.value); setSignCheck(null); }} />
                <input className="input" type="password" placeholder={t("tools.password")} aria-label={t("tools.password")} autoComplete="new-password"
                  value={password} onChange={(e) => { setPassword(e.target.value); setSignCheck(null); }} />
                <button type="button" className="btn" disabled={busy || !account || !password} onClick={trySign}>{t("tools.trySignIn")}</button>
              </div>
            )}
            {signCheck && <span className={`test-line ${signCheck.ok ? "ok" : "err"}`} role="status">{signCheck.ok ? t("tools.signOk", { detail: signCheck.detail }) : t("tools.signBad", { detail: signCheck.detail })}</span>}
            {signIn === "ad_login" && <small className="help">{t("tools.passwordHint")}</small>}
            {signIn === "token" && <small className="help">{t("tools.secretHint")}</small>}
          </fieldset>
          <div className="actions start">
            <button className="btn primary" disabled={busy || !count || name.length < 2 || (signIn === "ad_login" && !signCheck?.ok)} onClick={request}>{t("tools.request", { n: count })}</button>
          </div>
        </>
      )}
    </section>
  );
}


/** A connected system's saved sign-in: who Agent Studio signs in as, a check that it still works, and updating it. */
function SignIn({ tool, state, onSaved }: { tool: string; state: { account: string; saved: boolean }; onSaved: () => void }) {
  const { t } = useTranslation();
  const [check, setCheck] = useState<{ ok: boolean; detail: string } | null>(null);
  const [edit, setEdit] = useState(!state.saved);
  const [account, setAccount] = useState(state.account);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run(fn: () => Promise<void>) {
    setBusy(true); setErr("");
    try { await fn(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  const status = !state.saved ? "warn" : check ? (check.ok ? "ok" : "err") : "";
  return (
    <div className="signin-box">
      <span className={`badge ${status}`}>
        {!state.saved ? t("tools.signMissing") : check ? (check.ok ? t("tools.signWorks") : t("tools.signBroken")) : t("tools.signSaved", { account: state.account })}
      </span>
      {state.saved && !edit && (
        <>
          <button className="btn ghost" disabled={busy} onClick={() => run(async () => setCheck(await api.checkSignIn(tool)))}>{busy ? t("tools.checking") : t("tools.checkSignIn")}</button>
          <button className="btn ghost" onClick={() => setEdit(true)}>{t("tools.updatePassword")}</button>
        </>
      )}
      {check && !check.ok && <small className="help err">{t("tools.signBrokenHint", { detail: check.detail })}</small>}
      {edit && (
        <div className="signin-row">
          <input className="input" dir="ltr" autoComplete="off" aria-label={t("tools.account")} placeholder={t("tools.account")} value={account} onChange={(e) => setAccount(e.target.value)} />
          <input className="input" type="password" autoComplete="new-password" aria-label={t("tools.password")} placeholder={t("tools.password")} value={password} onChange={(e) => setPassword(e.target.value)} />
          <button className="btn primary" disabled={busy || !account || !password}
            onClick={() => run(async () => { const r = await api.saveSignIn(tool, account, password); setCheck(r); setPassword(""); setEdit(false); onSaved(); })}>
            {busy ? t("tools.checking") : t("tools.saveSignIn")}</button>
          {state.saved && <button className="btn ghost" onClick={() => setEdit(false)}>{t("mcps.cancel")}</button>}
        </div>
      )}
      {err && <small className="help err" role="alert">{err}</small>}
    </div>
  );
}
