(() => {
  "use strict";

  const viewer = JSON.parse(document.getElementById("segmentation-data").textContent);
  const colors = ["#25aae1", "#8cc63f", "#ccaf2d", "#d65c48", "#24bcad", "#b160a9"];
  const elements = {
    activityChart: document.getElementById("activity-chart"),
    activityControl: document.getElementById("activity-control"),
    activityKey: document.getElementById("activity-key"),
    activityToggle: document.getElementById("activity-toggle"),
    canvas: document.getElementById("source-canvas"),
    filterMetadata: document.getElementById("filter-metadata"),
    filterSelect: document.getElementById("filter-select"),
    loading: document.getElementById("loading-status"),
    nextFilter: document.getElementById("next-filter"),
    opacity: document.getElementById("overlay-opacity"),
    previousFilter: document.getElementById("previous-filter"),
    qcControl: document.getElementById("qc-control"),
    qcKey: document.getElementById("qc-key"),
    qcToggle: document.getElementById("qc-toggle"),
    selectionSwatch: document.getElementById("selection-swatch"),
    selectionTitle: document.getElementById("selection-title"),
    tooltip: document.getElementById("canvas-tooltip"),
    traceTitle: document.getElementById("trace-title"),
    traceWindow: document.getElementById("trace-window"),
    waveformChart: document.getElementById("waveform-chart"),
    waveformSection: document.getElementById("waveform-section"),
  };
  const context = elements.canvas.getContext("2d");
  const traceValues = decodeFloat32(viewer.traceDataBase64);
  const waveformValues = viewer.waveformDataBase64
    ? decodeFloat32(viewer.waveformDataBase64)
    : null;
  const imageRecords = {};
  const state = {
    activityVisible: true,
    imageRect: null,
    labelPixels: null,
    overlayOpacity: 0.74,
    probeHits: [],
    qcOnly: false,
    selectedIndex: viewer.defaultFilterIndex,
  };

  function decodeFloat32(encoded) {
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new Float32Array(bytes.buffer);
  }

  function currentFilter() {
    return viewer.filters[state.selectedIndex];
  }

  function filterColor(index) {
    return colors[index % colors.length];
  }

  function formatNumber(value, digits = 1) {
    return Number(value).toLocaleString(undefined, {
      maximumFractionDigits: digits,
      minimumFractionDigits: digits,
    });
  }

  function loadImage(record, key) {
    if (!record) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.addEventListener("load", () => {
        imageRecords[key] = image;
        resolve();
      });
      image.addEventListener("error", reject);
      image.src = record.assetPath;
    });
  }

  function containedRect(sourceWidth, sourceHeight, bounds) {
    const scale = Math.min(bounds.width / sourceWidth, bounds.height / sourceHeight);
    const width = sourceWidth * scale;
    const height = sourceHeight * scale;
    return {
      height,
      width,
      x: bounds.x + (bounds.width - width) / 2,
      y: bounds.y + (bounds.height - height) / 2,
    };
  }

  function drawCanvasText(text, x, y, options = {}) {
    context.save();
    context.fillStyle = options.color || "#dbe5e3";
    context.font = `${options.weight || 600} ${options.size || 14}px "Myriad Pro", sans-serif`;
    context.textAlign = options.align || "left";
    context.textBaseline = options.baseline || "alphabetic";
    context.fillText(text, x, y);
    context.restore();
  }

  function buildLabelPixels() {
    const image = imageRecords.labels;
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const labelContext = canvas.getContext("2d", { willReadFrequently: true });
    labelContext.imageSmoothingEnabled = false;
    labelContext.drawImage(image, 0, 0);
    state.labelPixels = labelContext.getImageData(0, 0, canvas.width, canvas.height);
  }

  function drawSelectionMask(rect) {
    const source = state.labelPixels;
    const selectedLabel = state.selectedIndex + 1;
    const maskCanvas = document.createElement("canvas");
    maskCanvas.width = source.width;
    maskCanvas.height = source.height;
    const maskContext = maskCanvas.getContext("2d");
    const mask = maskContext.createImageData(source.width, source.height);
    const color = hexToRgb(filterColor(state.selectedIndex));
    for (let pixel = 0; pixel < source.width * source.height; pixel += 1) {
      const offset = pixel * 4;
      const label = source.data[offset]
        + (source.data[offset + 1] << 8)
        + (source.data[offset + 2] << 16);
      if (label !== selectedLabel) continue;
      mask.data[offset] = color[0];
      mask.data[offset + 1] = color[1];
      mask.data[offset + 2] = color[2];
      mask.data[offset + 3] = 115;
    }
    maskContext.putImageData(mask, 0, 0);
    context.imageSmoothingEnabled = false;
    context.drawImage(maskCanvas, rect.x, rect.y, rect.width, rect.height);
  }

  function hexToRgb(value) {
    return [
      Number.parseInt(value.slice(1, 3), 16),
      Number.parseInt(value.slice(3, 5), 16),
      Number.parseInt(value.slice(5, 7), 16),
    ];
  }

  function drawScaleBar(rect) {
    if (!viewer.micronsPerPixel) return;
    const scaleMicrons = viewer.id === "slap2" ? 25 : 50;
    const sourcePixels = scaleMicrons / viewer.micronsPerPixel;
    const width = sourcePixels / viewer.baseImage.width * rect.width;
    const x = rect.x + rect.width - width - 22;
    const y = rect.y + rect.height - 24;
    context.strokeStyle = "#f8fbfa";
    context.lineWidth = 4;
    context.beginPath();
    context.moveTo(x, y);
    context.lineTo(x + width, y);
    context.stroke();
    drawCanvasText(`${scaleMicrons} µm`, x + width / 2, y - 8, {
      align: "center",
      color: "#f8fbfa",
      size: 13,
    });
  }

  function drawImageViewer() {
    const bounds = { x: 28, y: 28, width: 844, height: 650 };
    const rect = containedRect(
      imageRecords.base.naturalWidth,
      imageRecords.base.naturalHeight,
      bounds,
    );
    state.imageRect = rect;
    context.fillStyle = "#081012";
    context.fillRect(0, 0, elements.canvas.width, elements.canvas.height);
    context.imageSmoothingEnabled = true;
    context.drawImage(imageRecords.base, rect.x, rect.y, rect.width, rect.height);
    if (state.activityVisible && imageRecords.activity) {
      context.globalAlpha = 0.72;
      context.drawImage(imageRecords.activity, rect.x, rect.y, rect.width, rect.height);
      context.globalAlpha = 1;
    }
    context.globalAlpha = state.overlayOpacity;
    context.drawImage(imageRecords.overlay, rect.x, rect.y, rect.width, rect.height);
    context.globalAlpha = 1;
    drawSelectionMask(rect);
    context.strokeStyle = "#aab6b3";
    context.lineWidth = 1;
    context.strokeRect(rect.x, rect.y, rect.width, rect.height);
    drawScaleBar(rect);
  }

  function probeTransform() {
    const xMin = -8;
    const xMax = 72;
    const yMax = Math.max(
      ...viewer.rawChannels.map((channel) => channel.probeYUm),
      ...viewer.filters.map((filter) => filter.probeYUm),
    ) + 80;
    const bounds = { left: 145, right: 755, top: 38, bottom: 668 };
    return {
      bounds,
      x: (value) => bounds.left + (value - xMin) / (xMax - xMin) * (bounds.right - bounds.left),
      y: (value) => bounds.bottom - value / yMax * (bounds.bottom - bounds.top),
      yScale: (bounds.bottom - bounds.top) / yMax,
    };
  }

  function drawProbeViewer() {
    context.fillStyle = "#081012";
    context.fillRect(0, 0, elements.canvas.width, elements.canvas.height);
    const transform = probeTransform();
    const { bounds } = transform;
    const shaftLeft = transform.x(-4);
    const shaftRight = transform.x(68);
    context.fillStyle = "#111d1f";
    context.fillRect(shaftLeft, bounds.top, shaftRight - shaftLeft, bounds.bottom - bounds.top);
    context.strokeStyle = "#465355";
    context.lineWidth = 1;
    context.strokeRect(shaftLeft, bounds.top, shaftRight - shaftLeft, bounds.bottom - bounds.top);

    viewer.rawChannels.forEach((channel) => {
      const x = transform.x(channel.probeXUm);
      const y = transform.y(channel.probeYUm);
      const radius = 4 + channel.rawVariation * 9;
      const gradient = context.createRadialGradient(x, y, 0, x, y, radius * 2.2);
      gradient.addColorStop(0, `rgba(235, 246, 242, ${0.35 + channel.rawVariation * 0.6})`);
      gradient.addColorStop(0.32, `rgba(36, 188, 173, ${0.18 + channel.rawVariation * 0.48})`);
      gradient.addColorStop(1, "rgba(36, 188, 173, 0)");
      context.fillStyle = gradient;
      context.beginPath();
      context.arc(x, y, radius * 2.2, 0, Math.PI * 2);
      context.fill();
    });

    state.probeHits = [];
    viewer.filters.forEach((filter, index) => {
      if (state.qcOnly && !filter.isQcPassing) return;
      const x = transform.x(filter.probeXUm);
      const y = transform.y(filter.probeYUm);
      const radiusX = 9 + Math.min(filter.spreadUm, 160) * 0.055;
      const radiusY = Math.max(3, filter.spreadUm * transform.yScale * 0.55);
      const selected = index === state.selectedIndex;
      const color = filter.isQcPassing ? filterColor(index) : "#8d9996";
      context.strokeStyle = color;
      context.globalAlpha = selected ? 1 : state.overlayOpacity * (filter.isQcPassing ? 0.72 : 0.25);
      context.lineWidth = selected ? 3 : 1;
      context.beginPath();
      context.ellipse(x, y, selected ? radiusX * 1.35 : radiusX, selected ? radiusY * 1.35 : radiusY, 0, 0, Math.PI * 2);
      context.stroke();
      if (selected) {
        context.fillStyle = color;
        context.globalAlpha = 0.24;
        context.fill();
      }
      state.probeHits.push({ index, radiusX: Math.max(radiusX, 10), radiusY: Math.max(radiusY, 5), x, y });
    });
    context.globalAlpha = 1;

    for (let depth = 0; depth <= 4000; depth += 1000) {
      const y = transform.y(depth);
      context.strokeStyle = "#344143";
      context.beginPath();
      context.moveTo(shaftLeft, y);
      context.lineTo(shaftRight, y);
      context.stroke();
      drawCanvasText(`${depth} µm`, shaftLeft - 16, y + 4, {
        align: "right",
        color: "#aebbb8",
        size: 12,
      });
    }
    drawCanvasText("100 ms raw AP variation", (shaftLeft + shaftRight) / 2, 20, {
      align: "center",
      color: "#dbe5e3",
      size: 14,
      weight: 700,
    });
    drawCanvasText("Probe tip", shaftRight + 18, bounds.bottom, {
      color: "#aebbb8",
      size: 12,
    });
    drawCanvasText("Dorsal", shaftRight + 18, bounds.top + 8, {
      color: "#aebbb8",
      size: 12,
    });
  }

  function drawViewer() {
    if (viewer.viewType === "probe") drawProbeViewer();
    else drawImageViewer();
  }

  function canvasCoordinates(event) {
    const bounds = elements.canvas.getBoundingClientRect();
    return {
      x: (event.clientX - bounds.left) / bounds.width * elements.canvas.width,
      y: (event.clientY - bounds.top) / bounds.height * elements.canvas.height,
    };
  }

  function imageFilterAt(point) {
    const rect = state.imageRect;
    if (!rect || point.x < rect.x || point.x >= rect.x + rect.width || point.y < rect.y || point.y >= rect.y + rect.height) return -1;
    const sourceX = Math.floor((point.x - rect.x) / rect.width * state.labelPixels.width);
    const sourceY = Math.floor((point.y - rect.y) / rect.height * state.labelPixels.height);
    const offset = (sourceY * state.labelPixels.width + sourceX) * 4;
    const label = state.labelPixels.data[offset]
      + (state.labelPixels.data[offset + 1] << 8)
      + (state.labelPixels.data[offset + 2] << 16);
    if (label > 0) return label - 1;
    let nearest = -1;
    let nearestDistance = 14;
    viewer.filters.forEach((filter, index) => {
      const distance = Math.hypot(filter.centroidX - sourceX, filter.centroidY - sourceY);
      if (distance < nearestDistance) {
        nearest = index;
        nearestDistance = distance;
      }
    });
    return nearest;
  }

  function probeFilterAt(point) {
    let nearest = -1;
    let nearestDistance = 1.6;
    state.probeHits.forEach((hit) => {
      const distance = Math.hypot((point.x - hit.x) / hit.radiusX, (point.y - hit.y) / hit.radiusY);
      if (distance < nearestDistance) {
        nearest = hit.index;
        nearestDistance = distance;
      }
    });
    return nearest;
  }

  function filterAt(event) {
    const point = canvasCoordinates(event);
    return viewer.viewType === "probe" ? probeFilterAt(point) : imageFilterAt(point);
  }

  function showTooltip(event, index) {
    if (index < 0) {
      elements.tooltip.hidden = true;
      return;
    }
    const filter = viewer.filters[index];
    const detail = viewer.viewType === "probe"
      ? `${filter.location} · ${formatNumber(filter.depthUm, 0)} µm`
      : `${formatNumber(filter.pixelCount, 0)} pixels`;
    elements.tooltip.innerHTML = `<strong>${filter.label}</strong><br>${detail}`;
    elements.tooltip.hidden = false;
    elements.tooltip.style.left = `${Math.min(event.clientX + 14, window.innerWidth - 250)}px`;
    elements.tooltip.style.top = `${Math.min(event.clientY + 14, window.innerHeight - 70)}px`;
  }

  function metadataRows(filter) {
    if (viewer.id === "neuropixels") {
      return [
        ["QC", filter.isQcPassing ? "Passing" : "Not passing"],
        ["CCF area", filter.location],
        ["Depth", `${formatNumber(filter.depthUm, 0)} µm`],
        ["Peak channel", String(filter.peakChannel)],
        ["Firing rate", `${formatNumber(filter.firingRateHz, 2)} Hz`],
        ["SNR", formatNumber(filter.snr, 2)],
        ["Template spread", `${formatNumber(filter.spreadUm, 0)} µm`],
        ["Kilosort unit", String(filter.ksUnitId)],
      ];
    }
    if (viewer.id === "mesoscope") {
      const classification = filter.isSoma ? "Soma" : filter.isDendrite ? "Dendrite" : "Other";
      return [
        ["Class", classification],
        ["Pixels", formatNumber(filter.pixelCount, 0)],
        ["Soma probability", formatNumber(filter.somaProbability, 3)],
        ["Dendrite probability", formatNumber(filter.dendriteProbability, 3)],
        ["Centroid x", `${formatNumber(filter.centroidX * viewer.micronsPerPixel, 1)} µm`],
        ["Centroid y", `${formatNumber(filter.centroidY * viewer.micronsPerPixel, 1)} µm`],
      ];
    }
    return [
      ["Source", String(filter.id + 1)],
      ["Footprint pixels", formatNumber(filter.pixelCount, 0)],
      ["Centroid x", `${formatNumber(filter.centroidX * viewer.micronsPerPixel, 1)} µm`],
      ["Centroid y", `${formatNumber(filter.centroidY * viewer.micronsPerPixel, 1)} µm`],
      ["Imaging path", viewer.panelLabel],
      ["Signal", "iGluSnFR4f"],
    ];
  }

  function selectedTrace() {
    const start = state.selectedIndex * viewer.traceColumns;
    return traceValues.subarray(start, start + viewer.traceColumns);
  }

  function selectedWaveform() {
    if (!waveformValues) return null;
    const start = state.selectedIndex * viewer.waveformColumns;
    return waveformValues.subarray(start, start + viewer.waveformColumns);
  }

  function lineChart(svg, times, sourceValues, options = {}) {
    const width = 640;
    const height = options.height || 230;
    const margin = { left: 66, right: 18, top: 24, bottom: 43 };
    const finite = Array.from(sourceValues).filter(Number.isFinite);
    let yMin = Math.min(...finite);
    let yMax = Math.max(...finite);
    if (yMin === yMax) {
      yMin -= 1;
      yMax += 1;
    }
    const padding = (yMax - yMin) * 0.08;
    yMin -= padding;
    yMax += padding;
    const xMin = times[0];
    const xMax = times[times.length - 1];
    const x = (value) => margin.left + (value - xMin) / (xMax - xMin) * (width - margin.left - margin.right);
    const y = (value) => margin.top + (yMax - value) / (yMax - yMin) * (height - margin.top - margin.bottom);
    const stride = Math.max(1, Math.ceil(sourceValues.length / 900));
    const pathParts = [];
    for (let index = 0; index < sourceValues.length; index += stride) {
      const value = sourceValues[index];
      if (!Number.isFinite(value)) {
        pathParts.push(null);
        continue;
      }
      const previous = pathParts[pathParts.length - 1];
      pathParts.push(`${previous === null || pathParts.length === 0 ? "M" : "L"}${x(times[index]).toFixed(2)},${y(value).toFixed(2)}`);
    }
    const path = pathParts.filter(Boolean).join(" ");
    const grid = [0, 0.5, 1].map((fraction) => {
      const gridY = margin.top + fraction * (height - margin.top - margin.bottom);
      const value = yMax - fraction * (yMax - yMin);
      return `<line class="chart-grid" x1="${margin.left}" y1="${gridY}" x2="${width - margin.right}" y2="${gridY}"/><text class="chart-label" x="${margin.left - 10}" y="${gridY + 6}" text-anchor="end">${formatNumber(value, options.yDigits ?? 2)}</text>`;
    }).join("");
    const xTicks = [0, 0.5, 1].map((fraction) => {
      const value = xMin + fraction * (xMax - xMin);
      const tickX = x(value);
      return `<text class="chart-label" x="${tickX}" y="${height - 12}" text-anchor="middle">${formatNumber(value, options.xDigits ?? 1)} ${options.xUnit || "s"}</text>`;
    }).join("");
    const event = options.eventTime !== undefined && options.eventTime >= xMin && options.eventTime <= xMax
      ? `<line class="chart-event" x1="${x(options.eventTime)}" y1="${margin.top}" x2="${x(options.eventTime)}" y2="${height - margin.bottom}"/><text class="chart-event-label" x="${x(options.eventTime) + 7}" y="${margin.top + 17}">${options.eventLabel}</text>`
      : "";
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.innerHTML = `${grid}<line class="chart-axis" x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}"/>${event}<path class="chart-trace" style="stroke:${options.color || filterColor(state.selectedIndex)}" d="${path}"/>${xTicks}`;
    svg.setAttribute("aria-label", options.ariaLabel || "Selected filter trace");
  }

  function renderSelection() {
    const filter = currentFilter();
    const color = filterColor(state.selectedIndex);
    elements.selectionTitle.textContent = filter.label;
    elements.selectionSwatch.style.background = color;
    elements.filterSelect.value = String(state.selectedIndex);
    elements.filterMetadata.innerHTML = metadataRows(filter)
      .map(([term, value]) => `<div><dt>${term}</dt><dd title="${value}">${value}</dd></div>`)
      .join("");
    elements.traceTitle.textContent = viewer.traceLabel;
    const traceTimes = viewer.traceTimesSeconds;
    elements.traceWindow.textContent = `${formatNumber(traceTimes[0], 1)}–${formatNumber(traceTimes[traceTimes.length - 1], 1)} s`;
    lineChart(elements.activityChart, traceTimes, selectedTrace(), {
      ariaLabel: `${filter.label} ${viewer.traceLabel}`,
      color,
      eventLabel: viewer.eventLabel,
      eventTime: viewer.eventLabel ? 0 : undefined,
      yDigits: viewer.id === "neuropixels" ? 0 : 2,
    });

    const waveform = selectedWaveform();
    if (waveform) {
      elements.waveformSection.hidden = false;
      let troughIndex = 0;
      for (let index = 1; index < waveform.length; index += 1) {
        if (waveform[index] < waveform[troughIndex]) troughIndex = index;
      }
      const waveformTimes = Array.from(
        waveform,
        (_, index) => (index - troughIndex) / viewer.waveformSampleRateHz * 1000,
      );
      lineChart(elements.waveformChart, waveformTimes, waveform, {
        ariaLabel: `${filter.label} peak-channel mean template waveform`,
        color,
        height: 190,
        xDigits: 1,
        xUnit: "ms",
        yDigits: 2,
      });
    }
    drawViewer();
  }

  function selectFilter(index) {
    if (index < 0 || index >= viewer.filters.length) return;
    if (state.qcOnly && !viewer.filters[index].isQcPassing) return;
    state.selectedIndex = index;
    renderSelection();
  }

  function adjacentFilter(direction) {
    let index = state.selectedIndex;
    for (let attempt = 0; attempt < viewer.filters.length; attempt += 1) {
      index = (index + direction + viewer.filters.length) % viewer.filters.length;
      if (!state.qcOnly || viewer.filters[index].isQcPassing) {
        selectFilter(index);
        return;
      }
    }
  }

  function populateFilterSelect() {
    elements.filterSelect.innerHTML = viewer.filters.map((filter, index) => {
      const suffix = viewer.id === "neuropixels" && !filter.isQcPassing ? " · non-QC" : "";
      return `<option value="${index}">${filter.label}${suffix}</option>`;
    }).join("");
  }

  function configureControls() {
    populateFilterSelect();
    if (viewer.activityImage) {
      elements.activityControl.hidden = false;
      elements.activityKey.hidden = false;
    }
    if (viewer.id === "neuropixels") {
      elements.qcControl.hidden = false;
      elements.qcKey.hidden = false;
    }
    elements.filterSelect.addEventListener("change", () => selectFilter(Number(elements.filterSelect.value)));
    elements.opacity.addEventListener("input", () => {
      state.overlayOpacity = Number(elements.opacity.value) / 100;
      drawViewer();
    });
    elements.activityToggle.addEventListener("change", () => {
      state.activityVisible = elements.activityToggle.checked;
      drawViewer();
    });
    elements.qcToggle.addEventListener("change", () => {
      state.qcOnly = elements.qcToggle.checked;
      if (state.qcOnly && !currentFilter().isQcPassing) adjacentFilter(1);
      else drawViewer();
    });
    elements.previousFilter.addEventListener("click", () => adjacentFilter(-1));
    elements.nextFilter.addEventListener("click", () => adjacentFilter(1));
    elements.canvas.addEventListener("click", (event) => selectFilter(filterAt(event)));
    elements.canvas.addEventListener("pointermove", (event) => showTooltip(event, filterAt(event)));
    elements.canvas.addEventListener("pointerleave", () => { elements.tooltip.hidden = true; });
    elements.canvas.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft") adjacentFilter(-1);
      if (event.key === "ArrowRight") adjacentFilter(1);
    });
  }

  async function initialize() {
    configureControls();
    if (viewer.viewType === "image") {
      await Promise.all([
        loadImage(viewer.baseImage, "base"),
        loadImage(viewer.activityImage, "activity"),
        loadImage(viewer.labelImage, "labels"),
        loadImage(viewer.filterOverlay, "overlay"),
      ]);
      buildLabelPixels();
    }
    elements.loading.hidden = true;
    renderSelection();
  }

  initialize().catch((error) => {
    elements.loading.hidden = false;
    elements.loading.textContent = "Viewer assets unavailable";
    throw error;
  });
})();