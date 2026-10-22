const tabs = [...document.querySelectorAll('[role="tab"]')];
const viewButtons = [...document.querySelectorAll('.figure-mode-switch [data-view]')];

function selectAnalysis(selected, focus = false) {
  tabs.forEach((tab) => {
    const active = tab === selected;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    const panel = document.getElementById(tab.getAttribute("aria-controls"));
    panel.hidden = !active;
    const frame = panel.querySelector("iframe");
    if (active && frame && !frame.getAttribute("src")) {
      frame.src = frame.dataset.src;
    }
  });
  if (focus) selected.focus();
  window.dispatchEvent(new Event("resize"));
}

function selectView(view) {
  document.getElementById("interactive-view").hidden = view !== "interactive";
  document.getElementById("panel-static").hidden = view !== "static";
  viewButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.view === view));
  });
  if (view === "interactive") {
    selectAnalysis(tabs.find(tab => tab.getAttribute("aria-selected") === "true") || tabs[0]);
  }
  window.dispatchEvent(new Event("resize"));
}

function fitFrame(frame) {
  try {
    const body = frame.contentDocument?.body;
    if (!body || body.scrollHeight < 100) return;
    frame.style.height = `${Math.max(900, body.scrollHeight)}px`;
  } catch {
    return;
  }
}

viewButtons.forEach((button) => {
  button.addEventListener("click", () => selectView(button.dataset.view));
});

tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectAnalysis(tab));
  tab.addEventListener("keydown", (event) => {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    selectAnalysis(tabs[next], true);
  });
});

document.querySelectorAll("iframe").forEach((frame) => {
  frame.addEventListener("load", () => {
    fitFrame(frame);
    if (frame.contentDocument?.body) {
      const observer = new ResizeObserver(() => fitFrame(frame));
      observer.observe(frame.contentDocument.body);
    }
  });
});

window.addEventListener("resize", () => {
  document.querySelectorAll('#interactive-view:not([hidden]) section:not([hidden]) iframe')
    .forEach(fitFrame);
});
selectView("static");