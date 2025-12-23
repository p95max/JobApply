(function () {
  function onEnter(e) {
    const el = e.currentTarget;
    if (el.dataset.disabled === "1") return;
    el.style.transform = "translateY(-1px) scale(1.03)";
    clearTimeout(el.__navT);
    el.__navT = setTimeout(() => {
      el.style.transform = "";
    }, 140);
  }

  function onClick(e) {
    const el = e.currentTarget;
    // Не трогаем дропдауны
    if (el.getAttribute("data-bs-toggle") === "dropdown") return;

    if (el.dataset.disabled === "1") {
      e.preventDefault();
      el.classList.remove("shake");
      void el.offsetWidth;
      el.classList.add("shake");
    }
  }

  document.querySelectorAll(".nav-anim").forEach((el) => {
    el.addEventListener("mouseenter", onEnter);
    if (el.getAttribute("data-bs-toggle") !== "dropdown") {
      el.addEventListener("click", onClick);
    }
  });
})();