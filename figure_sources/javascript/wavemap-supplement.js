const tabs = [...document.querySelectorAll('[role="tab"]')];

function selectView(selected, focus = false) {
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

function fitFrame(frame) {
  try {
    const body = frame.contentDocument?.body;
    if (!body || body.scrollHeight < 100) return;
    frame.style.height = `${Math.max(900, body.scrollHeight)}px`;
  } catch {
    return;
  }
}

tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectView(tab));
  tab.addEventListener("keydown", (event) => {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    selectView(tabs[next], true);
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
  document.querySelectorAll('section:not([hidden]) iframe').forEach(fitFrame);
});