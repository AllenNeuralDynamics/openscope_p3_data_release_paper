(() => {
  "use strict";

  const protocol = JSON.parse(document.getElementById("neural-data").textContent);
  const accents = {
    neuropixels: "#4b79c6",
    mesoscope: "#14a882",
    slap2: "#13a7bd",
  };
  const scaleBarMicrons = 50;
  const elements = {
    canvas: document.getElementById("raw-canvas"),
    contrast: document.getElementById("contrast"),
    interactiveView: document.getElementById("interactive-view"),
    loading: document.getElementById("loading-status"),
    modalitySelector: document.getElementById("modality-selector"),
    optionLabel: document.getElementById("option-label"),
    optionSelect: document.getElementById("option-select"),
    playhead: document.getElementById("playhead"),
    playheadTime: document.getElementById("playhead-time"),
    playIcon: document.getElementById("play-icon"),
    playToggle: document.getElementById("play-toggle"),
    staticView: document.getElementById("static-view"),
    tooltip: document.getElementById("canvas-tooltip"),
    transport: document.querySelector(".transport"),
    viewButtons: document.querySelectorAll(".view-button"),
    viewer: document.getElementById("neural-viewer"),
  };
  const context = elements.canvas.getContext("2d");
  const movieFrameCanvas = document.createElement("canvas");
  const movieFrameContext = movieFrameCanvas.getContext("2d");
  const excerptDuration = protocol.windowEndSeconds - protocol.windowStartSeconds;
  const matrixCache = new Map();
  const spriteCache = new Map();
  let movieFrameKey = "";
  const state = {
    contrast: 1,
    lastFrame: null,
    optionIndex: 0,
    playing: false,
    playhead: protocol.windowStartSeconds,
    sessionIndex: 0,
    spriteToken: 0,
    view: "interactive",
  };
  const layout = {
    anatomyLeft: 78,
    anatomyRight: 160,
    plotBottom: 458,
    plotLeft: 168,
    plotRight: 870,
    plotTop: 42,
  };

  function currentSession() {
    return protocol.sessions[state.sessionIndex];
  }

  function currentOption() {
    return currentSession().options[state.optionIndex];
  }

  function selectView(view) {
    state.view = view;
    if (view === "static") pause();
    elements.interactiveView.hidden = view !== "interactive";
    elements.staticView.hidden = view !== "static";
    elements.viewer.classList.toggle("static-active", view === "static");
    elements.viewButtons.forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function nearestIndex(values, target) {
    let low = 0;
    let high = values.length;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if (values[middle] < target) low = middle + 1;
      else high = middle;
    }
    if (low <= 0) return 0;
    if (low >= values.length) return values.length - 1;
    return target - values[low - 1] <= values[low] - target ? low - 1 : low;
  }

  function formatTime(value) {
    return `${value.toFixed(3)} s`;
  }

  function elapsedTime(sourceTime) {
    return sourceTime - protocol.windowStartSeconds;
  }

  function formatNumber(value, digits = 1) {
    return Number(value).toLocaleString(undefined, {
      maximumFractionDigits: digits,
      minimumFractionDigits: digits,
    });
  }

  function drawText(text, x, y, options = {}) {
    context.save();
    context.fillStyle = options.color || "#303536";
    context.font = `${options.weight || 500} ${options.size || 13}px "Myriad Pro", Arial, sans-serif`;
    context.textAlign = options.align || "left";
    context.textBaseline = options.baseline || "alphabetic";
    context.fillText(text, x, y);
    context.restore();
  }

  function decodeMatrix(option) {
    const key = `${currentSession().id}/${option.id}`;
    if (matrixCache.has(key)) return matrixCache.get(key);
    const binary = atob(option.dataBase64);
    const values = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      values[index] = binary.charCodeAt(index);
    }
    matrixCache.set(key, values);
    return values;
  }

  function voltageColor(encoded) {
    const centered = Math.max(-1, Math.min(1, (encoded - 127.5) / 127.5 * state.contrast));
    if (centered < 0) {
      const amount = centered + 1;
      return [
        Math.round(28 + amount * 218),
        Math.round(77 + amount * 169),
        Math.round(151 + amount * 95),
      ];
    }
    return [
      Math.round(246 - centered * 57),
      Math.round(246 - centered * 192),
      Math.round(246 - centered * 205),
    ];
  }

  function drawHeatmap(option) {
    const encoded = decodeMatrix(option);
    const offscreen = document.createElement("canvas");
    offscreen.width = option.columns;
    offscreen.height = option.rows;
    const offscreenContext = offscreen.getContext("2d");
    const pixels = offscreenContext.createImageData(option.columns, option.rows);
    for (let index = 0; index < encoded.length; index += 1) {
      const [red, green, blue] = voltageColor(encoded[index]);
      const pixel = index * 4;
      pixels.data[pixel] = red;
      pixels.data[pixel + 1] = green;
      pixels.data[pixel + 2] = blue;
      pixels.data[pixel + 3] = 255;
    }
    offscreenContext.putImageData(pixels, 0, 0);

    const plotWidth = layout.plotRight - layout.plotLeft;
    const plotHeight = layout.plotBottom - layout.plotTop;
    context.imageSmoothingEnabled = false;
    context.drawImage(offscreen, layout.plotLeft, layout.plotTop, plotWidth, plotHeight);
    drawAnatomySegments(option, plotHeight);
    context.strokeStyle = "#8f9996";
    context.strokeRect(layout.plotLeft, layout.plotTop, plotWidth, plotHeight);
    drawText("Raw AP acquisition", layout.plotLeft, layout.plotTop - 13, {
      color: "#4d5553",
      size: 12,
      weight: 700,
    });

    const depthTicks = [option.depthMaxUm, (option.depthMaxUm + option.depthMinUm) / 2, option.depthMinUm];
    depthTicks.forEach((depth, index) => {
      const y = layout.plotTop + index * plotHeight / 2;
      drawText(formatNumber(depth, 0), layout.anatomyLeft - 10, y + (index === 0 ? 8 : index === 2 ? -2 : 4), {
        align: "right",
        color: "#59615f",
        size: 12,
      });
    });
    context.save();
    context.translate(20, (layout.plotTop + layout.plotBottom) / 2);
    context.rotate(-Math.PI / 2);
    drawText("Distance from probe tip (µm)", 0, 0, {
      align: "center",
      color: "#4d5553",
      size: 12,
    });
    context.restore();

    const axisY = layout.plotBottom + 7;
    for (let index = 0; index <= 4; index += 1) {
      const fraction = index / 4;
      const x = layout.plotLeft + fraction * plotWidth;
      const milliseconds = fraction
        * (option.timeEndSeconds - option.timeStartSeconds)
        * 1000;
      context.strokeStyle = "#6c7572";
      context.beginPath();
      context.moveTo(x, layout.plotBottom);
      context.lineTo(x, axisY);
      context.stroke();
      drawText(`${Math.round(milliseconds)}`, x, axisY + 14, {
        align: "center",
        color: "#59615f",
        size: 12,
        weight: 500,
      });
    }
    drawText("Excerpt time (ms)", (layout.plotLeft + layout.plotRight) / 2, 510, {
      align: "center",
      color: "#4d5553",
      size: 12,
    });
  }

  function drawAnatomySegments(option, plotHeight) {
    const width = layout.anatomyRight - layout.anatomyLeft;
    drawText("CCF", layout.anatomyLeft + width / 2, layout.plotTop - 13, {
      align: "center",
      color: "#4d5553",
      size: 12,
      weight: 700,
    });
    option.anatomySegments.forEach((segment, index) => {
      const top = layout.plotTop + segment.startRow / option.rows * plotHeight;
      const bottom = layout.plotTop + segment.endRow / option.rows * plotHeight;
      const height = bottom - top;
      context.fillStyle = segment.label === "void"
        ? "#f5f6f6"
        : index % 2 === 0 ? "#e2e7e5" : "#eef1f0";
      context.fillRect(layout.anatomyLeft, top, width, height);
      if (height >= 15) {
        drawText(segment.label, layout.anatomyLeft + width / 2, top + height / 2, {
          align: "center",
          baseline: "middle",
          color: "#3f4745",
          size: 12,
          weight: 600,
        });
      }
      if (segment.startRow > 0) {
        context.strokeStyle = "rgba(255, 255, 255, 0.82)";
        context.lineWidth = 2;
        context.beginPath();
        context.moveTo(layout.anatomyLeft, top);
        context.lineTo(layout.plotRight, top);
        context.stroke();
        context.strokeStyle = "rgba(41, 48, 46, 0.72)";
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(layout.anatomyLeft, top);
        context.lineTo(layout.plotRight, top);
        context.stroke();
      }
    });
    context.strokeStyle = "#8f9996";
    context.lineWidth = 1;
    context.strokeRect(layout.anatomyLeft, layout.plotTop, width, plotHeight);
  }

  function loadSprite(option) {
    if (spriteCache.has(option.assetPath)) return spriteCache.get(option.assetPath);
    const image = new Image();
    const record = { image, ready: false, failed: false };
    spriteCache.set(option.assetPath, record);
    const token = ++state.spriteToken;
    elements.loading.hidden = false;
    elements.loading.textContent = "Loading raw frames";
    image.addEventListener("load", () => {
      record.ready = true;
      if (token === state.spriteToken) {
        elements.loading.hidden = true;
        renderCanvas();
      }
    });
    image.addEventListener("error", () => {
      record.failed = true;
      if (token === state.spriteToken) {
        elements.loading.hidden = false;
        elements.loading.textContent = "Raw frames unavailable";
      }
    });
    image.src = option.assetPath;
    return record;
  }

  function microscopyFrame(option, record, frameIndex) {
    const key = `${option.assetPath}:${frameIndex}:${state.contrast}`;
    if (movieFrameKey === key) return movieFrameCanvas;
    if (
      movieFrameCanvas.width !== option.frameWidth
      || movieFrameCanvas.height !== option.frameHeight
    ) {
      movieFrameCanvas.width = option.frameWidth;
      movieFrameCanvas.height = option.frameHeight;
    }
    const sourceX = (frameIndex % option.sheetColumns) * option.frameWidth;
    const sourceY = Math.floor(frameIndex / option.sheetColumns) * option.frameHeight;
    movieFrameContext.clearRect(0, 0, option.frameWidth, option.frameHeight);
    movieFrameContext.drawImage(
      record.image,
      sourceX,
      sourceY,
      option.frameWidth,
      option.frameHeight,
      0,
      0,
      option.frameWidth,
      option.frameHeight,
    );
    if (state.contrast !== 1) {
      const image = movieFrameContext.getImageData(
        0,
        0,
        option.frameWidth,
        option.frameHeight,
      );
      for (let index = 0; index < image.data.length; index += 4) {
        image.data[index] = Math.min(255, Math.round(image.data[index] * state.contrast));
        image.data[index + 1] = Math.min(
          255,
          Math.round(image.data[index + 1] * state.contrast),
        );
        image.data[index + 2] = Math.min(
          255,
          Math.round(image.data[index + 2] * state.contrast),
        );
      }
      movieFrameContext.putImageData(image, 0, 0);
    }
    movieFrameKey = key;
    return movieFrameCanvas;
  }

  function drawMovie(option) {
    const record = loadSprite(option);
    if (!record.ready) return;
    const frameIndex = nearestIndex(option.frameTimes, state.playhead);
    const availableWidth = 760;
    const availableHeight = 460;
    const scale = Math.min(
      availableWidth / option.frameWidth,
      availableHeight / option.frameHeight,
    );
    const width = option.frameWidth * scale;
    const height = option.frameHeight * scale;
    const x = (elements.canvas.width - width) / 2;
    const y = (elements.canvas.height - height) / 2;
    context.imageSmoothingEnabled = true;
    context.drawImage(
      microscopyFrame(option, record, frameIndex),
      x,
      y,
      width,
      height,
    );
    context.strokeStyle = "#8f9996";
    context.strokeRect(x, y, width, height);
    drawScaleBar(option, x, y, width, height);
  }

  function drawScaleBar(option, x, y, width, height) {
    const micronsPerPixel = Number(option.micronsPerPixel);
    if (!Number.isFinite(micronsPerPixel) || micronsPerPixel <= 0) return;
    const displayWidth = option.displayWidth || option.nativeWidth;
    const barWidth = width * scaleBarMicrons / (displayWidth * micronsPerPixel);
    const barX = x + width - barWidth - 18;
    const barY = y + height - 18;

    context.save();
    context.lineCap = "butt";
    context.strokeStyle = "rgba(0, 0, 0, 0.82)";
    context.lineWidth = 7;
    context.beginPath();
    context.moveTo(barX, barY);
    context.lineTo(barX + barWidth, barY);
    context.stroke();
    context.strokeStyle = "#fff";
    context.lineWidth = 4;
    context.beginPath();
    context.moveTo(barX, barY);
    context.lineTo(barX + barWidth, barY);
    context.stroke();
    context.shadowColor = "rgba(0, 0, 0, 0.9)";
    context.shadowBlur = 3;
    drawText(`${scaleBarMicrons} µm`, barX + barWidth / 2, barY - 9, {
      align: "center",
      color: "#fff",
      size: 12,
      weight: 700,
    });
    context.restore();
  }

  function renderCanvas() {
    context.clearRect(0, 0, elements.canvas.width, elements.canvas.height);
    context.fillStyle = "#fff";
    context.fillRect(0, 0, elements.canvas.width, elements.canvas.height);
    const option = currentOption();
    if (currentSession().viewType === "heatmap") drawHeatmap(option);
    else drawMovie(option);
  }

  function buildTabs() {
    protocol.sessions.forEach((session, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "modality-tab";
      const logo = document.createElement("img");
      logo.className = "modality-logo";
      logo.src = session.logo;
      logo.alt = "";
      logo.width = 42;
      logo.height = 42;
      button.append(logo, session.label);
      button.setAttribute("aria-label", `${session.label}, mouse ${session.subject}`);
      button.addEventListener("click", () => selectSession(index));
      elements.modalitySelector.append(button);
    });
  }

  function populateOptions() {
    elements.optionSelect.replaceChildren();
    currentSession().options.forEach((option) => {
      elements.optionSelect.append(new Option(option.label, option.id));
    });
    elements.optionSelect.selectedIndex = state.optionIndex;
    elements.optionLabel.textContent = currentSession().optionLabel;
  }

  function updateTabs() {
    elements.modalitySelector.querySelectorAll("button").forEach((button, index) => {
      const active = index === state.sessionIndex;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function selectSession(index) {
    pause();
    hideTooltip();
    state.sessionIndex = index;
    state.optionIndex = 0;
    state.playhead = protocol.windowStartSeconds;
    state.spriteToken += 1;
    document.documentElement.style.setProperty("--accent", accents[currentSession().id]);
    populateOptions();
    updateTabs();
    render();
  }

  function render() {
    const session = currentSession();
    elements.transport.hidden = session.viewType === "heatmap";
    elements.canvas.setAttribute(
      "aria-label",
      session.viewType === "heatmap"
        ? "Raw 30 kHz AP acquisition voltage with CCF boundaries across the probe shaft"
        : "Raw imaging frames with a 50 micrometer scale bar",
    );
    elements.playhead.value = elapsedTime(state.playhead);
    elements.playheadTime.textContent = formatTime(elapsedTime(state.playhead));
    renderCanvas();
  }

  function setPlayhead(value) {
    state.playhead = Math.max(
      protocol.windowStartSeconds,
      Math.min(protocol.windowEndSeconds, value),
    );
    elements.playhead.value = elapsedTime(state.playhead);
    elements.playheadTime.textContent = formatTime(elapsedTime(state.playhead));
    renderCanvas();
  }

  function pause() {
    state.playing = false;
    state.lastFrame = null;
    elements.playIcon.innerHTML = "&#9654;";
    elements.playToggle.setAttribute("aria-label", "Play raw-data excerpt");
    elements.playToggle.title = "Play";
  }

  function play() {
    if (state.playhead >= protocol.windowEndSeconds - 0.001) {
      state.playhead = protocol.windowStartSeconds;
    }
    state.playing = true;
    state.lastFrame = null;
    elements.playIcon.innerHTML = "&#10074;&#10074;";
    elements.playToggle.setAttribute("aria-label", "Pause raw-data excerpt");
    elements.playToggle.title = "Pause";
    requestAnimationFrame(animate);
  }

  function animate(timestamp) {
    if (!state.playing) return;
    if (state.lastFrame != null) {
      state.playhead += (timestamp - state.lastFrame) / 1000;
    }
    state.lastFrame = timestamp;
    if (state.playhead >= protocol.windowEndSeconds) {
      state.playhead = protocol.windowEndSeconds;
      render();
      pause();
      return;
    }
    render();
    requestAnimationFrame(animate);
  }

  function pointerPosition(event) {
    const bounds = elements.canvas.getBoundingClientRect();
    return {
      x: (event.clientX - bounds.left) / bounds.width * elements.canvas.width,
      y: (event.clientY - bounds.top) / bounds.height * elements.canvas.height,
    };
  }

  function showTooltip(event) {
    const position = pointerPosition(event);
    const session = currentSession();
    const option = currentOption();
    let content = "";
    if (
      session.viewType === "heatmap"
      && position.x >= layout.anatomyLeft
      && position.x <= layout.plotRight
      && position.y >= layout.plotTop
      && position.y <= layout.plotBottom
    ) {
      const row = Math.min(
        option.rows - 1,
        Math.floor((position.y - layout.plotTop) / (layout.plotBottom - layout.plotTop) * option.rows),
      );
      const depth = option.depthMaxUm
        - row / (option.rows - 1) * (option.depthMaxUm - option.depthMinUm);
      const anatomy = option.anatomySegments.find(
        segment => row >= segment.startRow && row < segment.endRow,
      );
      if (position.x < layout.plotLeft) {
        content = `<strong>${anatomy.label}</strong><br>${formatNumber(depth, 0)} µm from tip`;
      } else {
        const column = Math.min(
          option.columns - 1,
          Math.floor((position.x - layout.plotLeft) / (layout.plotRight - layout.plotLeft) * option.columns),
        );
        const encoded = decodeMatrix(option)[row * option.columns + column];
        const voltage = (encoded / 255 * 2 - 1) * option.valueLimit;
        const time = option.timeStartSeconds
          + (column + 0.5) / option.columns
          * (option.timeEndSeconds - option.timeStartSeconds);
        const milliseconds = (time - option.timeStartSeconds) * 1000;
        content = `<strong>${milliseconds.toFixed(2)} ms</strong><br>${formatNumber(depth, 0)} µm from tip · ${anatomy.label}<br>${formatNumber(voltage, 1)} µV`;
      }
    } else if (session.viewType === "movie") {
      const index = nearestIndex(option.frameTimes, state.playhead);
      const storedWidth = option.storedWidth || option.nativeWidth;
      const storedHeight = option.storedHeight || option.nativeHeight;
      content = `<strong>${formatTime(elapsedTime(option.frameTimes[index]))}</strong><br>Raw frame ${index + 1} of ${option.frameCount}<br>${storedWidth} × ${storedHeight} stored pixels`;
    }
    if (!content) {
      hideTooltip();
      return;
    }
    elements.tooltip.innerHTML = content;
    elements.tooltip.hidden = false;
    const width = elements.tooltip.offsetWidth;
    const height = elements.tooltip.offsetHeight;
    elements.tooltip.style.left = `${Math.min(event.clientX + 12, window.innerWidth - width - 8)}px`;
    elements.tooltip.style.top = `${Math.max(8, Math.min(event.clientY + 12, window.innerHeight - height - 8))}px`;
  }

  function hideTooltip() {
    elements.tooltip.hidden = true;
  }

  elements.optionSelect.addEventListener("change", () => {
    pause();
    hideTooltip();
    state.optionIndex = elements.optionSelect.selectedIndex;
    state.spriteToken += 1;
    render();
  });
  elements.contrast.addEventListener("input", () => {
    state.contrast = Number(elements.contrast.value);
    renderCanvas();
  });
  elements.playhead.addEventListener("input", () => {
    pause();
    setPlayhead(protocol.windowStartSeconds + Number(elements.playhead.value));
  });
  elements.playToggle.addEventListener("click", () => {
    if (state.playing) pause();
    else play();
  });
  elements.canvas.addEventListener("pointermove", showTooltip);
  elements.canvas.addEventListener("pointerleave", hideTooltip);
  elements.canvas.addEventListener("click", () => {
    if (currentSession().viewType === "movie") {
      if (state.playing) pause();
      else play();
    }
  });
  elements.canvas.addEventListener("keydown", (event) => {
    if (currentSession().viewType !== "movie") return;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    pause();
    setPlayhead(state.playhead + (event.key === "ArrowRight" ? 0.04 : -0.04));
  });
  elements.viewButtons.forEach((button) => {
    button.addEventListener("click", () => selectView(button.dataset.view));
  });

  buildTabs();
  elements.playhead.max = excerptDuration;
  populateOptions();
  updateTabs();
  document.documentElement.style.setProperty("--accent", accents[currentSession().id]);
  selectView("interactive");
  render();
})();