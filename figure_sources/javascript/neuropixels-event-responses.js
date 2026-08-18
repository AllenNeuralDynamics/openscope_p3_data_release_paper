(() => {
  "use strict";

  const data = JSON.parse(
    document.getElementById("neuropixels-event-data").textContent,
  );
  const time = data.analysisParameters.timeBinCentersSeconds;
  const binSeconds = data.analysisParameters.binSeconds;
  const contextOrder = ["standard", "sensorimotor", "sequence", "duration"];
  const contextLabels = {
    standard: "Standard oddball",
    sensorimotor: "Sensorimotor",
    sequence: "Sequence",
    duration: "Duration",
  };
  const contextColors = {
    standard: "#22bcad",
    sensorimotor: "#283185",
    sequence: "#b16027",
    duration: "#ccaf2d",
  };
  const state = {
    area: "all",
    colorPercent: 100,
    context: "standard",
    eventIndex: 0,
    metric: "difference",
    probe: "all",
    qc: "qc",
    scope: "area",
    selectedUnit: null,
    sort: "response",
    view: "interactive",
    sortedUnits: [],
  };
  const atlasCache = new Map();

  const contextTabs = document.getElementById("context-tabs");
  const eventSelect = document.getElementById("event-select");
  const probeSelect = document.getElementById("probe-select");
  const areaSelect = document.getElementById("area-select");
  const qcTabs = document.getElementById("qc-tabs");
  const scopeTabs = document.getElementById("scope-tabs");
  const responseSelectionLabel = document.getElementById(
    "response-selection-label",
  );
  const unitSelect = document.getElementById("unit-select");
  const metricTabs = document.getElementById("metric-tabs");
  const sortSelect = document.getElementById("sort-select");
  const colorLimit = document.getElementById("color-limit");
  const colorLimitValue = document.getElementById("color-limit-value");
  const unitCount = document.getElementById("unit-count");
  const heatmapCanvas = document.getElementById("heatmap-canvas");
  const heatmapTooltip = document.getElementById("heatmap-tooltip");
  const heatmapDetail = document.getElementById("heatmap-detail");
  const colorKey = document.getElementById("color-key");
  const loadingMessage = document.getElementById("loading-message");
  const responseCanvas = document.getElementById("response-canvas");
  const responseTitle = document.getElementById("response-title");
  const unitTitle = document.getElementById("unit-title");
  const unitMetadata = document.getElementById("unit-metadata");
  const waveformCanvas = document.getElementById("waveform-canvas");
  const sourceNote = document.getElementById("source-note");
  const interactiveView = document.getElementById("interactive-view");
  const staticView = document.getElementById("static-view");

  function currentSession() {
    return data.sessions.find((session) => session.context === state.context);
  }

  function decodeFloat32Base64(encoded) {
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new Float32Array(bytes.buffer);
  }

  async function fetchGzip(path) {
    const response = await fetch(path);
    if (!response.ok || !response.body) {
      throw new Error(`Could not load response atlas: ${path}`);
    }
    if (typeof DecompressionStream === "undefined") {
      throw new Error("This browser does not support gzip decompression.");
    }
    return new Response(
      response.body.pipeThrough(new DecompressionStream("gzip")),
    ).arrayBuffer();
  }

  async function loadAtlas(session) {
    if (!atlasCache.has(session.context)) {
      atlasCache.set(
        session.context,
        Promise.all([
          fetchGzip(session.countAtlas.path),
          fetchGzip(session.waveformAtlas.path),
        ]).then(([countBuffer, waveformBuffer]) => ({
          baselineMean: decodeFloat32Base64(session.baselineMeanHzBase64),
          baselineStd: decodeFloat32Base64(session.baselineStdHzBase64),
          counts: new Uint16Array(countBuffer),
          responseDelta: decodeFloat32Base64(session.responseDeltaHzBase64),
          responseContext: decodeFloat32Base64(session.responseContextHzBase64),
          responseControl: decodeFloat32Base64(session.responseControlHzBase64),
          waveforms: new Int8Array(waveformBuffer),
        })),
      );
    }
    return atlasCache.get(session.context);
  }

  function button(label, pressed, click) {
    const element = document.createElement("button");
    element.type = "button";
    element.textContent = label;
    element.setAttribute("aria-pressed", String(pressed));
    element.addEventListener("click", click);
    return element;
  }

  function renderContextTabs() {
    contextTabs.replaceChildren();
    for (const context of contextOrder) {
      if (!data.sessions.some((session) => session.context === context)) continue;
      const element = button(
        contextLabels[context],
        context === state.context,
        () => {
          state.context = context;
          state.eventIndex = 0;
          state.area = "all";
          state.probe = "all";
          state.selectedUnit = null;
          configureSession();
        },
      );
      element.dataset.context = context;
      contextTabs.append(element);
    }
  }

  function renderEventSelect() {
    const session = currentSession();
    eventSelect.replaceChildren();
    session.events.forEach((event, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = event.label;
      eventSelect.append(option);
    });
    eventSelect.value = String(state.eventIndex);
  }

  function renderProbeSelect() {
    const session = currentSession();
    const probes = [...new Set(session.units.map((unit) => unit.probe))].sort();
    probeSelect.replaceChildren();
    for (const [value, label] of [
      ["all", "All probes"],
      ...probes.map((probe) => [probe, probe.replace("Probe", "Probe ")]),
    ]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      probeSelect.append(option);
    }
    if (![...probeSelect.options].some((option) => option.value === state.probe)) {
      state.probe = "all";
    }
    probeSelect.value = state.probe;
  }

  function areaSourceUnits() {
    const session = currentSession();
    return session.units.filter(
      (unit) =>
        (state.probe === "all" || unit.probe === state.probe) &&
        (state.qc === "all" || unit.qcPass),
    );
  }

  function renderAreaSelect() {
    const areas = [...new Set(areaSourceUnits().map((unit) => unit.location))].sort();
    areaSelect.replaceChildren();
    for (const [value, label] of [
      ["all", "All areas"],
      ...areas.map((area) => [area, area]),
    ]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      areaSelect.append(option);
    }
    if (![...areaSelect.options].some((option) => option.value === state.area)) {
      state.area = "all";
    }
    areaSelect.value = state.area;
  }

  function renderResponseSelection() {
    const individual = state.scope === "unit";
    responseSelectionLabel.textContent = individual ? "Unit" : "Area";
    areaSelect.hidden = individual;
    unitSelect.hidden = !individual;
  }

  function filteredUnitIndices() {
    const session = currentSession();
    return session.units
      .map((unit, index) => ({ unit, index }))
      .filter(
        ({ unit }) =>
          (state.probe === "all" || unit.probe === state.probe) &&
          (state.area === "all" || unit.location === state.area) &&
          (state.qc === "all" || unit.qcPass),
      )
      .map(({ index }) => index);
  }

  function responseValue(atlas, unitIndex) {
    const session = currentSession();
    return atlas.responseDelta[state.eventIndex * session.unitCount + unitIndex];
  }

  function sortedUnitIndices(atlas) {
    const session = currentSession();
    const indices = filteredUnitIndices();
    return indices.sort((left, right) => {
      if (state.sort === "depth") {
        const leftUnit = session.units[left];
        const rightUnit = session.units[right];
        return (
          leftUnit.probe.localeCompare(rightUnit.probe) ||
          leftUnit.depthUm - rightUnit.depthUm
        );
      }
      if (state.sort === "unit") {
        return session.units[left].id - session.units[right].id;
      }
      return Math.abs(responseValue(atlas, right)) - Math.abs(responseValue(atlas, left));
    });
  }

  function renderUnitSelect() {
    const session = currentSession();
    const units = state.sortedUnits;
    if (!units.includes(state.selectedUnit)) state.selectedUnit = units[0] ?? null;
    unitSelect.replaceChildren();
    for (const unitIndex of units) {
      const unit = session.units[unitIndex];
      const option = document.createElement("option");
      option.value = String(unitIndex);
      option.textContent = `Unit ${unit.id} · ${unit.probe} · ${unit.location}`;
      unitSelect.append(option);
    }
    unitSelect.value = state.selectedUnit === null ? "" : String(state.selectedUnit);
  }

  function countIndex(eventIndex, conditionIndex, unitIndex, binIndex) {
    const session = currentSession();
    const binCount = time.length;
    return (
      (((eventIndex * 2 + conditionIndex) * session.unitCount + unitIndex) *
        binCount) +
      binIndex
    );
  }

  function gaussianKernel() {
    const sigmaBins =
      data.analysisParameters.smoothingSigmaSeconds /
      data.analysisParameters.binSeconds;
    const radius = Math.ceil(sigmaBins * 3);
    const weights = [];
    for (let offset = -radius; offset <= radius; offset += 1) {
      weights.push(Math.exp(-0.5 * (offset / sigmaBins) ** 2));
    }
    const total = weights.reduce((sum, value) => sum + value, 0);
    return weights.map((value) => value / total);
  }

  const smoothingKernel = gaussianKernel();

  function smooth(values) {
    const radius = Math.floor(smoothingKernel.length / 2);
    return values.map((_, index) => {
      let sum = 0;
      let weightSum = 0;
      smoothingKernel.forEach((weight, kernelIndex) => {
        const source = index + kernelIndex - radius;
        if (source >= 0 && source < values.length) {
          sum += values[source] * weight;
          weightSum += weight;
        }
      });
      return sum / weightSum;
    });
  }

  function unitRateTrace(atlas, unitIndex, conditionIndex) {
    const event = currentSession().events[state.eventIndex];
    const trials =
      conditionIndex === 0 ? event.contextTrialCount : event.controlTrialCount;
    const values = time.map(
      (_, binIndex) =>
        atlas.counts[
          countIndex(state.eventIndex, conditionIndex, unitIndex, binIndex)
        ] /
        trials /
        binSeconds,
    );
    return smooth(values);
  }

  function unitHeatmapTrace(atlas, unitIndex) {
    const context = unitRateTrace(atlas, unitIndex, 0);
    if (state.metric === "difference") {
      const control = unitRateTrace(atlas, unitIndex, 1);
      return context.map((value, index) => value - control[index]);
    }
    const session = currentSession();
    const offset = state.eventIndex * session.unitCount + unitIndex;
    const mean = atlas.baselineMean[offset];
    const std = atlas.baselineStd[offset];
    if (!Number.isFinite(mean) || !Number.isFinite(std) || std <= 0) {
      return context.map(() => null);
    }
    return context.map((value) => (value - mean) / std);
  }

  function color(value, limit) {
    if (value === null || !Number.isFinite(value)) return [225, 228, 227];
    const normalized = Math.max(-1, Math.min(1, value / limit));
    const cold = [59, 76, 192];
    const neutral = [247, 247, 247];
    const warm = [180, 4, 38];
    const target = normalized < 0 ? cold : warm;
    const amount = Math.abs(normalized);
    return neutral.map((channel, index) =>
      Math.round(channel + (target[index] - channel) * amount),
    );
  }

  function automaticLimit(traces) {
    const sample = [];
    const stride = Math.max(1, Math.floor(traces.length / 250));
    for (let row = 0; row < traces.length; row += stride) {
      for (const value of traces[row]) {
        if (value !== null && Number.isFinite(value)) sample.push(Math.abs(value));
      }
    }
    if (!sample.length) return 1;
    sample.sort((left, right) => left - right);
    return Math.max(0.25, sample[Math.floor(sample.length * 0.98)]);
  }

  function canvasContext(canvas) {
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#303536";
    context.strokeStyle = "#303536";
    context.font = '19px "IBM Plex Mono", monospace';
    return context;
  }

  function drawHeatmap(atlas) {
    const session = currentSession();
    state.sortedUnits = sortedUnitIndices(atlas);
    renderUnitSelect();
    const traces = state.sortedUnits.map((unitIndex) =>
      unitHeatmapTrace(atlas, unitIndex),
    );
    const baseLimit = automaticLimit(traces);
    const limit = baseLimit * (state.colorPercent / 100);
    colorLimitValue.textContent = `${state.colorPercent}% · ±${limit.toFixed(
      state.metric === "zscore" ? 1 : 0,
    )}`;
    colorKey.title = `Blue −${limit.toFixed(2)}, white 0, red +${limit.toFixed(2)}`;
    const context = canvasContext(heatmapCanvas);
    const plot = { left: 82, right: 1175, top: 20, bottom: 570 };
    context.fillStyle = "#f7f8f8";
    context.fillRect(
      plot.left,
      plot.top,
      plot.right - plot.left,
      plot.bottom - plot.top,
    );
    if (traces.length) {
      const offscreen = document.createElement("canvas");
      offscreen.width = time.length;
      offscreen.height = traces.length;
      const offscreenContext = offscreen.getContext("2d");
      const image = offscreenContext.createImageData(time.length, traces.length);
      traces.forEach((trace, row) => {
        trace.forEach((value, column) => {
          const [red, green, blue] = color(value, limit);
          const offset = (row * time.length + column) * 4;
          image.data[offset] = red;
          image.data[offset + 1] = green;
          image.data[offset + 2] = blue;
          image.data[offset + 3] = 255;
        });
      });
      offscreenContext.putImageData(image, 0, 0);
      context.imageSmoothingEnabled = false;
      context.drawImage(
        offscreen,
        plot.left,
        plot.top,
        plot.right - plot.left,
        plot.bottom - plot.top,
      );
    }
    context.strokeStyle = "#d0d4d2";
    context.strokeRect(
      plot.left,
      plot.top,
      plot.right - plot.left,
      plot.bottom - plot.top,
    );
    for (const tick of [-1, 0, 1, 2]) {
      const x =
        plot.left +
        ((tick - time[0]) / (time.at(-1) - time[0])) *
          (plot.right - plot.left);
      context.strokeStyle = tick === 0 ? "#303536" : "#d0d4d2";
      context.setLineDash(tick === 0 ? [6, 5] : []);
      context.beginPath();
      context.moveTo(x, plot.top);
      context.lineTo(x, plot.bottom);
      context.stroke();
      context.setLineDash([]);
      context.fillStyle = "#59605e";
      context.textAlign = "center";
      context.fillText(String(tick), x, plot.bottom + 28);
    }
    context.font = '21px "Myriad Pro", Arial, sans-serif';
    context.fillText(
      "Time from stimulus-table start_time (s)",
      (plot.left + plot.right) / 2,
      plot.bottom + 59,
    );
    context.save();
    context.translate(25, (plot.top + plot.bottom) / 2);
    context.rotate(-Math.PI / 2);
    context.fillText("Units", 0, 0);
    context.restore();
    unitCount.textContent = `${state.sortedUnits.length.toLocaleString()} units`;
    heatmapDetail.textContent = `${session.sessionId} · ${
      session.events[state.eventIndex].label
    } · ${state.metric === "difference" ? "mismatch − control spikes/s" : "mismatch baseline z score"}`;
    heatmapCanvas.setAttribute(
      "aria-label",
      `${state.sortedUnits.length} unit rows by ${time.length} time bins for ${heatmapDetail.textContent}.`,
    );
  }

  function meanAndSem(traces) {
    const mean = [];
    const sem = [];
    for (let bin = 0; bin < time.length; bin += 1) {
      const values = traces.map((trace) => trace[bin]).filter(Number.isFinite);
      if (!values.length) {
        mean.push(null);
        sem.push(null);
        continue;
      }
      const average = values.reduce((sum, value) => sum + value, 0) / values.length;
      const variance =
        values.reduce((sum, value) => sum + (value - average) ** 2, 0) /
        values.length;
      mean.push(average);
      sem.push(Math.sqrt(variance) / Math.sqrt(values.length));
    }
    return { mean, sem };
  }

  function responseTraces(atlas) {
    if (state.scope === "unit") {
      return {
        context: unitRateTrace(atlas, state.selectedUnit, 0),
        control: unitRateTrace(atlas, state.selectedUnit, 1),
        contextSem: null,
        controlSem: null,
      };
    }
    const indices = filteredUnitIndices();
    const context = meanAndSem(
      indices.map((index) => unitRateTrace(atlas, index, 0)),
    );
    const control = meanAndSem(
      indices.map((index) => unitRateTrace(atlas, index, 1)),
    );
    return {
      context: context.mean,
      control: control.mean,
      contextSem: context.sem,
      controlSem: control.sem,
    };
  }

  function responseRange(traces) {
    const values = [...traces.context, ...traces.control].filter(Number.isFinite);
    if (traces.contextSem) {
      traces.context.forEach((value, index) => {
        if (value !== null && traces.contextSem[index] !== null) {
          values.push(value - traces.contextSem[index], value + traces.contextSem[index]);
        }
      });
    }
    if (traces.controlSem) {
      traces.control.forEach((value, index) => {
        if (value !== null && traces.controlSem[index] !== null) {
          values.push(value - traces.controlSem[index], value + traces.controlSem[index]);
        }
      });
    }
    const maximum = Math.max(...values, 1);
    return [0, maximum * 1.08];
  }

  function drawResponseLine(context, values, plot, yRange, colorValue, dashed = false) {
    context.save();
    context.strokeStyle = colorValue;
    context.lineWidth = 4;
    if (dashed) context.setLineDash([11, 8]);
    context.beginPath();
    values.forEach((value, index) => {
      const x =
        plot.left + (index / (time.length - 1)) * (plot.right - plot.left);
      const y =
        plot.bottom -
        ((value - yRange[0]) / (yRange[1] - yRange[0])) *
          (plot.bottom - plot.top);
      if (index) context.lineTo(x, y);
      else context.moveTo(x, y);
    });
    context.stroke();
    context.restore();
  }

  function drawResponseBand(context, values, sem, plot, yRange, colorValue) {
    if (!sem) return;
    context.save();
    context.fillStyle = colorValue;
    context.globalAlpha = 0.14;
    context.beginPath();
    values.forEach((value, index) => {
      const x =
        plot.left + (index / (time.length - 1)) * (plot.right - plot.left);
      const y =
        plot.bottom -
        ((value + sem[index] - yRange[0]) / (yRange[1] - yRange[0])) *
          (plot.bottom - plot.top);
      if (index) context.lineTo(x, y);
      else context.moveTo(x, y);
    });
    for (let index = values.length - 1; index >= 0; index -= 1) {
      const x =
        plot.left + (index / (time.length - 1)) * (plot.right - plot.left);
      const y =
        plot.bottom -
        ((values[index] - sem[index] - yRange[0]) / (yRange[1] - yRange[0])) *
          (plot.bottom - plot.top);
      context.lineTo(x, y);
    }
    context.closePath();
    context.fill();
    context.restore();
  }

  function drawResponse(atlas) {
    const traces = responseTraces(atlas);
    const yRange = responseRange(traces);
    const context = canvasContext(responseCanvas);
    const plot = { left: 86, right: 1170, top: 22, bottom: 280 };
    context.strokeStyle = "#d5d9d7";
    context.fillStyle = "#59605e";
    context.lineWidth = 1;
    for (const fraction of [0, 0.5, 1]) {
      const y = plot.bottom - fraction * (plot.bottom - plot.top);
      const value = yRange[0] + fraction * (yRange[1] - yRange[0]);
      context.beginPath();
      context.moveTo(plot.left, y);
      context.lineTo(plot.right, y);
      context.stroke();
      context.textAlign = "right";
      context.fillText(value.toFixed(1), plot.left - 10, y + 6);
    }
    for (const tick of [-1, 0, 1, 2]) {
      const x =
        plot.left +
        ((tick - time[0]) / (time.at(-1) - time[0])) *
          (plot.right - plot.left);
      context.strokeStyle = tick === 0 ? "#303536" : "#d5d9d7";
      context.setLineDash(tick === 0 ? [6, 5] : []);
      context.beginPath();
      context.moveTo(x, plot.top);
      context.lineTo(x, plot.bottom);
      context.stroke();
      context.setLineDash([]);
      context.textAlign = "center";
      context.fillText(String(tick), x, plot.bottom + 27);
    }
    drawResponseBand(
      context,
      traces.control,
      traces.controlSem,
      plot,
      yRange,
      "#8a918e",
    );
    drawResponseBand(
      context,
      traces.context,
      traces.contextSem,
      plot,
      yRange,
      contextColors[state.context],
    );
    drawResponseLine(context, traces.control, plot, yRange, "#8a918e", true);
    drawResponseLine(
      context,
      traces.context,
      plot,
      yRange,
      contextColors[state.context],
    );
    context.font = '20px "Myriad Pro", Arial, sans-serif';
    context.fillText(
      "Time from stimulus-table start_time (s)",
      (plot.left + plot.right) / 2,
      plot.bottom + 58,
    );
    context.save();
    context.translate(24, (plot.top + plot.bottom) / 2);
    context.rotate(-Math.PI / 2);
    context.fillText("Firing rate (spikes/s)", 0, 0);
    context.restore();
    responseTitle.textContent =
      state.scope === "area"
        ? `${state.area === "all" ? "Selected units" : state.area} mean PSTH`
        : `Unit ${currentSession().units[state.selectedUnit].id} PSTH`;
  }

  function metadataRows(rows) {
    unitMetadata.replaceChildren();
    for (const [term, value] of rows) {
      const wrapper = document.createElement("div");
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = term;
      dd.textContent = value;
      wrapper.append(dt, dd);
      unitMetadata.append(wrapper);
    }
  }

  function formattedMetric(value, digits = 3) {
    return value === null || !Number.isFinite(value)
      ? "n/a"
      : value.toFixed(digits);
  }

  function drawWaveform(atlas) {
    const session = currentSession();
    const unitIndex = state.selectedUnit;
    const unit = session.units[unitIndex];
    const samples = session.waveformAtlas.shape[1];
    const start = unitIndex * samples;
    const values = Array.from(
      atlas.waveforms.subarray(start, start + samples),
      (value) => (value / 127) * unit.waveformScaleUv,
    );
    const context = canvasContext(waveformCanvas);
    const plot = { left: 64, right: 500, top: 20, bottom: 185 };
    const maximum = Math.max(...values.map(Math.abs), 1);
    context.strokeStyle = "#d5d9d7";
    context.beginPath();
    context.moveTo(plot.left, (plot.top + plot.bottom) / 2);
    context.lineTo(plot.right, (plot.top + plot.bottom) / 2);
    context.stroke();
    context.strokeStyle = contextColors[state.context];
    context.lineWidth = 3;
    context.beginPath();
    values.forEach((value, index) => {
      const x = plot.left + (index / (values.length - 1)) * (plot.right - plot.left);
      const y =
        (plot.top + plot.bottom) / 2 -
        (value / maximum) * ((plot.bottom - plot.top) / 2);
      if (index) context.lineTo(x, y);
      else context.moveTo(x, y);
    });
    context.stroke();
    context.fillStyle = "#59605e";
    context.font = '16px "IBM Plex Mono", monospace';
    context.textAlign = "right";
    context.fillText(`±${maximum.toFixed(1)} µV`, plot.left - 5, plot.top + 8);
    context.textAlign = "center";
    context.fillText(
      `${((values.length / session.waveformAtlas.sampleRateHz) * 1000).toFixed(
        1,
      )} ms`,
      (plot.left + plot.right) / 2,
      plot.bottom + 29,
    );
    waveformCanvas.setAttribute(
      "aria-label",
      `Unit ${unit.id} mean template waveform, peak amplitude ${maximum.toFixed(
        1,
      )} microvolts.`,
    );
    unitTitle.textContent = `Unit ${unit.id} diagnostics`;
    metadataRows([
      ["Probe", unit.probe],
      ["Area", unit.location],
      ["Depth", `${formattedMetric(unit.depthUm, 1)} µm`],
      ["QC", unit.qcPass ? "Pass" : "Fail"],
      ["Sorter label", unit.decoderLabel],
      ["Spikes", unit.spikeCount.toLocaleString()],
      ["ISI violations", formattedMetric(unit.isiViolationsRatio)],
      ["Presence ratio", formattedMetric(unit.presenceRatio)],
    ]);
  }

  async function render() {
    const session = currentSession();
    loadingMessage.hidden = false;
    try {
      const atlas = await loadAtlas(session);
      drawHeatmap(atlas);
      if (state.selectedUnit !== null) {
        drawResponse(atlas);
        drawWaveform(atlas);
      }
      sourceNote.textContent = `${session.sessionId} · mouse ${session.subject} · DANDI:${session.asset.dandisetId} · ${session.unitCount.toLocaleString()} sorted units`;
      loadingMessage.hidden = true;
    } catch (error) {
      loadingMessage.textContent = error.message;
      throw error;
    }
  }

  function setPressed(container, key, value) {
    container.querySelectorAll(`[data-${key}]`).forEach((element) => {
      element.setAttribute("aria-pressed", String(element.dataset[key] === value));
    });
  }

  function configureSession() {
    document.documentElement.style.setProperty(
      "--accent",
      contextColors[state.context],
    );
    renderContextTabs();
    renderEventSelect();
    renderProbeSelect();
    renderAreaSelect();
    renderResponseSelection();
    render();
  }

  qcTabs.querySelectorAll("[data-qc]").forEach((element) => {
    element.addEventListener("click", () => {
      state.qc = element.dataset.qc;
      setPressed(qcTabs, "qc", state.qc);
      renderAreaSelect();
      state.selectedUnit = null;
      render();
    });
  });
  scopeTabs.querySelectorAll("[data-scope]").forEach((element) => {
    element.addEventListener("click", () => {
      state.scope = element.dataset.scope;
      if (state.scope === "unit") {
        state.area = "all";
        renderAreaSelect();
      }
      renderResponseSelection();
      setPressed(scopeTabs, "scope", state.scope);
      render();
    });
  });
  metricTabs.querySelectorAll("[data-metric]").forEach((element) => {
    element.addEventListener("click", () => {
      state.metric = element.dataset.metric;
      setPressed(metricTabs, "metric", state.metric);
      render();
    });
  });
  eventSelect.addEventListener("change", () => {
    state.eventIndex = Number(eventSelect.value);
    render();
  });
  probeSelect.addEventListener("change", () => {
    state.probe = probeSelect.value;
    state.area = "all";
    state.selectedUnit = null;
    renderAreaSelect();
    render();
  });
  areaSelect.addEventListener("change", () => {
    state.area = areaSelect.value;
    state.selectedUnit = null;
    render();
  });
  unitSelect.addEventListener("change", () => {
    state.selectedUnit = Number(unitSelect.value);
    render();
  });
  sortSelect.addEventListener("change", () => {
    state.sort = sortSelect.value;
    render();
  });
  colorLimit.addEventListener("input", () => {
    state.colorPercent = Number(colorLimit.value);
    render();
  });
  document.querySelectorAll("[data-view]").forEach((element) => {
    element.addEventListener("click", () => {
      state.view = element.dataset.view;
      document.querySelectorAll("[data-view]").forEach((buttonElement) => {
        buttonElement.setAttribute(
          "aria-pressed",
          String(buttonElement.dataset.view === state.view),
        );
      });
      interactiveView.hidden = state.view !== "interactive";
      staticView.hidden = state.view !== "static";
    });
  });

  heatmapCanvas.addEventListener("pointermove", (event) => {
    if (!state.sortedUnits.length) return;
    const rect = heatmapCanvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * heatmapCanvas.width;
    const y = ((event.clientY - rect.top) / rect.height) * heatmapCanvas.height;
    const plot = { left: 82, right: 1175, top: 20, bottom: 570 };
    if (x < plot.left || x > plot.right || y < plot.top || y > plot.bottom) {
      heatmapTooltip.hidden = true;
      return;
    }
    const row = Math.min(
      state.sortedUnits.length - 1,
      Math.floor(
        ((y - plot.top) / (plot.bottom - plot.top)) * state.sortedUnits.length,
      ),
    );
    const unitIndex = state.sortedUnits[row];
    const unit = currentSession().units[unitIndex];
    heatmapTooltip.textContent = `Unit ${unit.id} · ${unit.probe} · ${unit.location} · ${
      unit.qcPass ? "QC pass" : "QC fail"
    }`;
    heatmapTooltip.style.left = `${event.clientX + 12}px`;
    heatmapTooltip.style.top = `${event.clientY + 12}px`;
    heatmapTooltip.hidden = false;
  });
  heatmapCanvas.addEventListener("pointerleave", () => {
    heatmapTooltip.hidden = true;
  });
  heatmapCanvas.addEventListener("click", (event) => {
    if (!state.sortedUnits.length) return;
    const rect = heatmapCanvas.getBoundingClientRect();
    const y = ((event.clientY - rect.top) / rect.height) * heatmapCanvas.height;
    const plot = { top: 20, bottom: 570 };
    if (y < plot.top || y > plot.bottom) return;
    const row = Math.min(
      state.sortedUnits.length - 1,
      Math.floor(
        ((y - plot.top) / (plot.bottom - plot.top)) * state.sortedUnits.length,
      ),
    );
    state.selectedUnit = state.sortedUnits[row];
    state.scope = "unit";
    state.area = "all";
    renderAreaSelect();
    renderResponseSelection();
    setPressed(scopeTabs, "scope", state.scope);
    render();
  });

  configureSession();
})();
