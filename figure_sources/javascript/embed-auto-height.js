(() => {
  "use strict";

  const root = document.querySelector("body > main");
  if (!root || window.self === window.top) return;

  let wrapper;
  try {
    wrapper = window.frameElement?.parentElement;
  } catch {
    return;
  }
  if (!wrapper) return;

  document.documentElement.classList.add("is-embedded");
  document.documentElement.style.overflow = "hidden";
  document.body.style.overflow = "hidden";
  const syncHeight = () => {
    const height = Math.ceil(root.getBoundingClientRect().height);
    if (height > 0) wrapper.style.height = `${height}px`;
  };
  const resizeObserver = new ResizeObserver(syncHeight);
  resizeObserver.observe(root);
  window.addEventListener("resize", syncHeight);
  window.addEventListener("load", syncHeight, { once: true });
  syncHeight();
})();