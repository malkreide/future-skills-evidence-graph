// Standalone theme toggle for the secondary pages (einreichen, architektur).
// index.html keeps its own wiring in app.js because the radar canvas must be
// repainted on a theme change; here nothing needs repainting, so this small
// self-contained script is all the page needs. Storage key and behaviour are
// identical, so the choice travels between pages.
(function () {
  const MOON_SVG =
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>';
  const SUN_SVG =
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';

  const toggle = document.querySelector("#themeToggle");
  if (!toggle) return;

  function setTheme(theme) {
    const dark = theme === "dark";
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    try {
      localStorage.setItem("fseg-theme", dark ? "dark" : "light");
    } catch (_) {
      // Storage may be unavailable (private mode); the toggle still works per session.
    }
    toggle.setAttribute("aria-pressed", String(dark));
    toggle.setAttribute("aria-label", dark ? "Helles Design einschalten" : "Dunkles Design einschalten");
    const icon = toggle.querySelector(".theme-toggle-icon");
    const text = toggle.querySelector(".theme-toggle-text");
    // Show the icon of the mode you would switch *to*.
    if (icon) icon.innerHTML = dark ? SUN_SVG : MOON_SVG;
    if (text) text.textContent = dark ? "Hell" : "Dunkel";
  }

  // The pre-paint script in <head> already stamped data-theme; sync the button.
  setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");
  toggle.addEventListener("click", () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    setTheme(dark ? "light" : "dark");
  });
})();
