// Settings cards for administrators: the model servers agents use, and (local accounts) the people who may sign in.
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Account, type ModelProfile, type ModelsView } from "../api";

const EXAMPLES: Record<ModelProfile["provider"], string> = {
  ollama: "http://host.docker.internal:11434",
  openai: "http://your-server:8000/v1",
};

function ProfileFields({ id, value, onChange, models }: { id: string; value: ModelProfile; onChange: (p: ModelProfile) => void; models: string[] }) {
  const { t } = useTranslation();
  return (
    <div className="setup-grid">
      <div className="field">
        <label htmlFor={`${id}-kind`}>{t("setup.kind")}</label>
        <select id={`${id}-kind`} className="input" value={value.provider} onChange={(e) => onChange({ ...value, provider: e.target.value as ModelProfile["provider"] })}>
          <option value="ollama">Ollama</option>
          <option value="openai">{t("setup.openai")}</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${id}-url`}>{t("setup.address")}</label>
        <input id={`${id}-url`} className="input" value={value.base_url} placeholder={EXAMPLES[value.provider]} onChange={(e) => onChange({ ...value, base_url: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-model`}>{t("setup.model")}</label>
        <input id={`${id}-model`} className="input" list={`${id}-models`} value={value.model} onChange={(e) => onChange({ ...value, model: e.target.value })} />
        <datalist id={`${id}-models`}>{models.map((m) => <option key={m} value={m} />)}</datalist>
      </div>
      {value.provider === "openai" && (
        <div className="field">
          <label htmlFor={`${id}-key`}>{t("setup.key")}</label>
          <input id={`${id}-key`} className="input" type="password" autoComplete="off" value={value.api_key ?? ""}
            placeholder={value.has_key ? t("setup.keySaved") : t("setup.keyNone")} onChange={(e) => onChange({ ...value, api_key: e.target.value })} />
        </div>
      )}
    </div>
  );
}

export function ModelsCard() {
  const { t } = useTranslation();
  const [view, setView] = useState<ModelsView | null>(null);
  const [main, setMain] = useState<ModelProfile | null>(null);
  const [deep, setDeep] = useState<ModelProfile | null>(null);
  const [separate, setSeparate] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.models().then((v) => {
      setView(v);
      setMain({ ...v.default, api_key: null });
      setDeep({ ...v.reasoning, api_key: null });
      setSeparate(v.reasoning.base_url !== v.default.base_url || v.reasoning.model !== v.default.model);
    }).catch((e) => setMsg({ tone: "err", text: String(e.message) }));
  }, []);
  if (!main || !deep) return <div className="card"><h2>{t("setup.title")}</h2>{msg && <div className="notice err"><p>{msg.text}</p></div>}</div>;

  const clean = (p: ModelProfile): ModelProfile => ({ provider: p.provider, base_url: p.base_url.trim(), model: p.model.trim(), api_key: p.api_key ? p.api_key : null });
  const test = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.testModel(clean(main));
      setModels(r.models ?? []);
      setMsg(r.ok ? { tone: "ok", text: t("setup.works") } : { tone: "err", text: r.error ?? t("setup.noModel") });
    } catch (e) { setMsg({ tone: "err", text: String((e as Error).message) }); }
    setBusy(false);
  };
  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const v = await api.saveModels({ default: clean(main), reasoning: separate ? clean(deep) : null });
      setView(v);
      setMsg({ tone: v.engine ? "err" : "ok", text: v.engine ? `${t("setup.saved")} ${v.engine}` : t("setup.saved") });
    } catch (e) { setMsg({ tone: "err", text: String((e as Error).message) }); }
    setBusy(false);
  };

  return (
    <div className="card">
      <h2>{t("setup.title")}</h2>
      {view?.needs_setup && <div className="notice warn"><p>{t("setup.needed")}</p></div>}
      <p>{t("setup.hint")}</p>
      <ProfileFields id="main" value={main} onChange={setMain} models={models} />
      <label className="row-inline"><input type="checkbox" checked={separate} onChange={(e) => setSeparate(e.target.checked)} /> {t("setup.separate")}</label>
      {separate && <ProfileFields id="deep" value={deep} onChange={setDeep} models={models} />}
      {msg && <div className={`notice ${msg.tone}`}><p>{msg.text}</p></div>}
      <div className="row-inline">
        <button className="btn" disabled={busy} onClick={test}>{t("setup.test")}</button>
        <button className="btn primary" disabled={busy || !main.base_url || !main.model} onClick={save}>{t("setup.save")}</button>
      </div>
    </div>
  );
}

