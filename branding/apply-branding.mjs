// Applies branding/ to an upstream Langflow frontend checkout before `vite build`.
// Usage: node apply-branding.mjs <branding-dir> <frontend-dir> <fonts-dir>
// Touches only: src/assets/LangflowLogo.svg, src/customization/components/{custom-login-brand-title,branding/seams/*}.tsx,
// src/locales/en.json, index.html, public/manifest.json (+ adds public/brand/). See docs/patches.md.
import fs from "node:fs";
import path from "node:path";

const [brandDir, fe, fontsDir] = process.argv.slice(2);
const p = (...a) => path.join(fe, ...a);
// The single brand source: brand.local/ (the organisation's own, git-ignored) wins over brand.example/ (public).
const own = fs.existsSync(path.join(brandDir, "brand.local", "brand.json")) ? "brand.local" : "brand.example";
const brandFiles = path.join(brandDir, own);
const brand = JSON.parse(fs.readFileSync(path.join(brandFiles, "brand.json"), "utf8"));
console.log(`branding: ${own} (${brand.name})`);
const CSP = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; media-src 'self' blob: data:; form-action 'self'; base-uri 'self'; object-src 'none'";
const sub = (s) => s.replaceAll("{{BRAND}}", brand.name);

// 1. Logo: every upstream usage imports this one file.
fs.copyFileSync(path.join(brandFiles, brand.logo || "logo.svg"), p("src/assets/LangflowLogo.svg"));

// 2. Login brand title (upstream customization seam).
fs.writeFileSync(p("src/customization/components/custom-login-brand-title.tsx"),
  `export default function CustomLoginBrandTitle() {\n  return <>${brand.name}</>;\n}\n`);

// 2b. Other upstream customization seams (files named exactly like the upstream seam they replace).
for (const f of fs.readdirSync(path.join(brandDir, "seams"))) {
  const target = p("src/customization/components", f);
  if (!fs.existsSync(target)) throw new Error(`seam not found upstream: ${f}`);
  fs.copyFileSync(path.join(brandDir, "seams", f), target);
}

// 3. Visible English strings that name the product.
const enPath = p("src/locales/en.json");
const en = JSON.parse(fs.readFileSync(enPath, "utf8"));
const overrides = JSON.parse(sub(fs.readFileSync(path.join(brandDir, "locale-overrides.en.json"), "utf8")));
for (const k of Object.keys(overrides)) {
  if (!(k in en)) throw new Error(`locale key not found upstream: ${k}`);
  en[k] = overrides[k];
}
fs.writeFileSync(enPath, JSON.stringify(en, null, 2) + "\n");

// 3b. No user-visible "Langflow": every locale file, plus the few source files with hard-coded UI text.
//     Minimum counts make an upgrade that moves these strings fail the build instead of leaking the name.
const WORD = /\bLangflow\b/g;
const TEXT_FILES = {
  "src/constants/constants.ts": 7,
  "src/components/core/assistantPanel/assistant-panel.constants.ts": 2,
  "src/components/core/canvasControlsComponent/CanvasControls.tsx": 1,
  "src/hooks/use-document-title.ts": 1,
  "src/utils/buildUtils.ts": 1,
  "src/customization/utils/custom-poll-build-events.ts": 1,
  "src/constants/dbProviderConstants.ts": 1,
  "src/pages/MainPage/pages/knowledgePage/utils/backendMetadata.ts": 1,
};
for (const f of fs.readdirSync(p("src/locales")).filter((n) => n.endsWith(".json"))) TEXT_FILES[`src/locales/${f}`] = 1;
for (const [rel, min] of Object.entries(TEXT_FILES)) {
  const src = fs.readFileSync(p(rel), "utf8");
  const n = (src.match(WORD) || []).length;
  if (n < min) throw new Error(`${rel}: expected >= ${min} "Langflow" strings, found ${n} (upstream moved them?)`);
  fs.writeFileSync(p(rel), src.replace(WORD, brand.name));
}
// Documentation links point at Agent Studio itself (docs.langflow.org is external and unreachable offline).
const cc = p("src/customization/config-constants.ts");
const ccSrc = fs.readFileSync(cc, "utf8");
if (!ccSrc.includes('DOCS_LINK = "https://docs.langflow.org"')) throw new Error("DOCS_LINK not found upstream");
fs.writeFileSync(cc, ccSrc.replace('DOCS_LINK = "https://docs.langflow.org"', 'DOCS_LINK = "/studio/"'));

// 4. Static brand files + self-hosted fonts.
const out = p("public/brand");
fs.mkdirSync(out, { recursive: true });
for (const f of fs.readdirSync(brandFiles)) {
  if (/\.(svg|png|ico|css)$/i.test(f)) fs.copyFileSync(path.join(brandFiles, f), path.join(out, f));
}
fs.cpSync(fontsDir, path.join(out, "fonts"), { recursive: true });
if (!brand.theme) fs.writeFileSync(path.join(out, "theme.css"), "/* no brand theme: built-in look */\n");
else if (brand.theme !== "theme.css") fs.copyFileSync(path.join(brandFiles, brand.theme), path.join(out, "theme.css"));
const favicon = brand.favicon || brand.logo || "logo.svg";

// 5. index.html: title, no Google Fonts, local fonts + theme, favicon.
let html = fs.readFileSync(p("index.html"), "utf8");
const before = html;
html = html.replace(/\s*<link rel="preconnect" href="https:\/\/fonts\.g[^>]*>/g, "");
html = html.replace(/\s*<link\s+href="https:\/\/fonts\.googleapis\.com[^>]*\/>/s, "");
html = html.replace(/<title>.*?<\/title>/, `<title>${brand.name}${brand.name_ar ? " - " + brand.name_ar : ""}</title>`);  // tab: English - Arabic
html = html.replace(/<link rel="icon"[^>]*>/, `<link rel="icon" href="./brand/${favicon}" />`);
// Browser-side air gap: the page may only load from / talk to its own origin.
html = html.replace("<head>", `<head>
    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`);
html = html.replace("</head>", `  <link rel="stylesheet" href="./brand/fonts/fonts.css" />\n    <link rel="stylesheet" href="./brand/theme.css" />\n  </head>`);
if (html === before || html.includes("googleapis") || !html.includes("brand/theme.css") || !html.includes("Content-Security-Policy")) throw new Error("index.html patch did not apply cleanly");
fs.writeFileSync(p("index.html"), html);

// 6. PWA manifest.
const man = JSON.parse(fs.readFileSync(p("public/manifest.json"), "utf8"));
Object.assign(man, { name: `${brand.name} ${brand.tagline}`, short_name: brand.name, description: `${brand.name} ${brand.tagline}`,
  icons: [{ src: `brand/${favicon}`, sizes: "any" }] });
fs.writeFileSync(p("public/manifest.json"), JSON.stringify(man, null, 2) + "\n");
console.log(`branding applied: ${brand.name}`);
