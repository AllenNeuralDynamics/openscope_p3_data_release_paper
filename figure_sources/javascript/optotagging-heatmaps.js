(() => {
  const select = document.querySelector("#session-select");
  const parentSelect = document.querySelector("#parent-area");
  const slider = document.querySelector("#color-limit");
  const sliderValue = document.querySelector("#color-limit-value");
  const title = document.querySelector("#session-title");
  const details = document.querySelector("#session-details");
  const numericFigure = document.querySelector("#numeric-figure");
  const fallbackFigure = document.querySelector("#fallback-figure");
  const fallbackImage = document.querySelector("#heatmap-image");
  const panels = document.querySelector("#heatmap-panels");
  const interactiveView = document.querySelector("#interactive-view");
  const staticView = document.querySelector("#static-view");
  const viewButtons = document.querySelectorAll(".view-button");
  const sessionsById = new Map(
    OPTOTAGGING_DATA.sessions.map((session) => [session.session_id, session]),
  );
  let loadedAtlas = null;
  let loadGeneration = 0;
  let redrawTimer = null;

  function selectView(view) {
    interactiveView.hidden = view !== "interactive";
    staticView.hidden = view !== "static";
    viewButtons.forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function sessionLabel(session) {
    return session.session_id.replace(/^ecephys_/, "");
  }

  function conditionDetails(session) {
    return OPTOTAGGING_DATA.conditions
      .map((condition) => {
        const counts = session.condition_counts[condition.table_name];
        return `${condition.display_name}: ${counts.presentations} presentations, ` +
          `${counts.pulses} pulses`;
      })
      .join(" · ");
  }

  function updateUrl(sessionId) {
    const url = new URL(window.location.href);
    url.searchParams.set("session", sessionId);
    window.history.replaceState({}, "", url);
  }

  function colorFor(value, limit) {
    if (!Number.isFinite(value)) return [230, 230, 230, 255];
    const fraction = Math.max(-1, Math.min(1, value / limit));
    const cold = [59, 76, 192];
    const middle = [247, 247, 247];
    const warm = [180, 4, 38];
    const start = fraction < 0 ? cold : middle;
    const end = fraction < 0 ? middle : warm;
    const amount = fraction < 0 ? fraction + 1 : fraction;
    return [
      Math.round(start[0] + amount * (end[0] - start[0])),
      Math.round(start[1] + amount * (end[1] - start[1])),
      Math.round(start[2] + amount * (end[2] - start[2])),
      255,
    ];
  }

  function selectedUnitIndices(metadata, condition) {
    const requested = parentSelect.value;
    const areaIndex = metadata.parent_areas.indexOf(requested);
    const order = metadata.strongest_first_unit_indices[condition.table_name];
    if (!requested || requested === "All areas" || areaIndex < 0) return order;
    return order.filter((unitIndex) => metadata.parent_codes[unitIndex] === areaIndex);
  }

  function drawPanel(canvas, atlas, condition) {
    const {metadata, scalars} = atlas;
    const units = selectedUnitIndices(metadata, condition);
    const bins = metadata.time_bin_count;
    const source = document.createElement("canvas");
    source.width = bins;
    source.height = Math.max(1, units.length);
    const sourceContext = source.getContext("2d");
    const pixels = sourceContext.createImageData(bins, source.height);
    const limit = Number(slider.value);
    const rowOffset = metadata.condition_row_offsets[condition.table_name];
    for (let row = 0; row < units.length; row += 1) {
      const scalarOffset = (rowOffset + units[row]) * bins;
      for (let column = 0; column < bins; column += 1) {
        const quantized = scalars[scalarOffset + column];
        const value = quantized === metadata.quantization.nan_sentinel
          ? Number.NaN
          : quantized / metadata.quantization.scale;
        pixels.data.set(colorFor(value, limit), (row * bins + column) * 4);
      }
    }
    sourceContext.putImageData(pixels, 0, 0);

    const width = Math.max(320, Math.round(canvas.getBoundingClientRect().width * devicePixelRatio));
    const height = Math.max(300, Math.round(canvas.getBoundingClientRect().height * devicePixelRatio));
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    const margin = {left: 48, right: 8, top: 8, bottom: 30};
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    context.imageSmoothingEnabled = false;
    context.fillStyle = "#f2f2f2";
    context.fillRect(0, 0, width, height);
    if (units.length) {
      context.drawImage(source, margin.left, margin.top, plotWidth, plotHeight);
    }
    const [timeStart, timeEnd] = metadata.time_seconds;
    const laserX = margin.left + ((0 - timeStart) / (timeEnd - timeStart)) * plotWidth;
    context.strokeStyle = "#111";
    context.setLineDash([5, 4]);
    context.beginPath();
    context.moveTo(laserX, margin.top);
    context.lineTo(laserX, margin.top + plotHeight);
    context.stroke();
    context.setLineDash([]);
    context.fillStyle = "#293133";
    context.font = `${12 * devicePixelRatio}px Arial`;
    context.textAlign = "center";
    for (const tick of [-0.5, 0, 0.5, 1]) {
      const x = margin.left + ((tick - timeStart) / (timeEnd - timeStart)) * plotWidth;
      context.fillText(String(tick), x, height - 13);
    }
    context.save();
    context.translate(14, margin.top + plotHeight / 2);
    context.rotate(-Math.PI / 2);
    context.fillText("Units (strongest at top)", 0, 0);
    context.restore();
    canvas.setAttribute(
      "aria-label",
      `${condition.display_name} heatmap with ${units.length.toLocaleString()} units; ` +
      "strongest exact-laser-on response at top.",
    );
    canvas.parentElement.querySelector("p").textContent =
      `${units.length.toLocaleString()} units · time from laser onset (s)`;
  }

  function redraw() {
    if (!loadedAtlas) return;
    for (const condition of OPTOTAGGING_DATA.conditions) {
      const canvas = panels.querySelector(`[data-condition="${condition.table_name}"]`);
      drawPanel(canvas, loadedAtlas, condition);
    }
    const limit = Number(slider.value);
    sliderValue.value = String(limit);
    document.querySelector("#color-min").textContent = `−${limit}`;
    document.querySelector("#color-max").textContent = `+${limit}`;
  }

  function scheduleRedraw() {
    sliderValue.value = slider.value;
    window.clearTimeout(redrawTimer);
    redrawTimer = window.setTimeout(redraw, 150);
  }

  function decodeAtlasImage(image, metadata) {
    const decoder = document.createElement("canvas");
    decoder.width = image.naturalWidth;
    decoder.height = image.naturalHeight;
    const context = decoder.getContext("2d", {willReadFrequently: true});
    context.drawImage(image, 0, 0);
    const bytes = context.getImageData(0, 0, decoder.width, decoder.height).data;
    const scalars = new Int8Array(decoder.width * decoder.height);
    for (let index = 0; index < scalars.length; index += 1) {
      const unsigned = bytes[index * 4];
      scalars[index] = unsigned >= 0x80 ? unsigned - 0x100 : unsigned;
    }
    return scalars;
  }

  async function loadNumericAtlas(session, generation) {
    const embedded = globalThis.OPTOTAGGING_ATLASES?.[session.session_id];
    if (!embedded) {
      throw new Error("Embedded atlas not found for the selected session.");
    }
    const metadata = embedded.metadata;
    const image = new Image();
    image.src = embedded.image;
    await image.decode();
    if (generation !== loadGeneration) return;
    loadedAtlas = {metadata, scalars: decodeAtlasImage(image, metadata)};
    const previousArea = parentSelect.value;
    parentSelect.replaceChildren();
    for (const area of ["All areas", ...metadata.parent_areas]) {
      const option = document.createElement("option");
      option.value = area;
      option.textContent = area;
      parentSelect.append(option);
    }
    parentSelect.value = metadata.parent_areas.includes(previousArea)
      ? previousArea
      : "All areas";
    parentSelect.disabled = false;
    slider.disabled = false;
    numericFigure.hidden = false;
    fallbackFigure.hidden = true;
    redraw();
  }

  function buildPanels() {
    panels.replaceChildren();
    for (const condition of OPTOTAGGING_DATA.conditions) {
      const panel = document.createElement("section");
      panel.className = "heatmap-panel";
      const heading = document.createElement("h2");
      heading.textContent = condition.display_name;
      const canvas = document.createElement("canvas");
      canvas.dataset.condition = condition.table_name;
      canvas.setAttribute("role", "img");
      const count = document.createElement("p");
      panel.append(heading, canvas, count);
      panels.append(panel);
    }
  }

  async function renderSession(sessionId) {
    const session = sessionsById.get(sessionId);
    if (!session) return;
    title.textContent = sessionLabel(session);
    details.textContent =
      `${session.unit_count.toLocaleString()} non-noise units · ${conditionDetails(session)}`;
    updateUrl(session.session_id);
    loadedAtlas = null;
    const generation = ++loadGeneration;
    if (OPTOTAGGING_DATA.version === 1) {
      parentSelect.disabled = true;
      slider.disabled = true;
      fallbackImage.src = `media/optotagging/${session.image_file}`;
      fallbackImage.alt = `Three optotagging heatmaps for ${session.session_id}.`;
      fallbackFigure.hidden = false;
      numericFigure.hidden = true;
      return;
    }
    try {
      await loadNumericAtlas(session, generation);
    } catch (error) {
      if (generation !== loadGeneration) return;
      details.textContent = `${details.textContent} · ${error.message}`;
    }
  }

  function populateOptions(preferredId) {
    select.replaceChildren();
    for (const session of OPTOTAGGING_DATA.sessions) {
      const option = document.createElement("option");
      option.value = session.session_id;
      option.textContent = sessionLabel(session);
      select.append(option);
    }
    const selectedId = OPTOTAGGING_DATA.sessions.some(
      (session) => session.session_id === preferredId,
    )
      ? preferredId
      : OPTOTAGGING_DATA.sessions[0].session_id;
    select.value = selectedId;
    renderSession(selectedId);
  }

  select.addEventListener("change", () => renderSession(select.value));
  slider.addEventListener("input", scheduleRedraw);
  parentSelect.addEventListener("change", scheduleRedraw);
  window.addEventListener("resize", scheduleRedraw);
  viewButtons.forEach((button) => {
    button.addEventListener("click", () => selectView(button.dataset.view));
  });

  buildPanels();
  const requestedSession = new URL(window.location.href).searchParams.get("session");
  const initialSession = sessionsById.has(requestedSession)
    ? requestedSession
    : OPTOTAGGING_DATA.default_session_id;
  populateOptions(initialSession);
})();
