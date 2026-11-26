import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/600.css";
import "@fontsource/ibm-plex-sans-arabic/700.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./i18n";
import "./styles.css";
import { loadBrand } from "./brand";

// Shown inside another app's window (the chat app): compact layout, no sidebar. ?embed=1 forces it for testing.
try {
  if (window.self !== window.top || new URLSearchParams(location.search).has("embed")) document.documentElement.dataset.embedded = "1";
} catch {
  document.documentElement.dataset.embedded = "1";   // a cross-origin parent: we are certainly framed
}

loadBrand().then(() => createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
));
