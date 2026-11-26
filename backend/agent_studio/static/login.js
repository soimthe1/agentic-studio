// Password reveal toggle + submit loading state for the sign-in page.
const pw = document.getElementById("password");
const reveal = document.querySelector(".reveal");
reveal.addEventListener("click", () => {
  const show = pw.type === "password";
  pw.type = show ? "text" : "password";
  pw.toggleAttribute("data-revealed", show);
  reveal.textContent = show ? "Hide" : "Show";
  reveal.setAttribute("aria-pressed", String(show));
  pw.focus();
});
document.querySelector("form").addEventListener("submit", (e) => {
  const btn = e.target.querySelector("button[type=submit]");
  btn.disabled = true;
  btn.textContent = "Signing in…";
});
if (document.getElementById("form-error").hidden === false) pw.focus();
