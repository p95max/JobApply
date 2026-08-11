(() => {
  const storageKey = "jobapply-theme";

  const currentTheme = () => document.documentElement.getAttribute("data-bs-theme") || "dark";

  const applyTheme = (theme) => {
    document.documentElement.setAttribute("data-bs-theme", theme);
    try {
      localStorage.setItem(storageKey, theme);
    } catch (_) {}

    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      const isLight = theme === "light";
      const nextLabel = isLight ? button.dataset.darkLabel : button.dataset.lightLabel;
      button.setAttribute("aria-label", nextLabel || "");
      button.setAttribute("title", nextLabel || "");
      button.setAttribute("aria-pressed", String(isLight));
      const icon = button.querySelector("[data-theme-icon]");
      if (icon) icon.textContent = isLight ? "🌙" : "☀️";
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(currentTheme());
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        applyTheme(currentTheme() === "light" ? "dark" : "light");
      });
    });
  });
})();
