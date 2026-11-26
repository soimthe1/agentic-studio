// The product's name and look come from ONE brand.json (branding/brand.local, else branding/brand.example), served
// by the API - never from code. Texts use {{brand}} / {{tagline}}.
import i18n from "i18next";
import builtInLogo from "./assets/logo.svg";

type Brand = { name: string; name_ar: string; tagline: string; tagline_ar: string; title: string; custom_logo: boolean; favicon?: boolean; theme?: boolean };
let current: Brand = { name: "Agentic Studio", name_ar: "", tagline: "AI agents in plain words", tagline_ar: "", title: "Agentic Studio", custom_logo: false };
const API = "/api/studio/v1/brand";

export const logoUrl = () => (current.custom_logo ? `${API}/logo` : builtInLogo);

function apply(lang: string) {
  const ar = lang === "ar";
  i18n.options.interpolation = {
    ...i18n.options.interpolation,
    defaultVariables: { brand: (ar && current.name_ar) || current.name, tagline: (ar && current.tagline_ar) || current.tagline },
  };
}

/** Load once before the first screen. */
export async function loadBrand(): Promise<void> {
  try {
    const r = await fetch(API);
    if (r.ok) current = await r.json();
  } catch { /* the built-in name is used */ }
  document.title = current.title;
  const icon = document.querySelector<HTMLLinkElement>("link[rel~='icon']") ?? document.head.appendChild(Object.assign(document.createElement("link"), { rel: "icon" }));
  icon.href = current.favicon ? `${API}/favicon` : logoUrl();
  if (current.theme) document.head.appendChild(Object.assign(document.createElement("link"), { rel: "stylesheet", href: `${API}/theme` }));
  apply(i18n.language);
  i18n.on("languageChanged", apply);
}
