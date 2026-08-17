(() => {
  "use strict";

  const protocol = JSON.parse(document.getElementById("segmentation-data").textContent);
  const colors = ["#25aae1", "#8cc63f", "#ccaf2d", "#d65c48", "#24bcad", "#b160a9"];
  const modalityAccents = {
    neuropixels: "#3157b7",
    mesoscope: "#168f78",
    slap2: "#b16027",
  };
  const viewerTitles = {
    neuropixels: "Neuropixels unit-template viewer",
    mesoscope: "Mesoscope ROI segmentation viewer",
    slap2: "SLAP2 source-segmentation viewer",
  };
  const elements = {
    activityChart: document.getElementById("activity-chart"),
    background: document.getElementById("background-intensity"),
    backgroundLabel: document.getElementById("background-label"),
    canvas: document.getElementById("source-canvas"),
    commonModeControl: document.getElementById("common-mode-control"),
    commonModeToggle: document.getElementById("common-mode-toggle"),
    filterMetadata: document.getElementById("filter-metadata"),
    filterSelect: document.getElementById("filter-select"),
    loading: document.getElementById("loading-status"),
    interactiveView: document.getElementById("interactive-view"),
    modalitySelector: document.getElementById("modality-selector"),
    nextFilter: document.getElementById("next-filter"),
    previousFilter: document.getElementById("previous-filter"),
    selectionSwatch: document.getElementById("selection-swatch"),
    selectionTitle: document.getElementById("selection-title"),
    staticView: document.getElementById("static-view"),
    sourceLabel: document.getElementById("source-label"),
    sourceLink: document.getElementById("source-link"),
    sourceSelect: document.getElementById("source-select"),
    tooltip: document.getElementById("canvas-tooltip"),
    traceTitle: document.getElementById("trace-title"),
    waveformChart: document.getElementById("waveform-chart"),
    waveformSection: document.getElementById("waveform-section"),
    viewer: document.getElementById("segmentation-viewer"),
    viewerTitle: document.getElementById("viewer-title"),
    viewButtons: document.querySelectorAll(".view-button"),
  };
  const context = elements.canvas.getContext("2d");
  const decodedViewers = protocol.viewers.map((modality) => modality.sources.map((record) => ({
    raw: record.rawDataBase64 ? decodeUint8(record.rawDataBase64) : null,
    traces: decodeFloat32(record.traceDataBase64),
    waveforms: record.waveformDataBase64 ? decodeFloat32(record.waveformDataBase64) : null,
  })));
  const viewerStates = protocol.viewers.map((modality) => modality.sources.map((record) => ({
    backgroundIntensity: 1,
    commonModeCorrected: record.viewType === "spike-map",
    imageRect: null,
    labelPixels: null,
    selectedIndex: record.defaultFilterIndex,
    spikeHits: [],
  })));
  const activeSourceIndices = protocol.viewers.map(() => 0);
  let activeViewerIndex = 0;
  let modality = protocol.viewers[0];
  let viewer = modality.sources[0];
  let traceValues = decodedViewers[0][0].traces;
  let waveformValues = decodedViewers[0][0].waveforms;
  let rawValues = decodedViewers[0][0].raw;
  let imageRecords = {};
  let viewerLoadToken = 0;
  const rawHeatmapCanvas = document.createElement("canvas");
  const rawHeatmapContext = rawHeatmapCanvas.getContext("2d");
  let rawHeatmapKey = null;
  let state = viewerStates[0][0];

  function selectView(view) {
    elements.interactiveView.hidden = view !== "interactive";
    elements.staticView.hidden = view !== "static";
    elements.viewButtons.forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function decodeFloat32(encoded) {
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new Float32Array(bytes.buffer);
  }

  function decodeUint8(encoded) {
    const binary = atob(encoded);
    const values = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      values[index] = binary.charCodeAt(index);
    }
    return values;
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

  function loadImage(record) {
    if (!record) return Promise.resolve(null);
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.addEventListener("load", () => resolve(image));
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
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, elements.canvas.width, elements.canvas.height);
    context.imageSmoothingEnabled = true;
    context.filter = `brightness(${state.backgroundIntensity})`;
    context.drawImage(imageRecords.base, rect.x, rect.y, rect.width, rect.height);
    context.filter = "none";
    context.imageSmoothingEnabled = false;
    context.globalAlpha = 1;
    context.drawImage(imageRecords.overlay, rect.x, rect.y, rect.width, rect.height);
    drawSelectionMask(rect);
    context.strokeStyle = "#aab6b3";
    context.lineWidth = 1;
    context.strokeRect(rect.x, rect.y, rect.width, rect.height);
    drawScaleBar(rect);
  }

  function rawHeatmap() {
    const cacheKey = `${state.backgroundIntensity}:${state.commonModeCorrected}`;
    if (rawHeatmapKey === cacheKey) return rawHeatmapCanvas;
    rawHeatmapCanvas.width = viewer.rawColumns;
    rawHeatmapCanvas.height = viewer.rawRows;
    const image = rawHeatmapContext.createImageData(viewer.rawColumns, viewer.rawRows);
    const commonMode = new Float32Array(viewer.rawColumns);
    if (state.commonModeCorrected) {
      const column = new Array(viewer.rawRows);
      for (let columnIndex = 0; columnIndex < viewer.rawColumns; columnIndex += 1) {
        for (let row = 0; row < viewer.rawRows; row += 1) {
          column[row] = rawValues[row * viewer.rawColumns + columnIndex];
        }
        column.sort((left, right) => left - right);
        const midpoint = viewer.rawRows / 2;
        commonMode[columnIndex] = viewer.rawRows % 2
          ? column[Math.floor(midpoint)]
          : (column[midpoint - 1] + column[midpoint]) / 2;
      }
    }
    for (let index = 0; index < rawValues.length; index += 1) {
      const columnIndex = index % viewer.rawColumns;
      const centered = state.commonModeCorrected
        ? rawValues[index] - commonMode[columnIndex]
        : rawValues[index] - 127.5;
      const gray = Math.max(
        0,
        Math.min(255, Math.round(127.5 + centered * state.backgroundIntensity)),
      );
      const offset = index * 4;
      image.data[offset] = gray;
      image.data[offset + 1] = gray;
      image.data[offset + 2] = gray;
      image.data[offset + 3] = 255;
    }
    rawHeatmapContext.putImageData(image, 0, 0);
    rawHeatmapKey = cacheKey;
    return rawHeatmapCanvas;
  }

  function spikeMapLayout() {
    const plot = { left: 88, right: 872, top: 42, bottom: 650 };
    return {
      plot,
      x: (timeMs) => plot.left + (timeMs - viewer.rawTimeStartMs)
        / (viewer.rawTimeEndMs - viewer.rawTimeStartMs) * (plot.right - plot.left),
      y: (row) => plot.top + (row + 0.5) / viewer.rawRows * (plot.bottom - plot.top),
    };
  }

  function drawSpikeMap() {
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, elements.canvas.width, elements.canvas.height);
    const layout = spikeMapLayout();
    const { plot } = layout;
    context.imageSmoothingEnabled = false;
    context.drawImage(
      rawHeatmap(),
      plot.left,
      plot.top,
      plot.right - plot.left,
      plot.bottom - plot.top,
    );

    const selected = currentFilter();
    const selectedY = layout.y(selected.rawRow);
    const bandHeight = Math.max(
      5,
      selected.spreadUm / (viewer.rawDepthMaxUm - viewer.rawDepthMinUm)
        * (plot.bottom - plot.top),
    );
    context.fillStyle = filterColor(state.selectedIndex);
    context.globalAlpha = 0.2;
    context.fillRect(plot.left, selectedY - bandHeight / 2, plot.right - plot.left, bandHeight);
    context.globalAlpha = 1;
    context.strokeStyle = filterColor(state.selectedIndex);
    context.lineWidth = 1.5;
    context.beginPath();
    context.moveTo(plot.left, selectedY);
    context.lineTo(plot.right, selectedY);
    context.stroke();

    state.spikeHits = [];
    viewer.spikeEvents.forEach((event) => {
      const x = layout.x(event.timeMs);
      const y = layout.y(event.row);
      const isSelected = event.filterIndex === state.selectedIndex;
      const radius = isSelected ? 5 : 2.5;
      context.fillStyle = filterColor(event.filterIndex);
      context.globalAlpha = isSelected ? 1 : 0.82;
      context.beginPath();
      context.arc(x, y, radius, 0, Math.PI * 2);
      context.fill();
      if (isSelected) {
        context.strokeStyle = "#ffffff";
        context.lineWidth = 1.5;
        context.stroke();
      }
      state.spikeHits.push({ filterIndex: event.filterIndex, radius: Math.max(radius, 7), x, y });
    });
    context.globalAlpha = 1;

    context.strokeStyle = "#9ba7a4";
    context.lineWidth = 1;
    context.strokeRect(plot.left, plot.top, plot.right - plot.left, plot.bottom - plot.top);
    for (let index = 0; index <= 4; index += 1) {
      const fraction = index / 4;
      const x = plot.left + fraction * (plot.right - plot.left);
      const time = viewer.rawTimeStartMs
        + fraction * (viewer.rawTimeEndMs - viewer.rawTimeStartMs);
      context.beginPath();
      context.moveTo(x, plot.bottom);
      context.lineTo(x, plot.bottom + 6);
      context.stroke();
      drawCanvasText(`${formatNumber(time, 0)}`, x, plot.bottom + 22, {
        align: "center",
        color: "#68716f",
        size: 12,
      });
    }
    for (let index = 0; index <= 4; index += 1) {
      const fraction = index / 4;
      const y = plot.top + fraction * (plot.bottom - plot.top);
      const depth = viewer.rawDepthMaxUm
        - fraction * (viewer.rawDepthMaxUm - viewer.rawDepthMinUm);
      context.beginPath();
      context.moveTo(plot.left - 6, y);
      context.lineTo(plot.left, y);
      context.stroke();
      drawCanvasText(`${formatNumber(depth, 0)}`, plot.left - 10, y + 4, {
        align: "right",
        color: "#68716f",
        size: 12,
      });
    }
    const voltageLabel = state.commonModeCorrected
      ? "Common-mode-corrected AP voltage"
      : "Raw AP voltage";
    drawCanvasText(`${voltageLabel} + detected sorted spikes`, (plot.left + plot.right) / 2, 23, {
      align: "center",
      color: "#293133",
      size: 14,
      weight: 700,
    });
    drawCanvasText("Excerpt time (ms)", (plot.left + plot.right) / 2, 697, {
      align: "center",
      color: "#68716f",
      size: 12,
    });
    context.save();
    context.translate(20, (plot.top + plot.bottom) / 2);
    context.rotate(-Math.PI / 2);
    drawCanvasText("Probe length from tip (µm)", 0, 0, {
      align: "center",
      color: "#68716f",
      size: 12,
    });
    context.restore();
  }

  function drawViewer() {
    if (viewer.viewType === "spike-map") drawSpikeMap();
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

  function spikeFilterAt(point) {
    let nearest = -1;
    let nearestDistance = 12;
    state.spikeHits.forEach((hit) => {
      const distance = Math.hypot(point.x - hit.x, point.y - hit.y);
      if (distance < nearestDistance) {
        nearest = hit.filterIndex;
        nearestDistance = distance;
      }
    });
    return nearest;
  }

  function filterAt(event) {
    const point = canvasCoordinates(event);
    return viewer.viewType === "spike-map" ? spikeFilterAt(point) : imageFilterAt(point);
  }

  function showTooltip(event, index) {
    if (index < 0) {
      elements.tooltip.hidden = true;
      return;
    }
    const filter = viewer.filters[index];
    const detail = viewer.viewType === "spike-map"
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
        ["CCF area", filter.location],
        ["Depth", `${formatNumber(filter.depthUm, 0)} µm`],
        ["Peak channel", String(filter.peakChannel)],
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
    const values = traceValues.subarray(start, start + viewer.traceColumns);
    const scale = viewer.traceScale || 1;
    return scale === 1 ? values : Float32Array.from(values, (value) => value * scale);
  }

  function selectedWaveform() {
    if (!waveformValues) return null;
    const start = state.selectedIndex * viewer.waveformColumns;
    return waveformValues.subarray(start, start + viewer.waveformColumns);
  }

  function lineChart(svg, times, sourceValues, options = {}) {
    const width = 640;
    const height = options.height || 230;
    const margin = { left: 96, right: 40, top: 24, bottom: 43 };
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
      const suffix = options.yUnit === "%" ? "%" : "";
      return `<line class="chart-grid" x1="${margin.left}" y1="${gridY}" x2="${width - margin.right}" y2="${gridY}"/><line class="chart-tick" x1="${margin.left - 6}" y1="${gridY}" x2="${margin.left}" y2="${gridY}"/><text class="chart-label" x="${margin.left - 10}" y="${gridY + 6}" text-anchor="end">${formatNumber(value, options.yDigits ?? 2)}${suffix}</text>`;
    }).join("");
    const xTicks = [0, 0.5, 1].map((fraction) => {
      const value = xMin + fraction * (xMax - xMin);
      const tickX = x(value);
      return `<line class="chart-tick" x1="${tickX}" y1="${height - margin.bottom}" x2="${tickX}" y2="${height - margin.bottom + 6}"/><text class="chart-label" x="${tickX}" y="${height - 12}" text-anchor="middle">${formatNumber(value, options.xDigits ?? 1)} ${options.xUnit || "s"}</text>`;
    }).join("");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.innerHTML = `${grid}<line class="chart-axis" x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}"/><path class="chart-trace" style="stroke:${options.color || filterColor(state.selectedIndex)}" d="${path}"/>${xTicks}`;
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
    lineChart(elements.activityChart, traceTimes, selectedTrace(), {
      ariaLabel: `${filter.label} ${viewer.traceLabel}`,
      color,
      yDigits: viewer.id === "neuropixels" ? 0 : 2,
      yUnit: viewer.traceUnit,
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
    state.selectedIndex = index;
    renderSelection();
  }

  function adjacentFilter(direction) {
    const index = (
      state.selectedIndex + direction + viewer.filters.length
    ) % viewer.filters.length;
    selectFilter(index);
  }

  function populateFilterSelect() {
    elements.filterSelect.innerHTML = viewer.filters.map((filter, index) => {
      return `<option value="${index}">${filter.label}</option>`;
    }).join("");
  }

  function renderModalityTabs() {
    elements.modalitySelector.innerHTML = protocol.viewers.map((record, index) => (
      `<button class="modality-tab${index === activeViewerIndex ? " active" : ""}" `
      + `type="button" role="tab" data-viewer-index="${index}" `
      + `aria-selected="${index === activeViewerIndex}" `
      + `style="--tab-accent:${modalityAccents[record.id]}">`
      + `<img class="modality-logo" src="${record.logo}" alt="">`
      + `<span>${record.label}</span>`
      + "</button>"
    )).join("");
    elements.modalitySelector.querySelectorAll(".modality-tab").forEach((button) => {
      button.addEventListener("click", () => activateModality(Number(button.dataset.viewerIndex)));
    });
  }

  function populateSourceSelect() {
    elements.sourceSelect.innerHTML = modality.sources.map((record, index) => (
      `<option value="${index}">${record.label}</option>`
    )).join("");
    elements.sourceSelect.value = String(activeSourceIndices[activeViewerIndex]);
  }

  function updateViewerChrome() {
    elements.viewer.dataset.modality = modality.id;
    elements.viewerTitle.textContent = viewerTitles[modality.id];
    elements.sourceLabel.textContent = modality.sourceLabel;
    elements.sourceLink.href = viewer.asset.dandiset_url;
    elements.canvas.setAttribute("aria-label", `${viewerTitles[modality.id]} filter map`);
    document.title = `Unit extraction · ${modality.label}`;

    elements.waveformSection.hidden = !viewer.waveformDataBase64;
    elements.backgroundLabel.textContent = modality.id === "neuropixels"
      ? "Raw AP contrast"
      : "Background intensity";
    elements.background.value = String(Math.round(state.backgroundIntensity * 100));
    elements.commonModeControl.hidden = modality.id !== "neuropixels";
    elements.commonModeToggle.checked = state.commonModeCorrected;
    elements.tooltip.hidden = true;
    populateSourceSelect();
    populateFilterSelect();
  }

  async function activateSource(index) {
    if (index < 0 || index >= modality.sources.length) return;
    activeSourceIndices[activeViewerIndex] = index;
    viewer = modality.sources[index];
    state = viewerStates[activeViewerIndex][index];
    traceValues = decodedViewers[activeViewerIndex][index].traces;
    waveformValues = decodedViewers[activeViewerIndex][index].waveforms;
    rawValues = decodedViewers[activeViewerIndex][index].raw;
    imageRecords = {};
    rawHeatmapKey = null;
    const token = ++viewerLoadToken;
    updateViewerChrome();
    elements.selectionTitle.textContent = "Loading…";
    elements.filterMetadata.innerHTML = "";
    elements.traceTitle.textContent = viewer.traceLabel;
    elements.activityChart.innerHTML = "";
    elements.waveformChart.innerHTML = "";

    if (viewer.viewType === "image") {
      elements.loading.hidden = false;
      elements.loading.textContent = "Loading source image";
      const [base, labels, overlay] = await Promise.all([
        loadImage(viewer.baseImage),
        loadImage(viewer.labelImage),
        loadImage(viewer.filterOverlay),
      ]);
      if (token !== viewerLoadToken) return;
      imageRecords = { base, labels, overlay };
      buildLabelPixels();
    }
    if (token !== viewerLoadToken) return;
    elements.loading.hidden = true;
    renderSelection();
  }

  async function activateModality(index) {
    if (index < 0 || index >= protocol.viewers.length) return;
    activeViewerIndex = index;
    modality = protocol.viewers[index];
    renderModalityTabs();
    await activateSource(activeSourceIndices[index]);
  }

  function configureControls() {
    elements.viewButtons.forEach((button) => {
      button.addEventListener("click", () => selectView(button.dataset.view));
    });
    elements.sourceSelect.addEventListener("change", () => {
      activateSource(Number(elements.sourceSelect.value));
    });
    elements.filterSelect.addEventListener("change", () => selectFilter(Number(elements.filterSelect.value)));
    elements.background.addEventListener("input", () => {
      state.backgroundIntensity = Number(elements.background.value) / 100;
      drawViewer();
    });
    elements.commonModeToggle.addEventListener("change", () => {
      state.commonModeCorrected = elements.commonModeToggle.checked;
      rawHeatmapKey = null;
      drawViewer();
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
    selectView("interactive");
    await activateModality(0);
  }

  initialize().catch((error) => {
    elements.loading.hidden = false;
    elements.loading.textContent = "Viewer assets unavailable";
    throw error;
  });
})();