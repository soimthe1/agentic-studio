import { ChevronDown, LogOut, Moon, Search, Sparkles, Sun, Wrench } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { getNeon, getTheme, setNeon, setTheme, type Theme, useMe } from "../App";

/** The house standard top row: the page's own title and purpose, its actions, then search, theme, language, user. */
export function Topbar({ title, subtitle, children }: { title: ReactNode; subtitle?: ReactNode; children?: ReactNode }) {
  const { t, i18n } = useTranslation();
  const nav = useNavigate();
  const [theme, setLocalTheme] = useState<Theme>(getTheme());
  const [q, setQ] = useState("");

  function changeTheme(value: Theme) {
    setTheme(value);
    setLocalTheme(value);
  }

  return (
    <header className="topbar">
      <div className="page-head">
        <h1>{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {children && <div className="page-actions">{children}</div>}
      <div className="topbar-spacer" />
      <form className="search" role="search" onSubmit={(e) => { e.preventDefault(); nav(`/agents?q=${encodeURIComponent(q.trim())}`); }}>
        <Search size={15} aria-hidden="true" />
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("top.search")} aria-label={t("top.search")} />
      </form>
      <div className="segmented" role="group" aria-label={t("top.theme")}>
        {([["light", Sun], ["dark", Moon]] as const).map(([value, Ico]) => (
          <button key={value} type="button" className={theme === value ? "is-active" : ""} aria-pressed={theme === value}
            title={t(`settings.${value}`)} onClick={() => changeTheme(value)}>
            <Ico size={14} aria-hidden="true" /><span className="seg-label">{t(`settings.${value}`)}</span>
          </button>
        ))}
      </div>
      <button type="button" className="lang-toggle" aria-label={t("settings.language")} title={t("settings.language")}
        onClick={() => i18n.changeLanguage(i18n.language === "ar" ? "en" : "ar")}>
        <span className={i18n.language !== "ar" ? "is-current" : ""}>EN</span>
        <span aria-hidden="true">/</span>
        <span className={i18n.language === "ar" ? "is-current" : ""} lang="ar">عربي</span>
      </button>
      <UserMenu />
    </header>
  );
}

function UserMenu() {
  const { t } = useTranslation();
  const me = useMe();
  const [open, setOpen] = useState(false);
  const [neon, setLocalNeon] = useState(getNeon());
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onMouse = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onMouse);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onMouse); document.removeEventListener("keydown", onKey); };
  }, [open]);

  if (!me) return null;
  const parts = me.username.split(/[\s._-]+/).filter(Boolean);
  const initials = (parts.length > 1 ? parts.slice(0, 2).map((p) => p[0]) : [...(parts[0] || "?").slice(0, 2)]).join("").toUpperCase();
  return (
    <div className="user-menu" ref={ref}>
      <button type="button" className="user-menu-button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="avatar" aria-hidden="true">{initials}</span>
        <span className="user-menu-name">{me.username}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className="user-menu-panel" role="menu">
          <div className="user-menu-head">
            <span className="avatar avatar-lg" aria-hidden="true">{initials}</span>
            <div><b>{me.username}</b><small>{t(`top.role.${me.role}`)}</small></div>
          </div>
          <button type="button" role="menuitemcheckbox" aria-checked={neon} className="menu-item neon-toggle"
            onClick={() => { setNeon(!neon); setLocalNeon(!neon); }}>
            <Sparkles size={15} aria-hidden="true" /> <span>{t("top.neon")}<small>{t("top.neonHint")}</small></span>
            <span className={`switch${neon ? " on" : ""}`} aria-hidden="true" />
          </button>
          {me.engine_console_url && (
            <a role="menuitem" className="menu-item" href={me.engine_console_url} target="_blank" rel="noopener">
              <Wrench size={15} aria-hidden="true" /> <span>{t("engineConsole")}<small>{t("engineConsoleHint")}</small></span>
            </a>
          )}
          <a role="menuitem" className="menu-item signout" href="/auth/logout"><LogOut size={15} aria-hidden="true" /> {t("signOut")}</a>
        </div>
      )}
    </div>
  );
}
