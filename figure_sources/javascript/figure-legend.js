(() => {
  "use strict";

  const toggle = document.getElementById("figure-legend-toggle");
  const legend = document.getElementById("figure-legend");
  const staticButton = document.querySelector('[data-view="static"]');

  function setLegendOpen(open) {
    if (!toggle || !legend) return;
    legend.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
  }

  function syncLegend() {
    if (!toggle || !staticButton) return;
    const isStatic = staticButton.getAttribute("aria-pressed") === "true"
      || staticButton.getAttribute("aria-selected") === "true";
    toggle.hidden = isStatic;
    if (isStatic) setLegendOpen(false);
  }

  if (toggle && legend) {
    toggle.addEventListener("click", () => setLegendOpen(legend.hidden));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !legend.hidden) {
        setLegendOpen(false);
        toggle.focus();
      }
    });
    if (staticButton) {
      new MutationObserver(syncLegend).observe(staticButton, {
        attributes: true,
        attributeFilter: ["aria-pressed", "aria-selected"],
      });
    }
    syncLegend();
  }

  const simpleViewer = document.querySelector("[data-simple-view]");
  if (simpleViewer) {
    const buttons = simpleViewer.querySelectorAll("[data-view]");
    function selectView(view) {
      simpleViewer.querySelector("#interactive-view").hidden = view !== "interactive";
      simpleViewer.querySelector("#static-view").hidden = view !== "static";
      buttons.forEach((button) => {
        const active = button.dataset.view === view;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      });
      syncLegend();
      window.dispatchEvent(new Event("resize"));
    }
    buttons.forEach((button) => {
      button.addEventListener("click", () => selectView(button.dataset.view));
    });
    selectView("static");
  }
})();