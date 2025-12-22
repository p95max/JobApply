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
    if (el.dataset.disabled === "1") {
      e.preventDefault();
      el.classList.remove("shake");
      // reflow to restart animation
      void el.offsetWidth;
      el.classList.add("shake");
    }
  }

  document.querySelectorAll(".nav-anim").forEach((el) => {
    el.addEventListener("mouseenter", onEnter);
    el.addEventListener("click", onClick);
  });
})();