export function PeopleCard({ me }: { me: string }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<Account[]>([]);
  const [form, setForm] = useState({ username: "", name: "", password: "", role: "user" });
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const load = () => api.accounts().then(setRows).catch((e) => setMsg({ tone: "err", text: String(e.message) }));
  useEffect(() => { load(); }, []);
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); setMsg({ tone: "ok", text: ok }); await load(); } catch (e) { setMsg({ tone: "err", text: String((e as Error).message) }); }
  };

  return (
    <div className="card">
      <h2>{t("people.title")}</h2>
      <p>{t("people.hint")}</p>
      <table className="activity">
        <thead><tr><th>{t("people.username")}</th><th>{t("people.role")}</th><th /></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.username}>
              <td>{r.username}{r.name && ` · ${r.name}`}</td>
              <td>
                <select className="input" value={r.role} aria-label={t("people.role")}
                  onChange={(e) => act(() => api.changeAccount(r.username, { role: e.target.value }), t("people.changed"))}>
                  {(["user", "builder", "admin"] as const).map((x) => <option key={x} value={x}>{t(`people.${x}`)}</option>)}
                </select>
              </td>
              <td className="row-inline">
                <button className="btn ghost" onClick={() => {
                  const pw = window.prompt(t("people.newPassword", { user: r.username }));
                  if (pw) act(() => api.changeAccount(r.username, { password: pw }), t("people.changed"));
                }}>{t("people.reset")}</button>
                {r.username !== me && <button className="btn ghost" onClick={() => {
                  if (window.confirm(t("people.confirmRemove", { user: r.username }))) act(() => api.removeAccount(r.username), t("people.removed"));
                }}>{t("people.remove")}</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>{t("people.add")}</h3>
      <div className="row-inline">
        <input className="input" aria-label={t("people.username")} placeholder={t("people.username")} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
        <input className="input" aria-label={t("people.name")} placeholder={t("people.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </div>
      <div className="row-inline">
        <input className="input" type="password" autoComplete="new-password" aria-label={t("people.password")} placeholder={t("people.password")} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <select className="input" aria-label={t("people.role")} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
          {(["user", "builder", "admin"] as const).map((x) => <option key={x} value={x}>{t(`people.${x}`)}</option>)}
        </select>
        <button className="btn primary" disabled={!form.username || !form.password}
          onClick={() => act(async () => { await api.addAccount(form); setForm({ username: "", name: "", password: "", role: "user" }); }, t("people.added"))}>{t("people.add")}</button>
      </div>
      {msg && <div className={`notice ${msg.tone}`}><p>{msg.text}</p></div>}
    </div>
  );
}

export function PasswordForm() {
  const { t } = useTranslation();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  return (
    <>
      <div className="row-inline">
        <input className="input" type="password" autoComplete="current-password" aria-label={t("people.current")} placeholder={t("people.current")} value={cur} onChange={(e) => setCur(e.target.value)} />
        <input className="input" type="password" autoComplete="new-password" aria-label={t("people.password")} placeholder={t("people.password")} value={next} onChange={(e) => setNext(e.target.value)} />
        <button className="btn" disabled={!cur || !next} onClick={async () => {
          setMsg(null);
          try { await api.myPassword(cur, next); setCur(""); setNext(""); setMsg({ tone: "ok", text: t("people.changed") }); }
          catch (e) { setMsg({ tone: "err", text: String((e as Error).message) }); }
        }}>{t("people.change")}</button>
      </div>
      {msg && <div className={`notice ${msg.tone}`}><p>{msg.text}</p></div>}
    </>
  );
}
