(() => {
  "use strict";

  const views = {
    interactive: document.getElementById("interactive-view"),
    static: document.getElementById("static-view"),
  };
  const viewButtons = [...document.querySelectorAll(".view-button")];

  function selectView(view) {
    Object.entries(views).forEach(([name, element]) => {
      element.hidden = name !== view;
    });
    viewButtons.forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function selectModality(tabSet, modality) {
    const view = tabSet.dataset.tabs;
    tabSet.querySelectorAll(".modality-tab").forEach((button) => {
      const active = button.dataset.modality === modality;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll(`[data-view-panel="${view}"]`).forEach((panel) => {
      panel.hidden = panel.dataset.modality !== modality;
    });
  }

  viewButtons.forEach((button) => {
    button.addEventListener("click", () => selectView(button.dataset.view));
  });

  document.querySelectorAll(".modality-tabs").forEach((tabSet) => {
    tabSet.querySelectorAll(".modality-tab").forEach((button) => {
      button.addEventListener("click", () => {
        selectModality(tabSet, button.dataset.modality);
      });
    });
  });
})();
