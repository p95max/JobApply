(() => {
  const header = document.querySelector("[data-app-header]");
  const toggle = document.querySelector("[data-menu-toggle]");
  const panel = document.querySelector("[data-menu-panel]");

  if (!header || !toggle || !panel) return;

  const closeMenu = () => {
    header.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
  };

  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    header.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", String(open));
  });

  panel.addEventListener("click", (event) => {
    if (event.target.closest("a") && window.matchMedia("(max-width: 899.98px)").matches) {
      closeMenu();
    }
  });

  document.addEventListener("click", (event) => {
    if (!header.contains(event.target)) {
      closeMenu();
      document.querySelectorAll("[data-services-menu][open]").forEach((menu) => {
        menu.removeAttribute("open");
      });
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenu();
      document.querySelectorAll("[data-services-menu][open]").forEach((menu) => {
        menu.removeAttribute("open");
      });
      toggle.focus();
    }
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth >= 900) closeMenu();
  });
})();