import { useTranslation } from "react-i18next";
import { getTheme, setTheme, type Theme, useMe } from "../App";
import { Topbar } from "../components/Topbar";
import { ModelsCard, PasswordForm, PeopleCard } from "../components/SetupCards";

export function Settings({ onChange }: { onChange: () => void }) {
  const { t, i18n } = useTranslation();
  const me = useMe();
  const theme = getTheme();

  return (
    <>
      <Topbar title={<>{t("settings.title")}</>} subtitle={t("top.sub.settings")} />
      <section className="grid cols-2">
        <div className="card">
          <h2>{t("settings.language")}</h2>
          <div className="field">
            <label htmlFor="lang">{t("settings.language")}</label>
            <select id="lang" className="input" value={i18n.language} onChange={(e) => i18n.changeLanguage(e.target.value)}>
              <option value="en">English</option>
              <option value="ar">العربية</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="theme">{t("settings.theme")}</label>
            <select id="theme" className="input" value={theme} onChange={(e) => { setTheme(e.target.value as Theme); onChange(); }}>
              <option value="dark">{t("settings.dark")}</option>
              <option value="light">{t("settings.light")}</option>
            </select>
          </div>
        </div>
        <div className="card">
          <h2>{t("settings.account")}</h2>
          <p>{t("settings.signedInAs", { user: me?.username })}</p>
          {me?.local_accounts && <PasswordForm />}
          <a className="btn" href="/auth/logout">{t("signOut")}</a>
        </div>
        {me?.role === "admin" && <ModelsCard />}
        {me?.role === "admin" && me.local_accounts && <PeopleCard me={me.username} />}
      </section>
    </>
  );
}
