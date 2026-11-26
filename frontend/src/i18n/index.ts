import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import ar from "./ar.json";
import en from "./en.json";

function saved(): string | null {
  try {
    return localStorage.getItem("agent_studio.lang");
  } catch {
    return null;
  }
}

i18n.use(initReactI18next).init({
  resources: { en: { t: en }, ar: { t: ar } },
  ns: ["t"],
  defaultNS: "t",
  lng: saved() || "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export function applyDirection(lang: string) {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
}

applyDirection(i18n.language);
i18n.on("languageChanged", (l) => {
  applyDirection(l);
  try {
    localStorage.setItem("agent_studio.lang", l);
  } catch {
    /* private mode: language just isn't remembered */
  }
});

export default i18n;
