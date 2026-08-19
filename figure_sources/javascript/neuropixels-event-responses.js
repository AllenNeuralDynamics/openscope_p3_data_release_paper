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
    metric: "mismatch",
    probe: "all",
    qc: "qc",
    decoderLabels: new Set(["mua", "sua"]),
    minimumFiringRateHz: 1,
    scope: "area",
    selectedUnit: null,
    sort: "response",
    view: "interactive",
    zscoreLimit: 3,
    sortedUnits: [],
  };
  const atlasCache = new Map();

  const contextTabs = document.getElementById("context-tabs");
  const eventSelect = document.getElementById("event-select");
  const probeSelect = document.getElementById("probe-select");
  const areaSelect = document.getElementById("area-select");
  const qcTabs = document.getElementById("qc-tabs");
  const decoderLabelFilter = document.getElementById("decoder-label-filter");
  const minimumFiringRate = document.getElementById("minimum-firing-rate");
  const minimumFiringRateValue = document.getElementById(
    "minimum-firing-rate-value",
  );
  const scopeTabs = document.getElementById("scope-tabs");
  const responseSelectionLabel = document.getElementById(
    "response-selection-label",
  );
  const unitSelect = document.getElementById("unit-select");
  const metricTabs = document.getElementById("metric-tabs");
  const sortSelect = document.getElementById("sort-select");
  const colorLimit = document.getElementById("color-limit");
  const colorLimitValue = document.getElementById("color-limit-value");
  const colorKeyMin = document.getElementById("color-key-min");
  const colorKeyMax = document.getElementById("color-key-max");
  const heatmapCanvas = document.getElementById("heatmap-canvas");
  const heatmapTooltip = document.getElementById("heatmap-tooltip");
  const heatmapDetail = document.getElementById("heatmap-detail");
  const colorKey = document.getElementById("color-key");
  const loadingMessage = document.getElementById("loading-message");
  const responseCanvas = document.getElementById("response-canvas");
  const responseTitle = document.getElementById("response-title");
  const baselineResponseCanvas = document.getElementById(
    "baseline-response-canvas",
  );
  const baselineResponseTitle = document.getElementById(
    "baseline-response-title",
  );
  const sourceNote = document.getElementById("source-note");
  const interactiveView = document.getElementById("interactive-view");
  const staticView = document.getElementById("static-view");
  const rastermapRankCache = new Map();

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

  function decodeUint16Base64(encoded) {
    const binary = atob(encoded);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new Uint16Array(bytes.buffer);
  }

  function rastermapRanks(session) {
    if (!rastermapRankCache.has(session.context)) {
      rastermapRankCache.set(
        session.context,
        decodeUint16Base64(session.rastermapRank.base64),
      );
    }
    return rastermapRankCache.get(session.context);
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
          fetchGzip(session.countSquareAtlas.path),
        ]).then(([countBuffer, countSquareBuffer]) => ({
          baselineMean: decodeFloat32Base64(session.baselineMeanHzBase64),
          baselineStd: decodeFloat32Base64(session.baselineStdHzBase64),
          counts: new Uint16Array(countBuffer),
          countSquares: new Uint16Array(countSquareBuffer),
          responseDelta: decodeFloat32Base64(session.responseDeltaHzBase64),
          responseContext: decodeFloat32Base64(session.responseContextHzBase64),
          responseControl: decodeFloat32Base64(session.responseControlHzBase64),
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
    return session.units.filter(unitMatchesBaseFilters);
  }

  function unitMatchesBaseFilters(unit) {
    return (
      (state.probe === "all" || unit.probe === state.probe) &&
      (state.qc === "all" || unit.qcPass) &&
      state.decoderLabels.has(unit.decoderLabel) &&
      unit.firingRateHz >= state.minimumFiringRateHz
    );
  }

  function renderAreaSelect() {
    const units = areaSourceUnits();
    const areas = [...new Set(units.map((unit) => unit.location))].sort();
    const groups = [
      ["group:cortical", "All cortical areas", "cortical"],
      ["group:thalamic", "All thalamic areas", "thalamic"],
      ["group:visual", "All visual areas", "visual"],
      ["group:frontal", "All frontal areas", "frontal"],
      ["group:motor", "All motor areas", "motor"],
      ["group:hippocampal", "All hippocampal areas", "hippocampal"],
    ].filter(([, , group]) =>
      units.some((unit) => unit.areaGroups.includes(group)),
    );
    areaSelect.replaceChildren();
    for (const [value, label] of [
      ["all", "All areas"],
      ...groups.map(([value, label]) => [value, label]),
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

  function areaMatches(unit) {
    if (state.area === "all") return true;
    if (state.area.startsWith("group:")) {
      return unit.areaGroups.includes(state.area.slice("group:".length));
    }
    return unit.location === state.area;
  }

  function selectedAreaLabel() {
    return areaSelect.selectedOptions[0]?.textContent || state.area;
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
          unitMatchesBaseFilters(unit) && areaMatches(unit),
      )
      .map(({ index }) => index);
  }

  function sortingTrace(atlas, unitIndex) {
    const context = unitRateTrace(atlas, unitIndex, 0);
    const session = currentSession();
    const offset = baselineOffset(unitIndex, 0);
    const mean = atlas.baselineMean[offset];
    const std = atlas.baselineStd[offset];
    if (!Number.isFinite(mean) || !Number.isFinite(std) || std <= 0) {
      return context.map(() => null);
    }
    return context.map((value) => (value - mean) / std);
  }

  function sortingResponseMagnitude(atlas, unitIndex) {
    const trace = sortingTrace(atlas, unitIndex);
    const timing = currentSession().events[state.eventIndex].timing.context;
    const values = trace.filter(
      (value, index) =>
        time[index] >= timing.presentationStartSeconds &&
        time[index] <= timing.presentationStopSeconds &&
        value !== null &&
        Number.isFinite(value),
    );
    return values.length ? Math.max(...values.map(Math.abs)) : Number.NEGATIVE_INFINITY;
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
      if (state.sort === "peak-time") {
        const leftPeak = peakTime(atlas, left);
        const rightPeak = peakTime(atlas, right);
        if (leftPeak !== rightPeak) return leftPeak < rightPeak ? -1 : 1;
        return session.units[left].id - session.units[right].id;
      }
      if (state.sort === "rastermap") {
        const ranks = rastermapRanks(session);
        const offset = state.eventIndex * session.unitCount;
        return (
          ranks[offset + left] - ranks[offset + right] ||
          session.units[left].id - session.units[right].id
        );
      }
      const leftMagnitude = sortingResponseMagnitude(atlas, left);
      const rightMagnitude = sortingResponseMagnitude(atlas, right);
      if (leftMagnitude !== rightMagnitude) {
        return leftMagnitude > rightMagnitude ? -1 : 1;
      }
      return session.units[left].id - session.units[right].id;
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
      option.textContent = `Unit ${unit.id} · ${unit.probe} · ${
        unit.location
      } · ${unit.decoderLabel.toUpperCase()} · ${unit.firingRateHz.toFixed(1)} Hz`;
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

  function smoothStandardErrors(meanVariances) {
    const radius = Math.floor(smoothingKernel.length / 2);
    return meanVariances.map((_, index) => {
      let variance = 0;
      let weightSum = 0;
      smoothingKernel.forEach((weight, kernelIndex) => {
        const source = index + kernelIndex - radius;
        if (source >= 0 && source < meanVariances.length) {
          variance += meanVariances[source] * weight * weight;
          weightSum += weight;
        }
      });
      return Math.sqrt(variance) / weightSum;
    });
  }

  function unitRateStats(atlas, unitIndex, conditionIndex) {
    const event = currentSession().events[state.eventIndex];
    const trials =
      conditionIndex === 0 ? event.contextTrialCount : event.controlTrialCount;
    const means = [];
    const meanVariances = [];
    time.forEach((_, binIndex) => {
      const index = countIndex(
        state.eventIndex,
        conditionIndex,
        unitIndex,
        binIndex,
      );
      const sum = atlas.counts[index];
      const squareSum = atlas.countSquares[index];
      const mean = sum / trials;
      const variance =
        trials > 1
          ? Math.max(0, (squareSum - (sum * sum) / trials) / (trials - 1))
          : 0;
      means.push(mean / binSeconds);
      meanVariances.push(variance / trials / binSeconds ** 2);
    });
    return {
      mean: smooth(means),
      sem: smoothStandardErrors(meanVariances),
    };
  }

  function unitRateTrace(atlas, unitIndex, conditionIndex) {
    return unitRateStats(atlas, unitIndex, conditionIndex).mean;
  }

  function unitHeatmapTrace(atlas, unitIndex) {
    const context = unitRateTrace(atlas, unitIndex, 0);
    if (state.metric === "mismatch") return context;
    const control = unitRateTrace(atlas, unitIndex, 1);
    if (state.metric === "control") return control;
    if (state.metric === "difference") {
      return context.map((value, index) => value - control[index]);
    }
    const session = currentSession();
    const conditionIndex = state.metric === "mismatch-zscore" ? 0 : 1;
    const offset =
      (state.eventIndex * 2 + conditionIndex) * session.unitCount + unitIndex;
    const mean = atlas.baselineMean[offset];
    const std = atlas.baselineStd[offset];
    if (!Number.isFinite(mean) || !Number.isFinite(std) || std <= 0) {
      return context.map(() => null);
    }
    const values = conditionIndex === 0 ? context : control;
    return values.map((value) => (value - mean) / std);
  }

  function metricIsSequential() {
    return state.metric === "mismatch" || state.metric === "control";
  }

  function color(value, limit) {
    if (value === null || !Number.isFinite(value)) return [225, 228, 227];
    if (metricIsSequential()) {
      const amount = Math.max(0, Math.min(1, value / limit));
      const neutral = [247, 247, 247];
      const warm = [35, 35, 35];
      return neutral.map((channel, index) =>
        Math.round(channel + (warm[index] - channel) * amount),
      );
    }
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
        if (value !== null && Number.isFinite(value))         sample.push(metricIsSequential() ? Math.max(0, value) : Math.abs(value));
      }
    }
    if (!sample.length) return 1;
    sample.sort((left, right) => left - right);
    return Math.max(0.25, sample[Math.floor(sample.length * 0.98)]);
  }

  function displayStart() {
    return state.context === "duration" ? -1.5 : -1;
  }

  function peakTime(atlas, unitIndex) {
    const trace = sortingTrace(atlas, unitIndex);
    const timing = currentSession().events[state.eventIndex].timing.context;
    let maximum = 0;
    let peak = Number.POSITIVE_INFINITY;
    trace.forEach((value, index) => {
      if (
        time[index] >= timing.presentationStartSeconds &&
        time[index] <= timing.presentationStopSeconds &&
        value !== null &&
        value > maximum
      ) {
        maximum = value;
        peak = time[index];
      }
    });
    return peak;
  }

  function metricLabel() {
    return {
      mismatch: "mismatch firing rate",
      control: "control firing rate",
      difference: "mismatch − control spikes/s",
      "mismatch-zscore": "mismatch baseline z score",
      "control-zscore": "control baseline z score",
    }[state.metric];
  }

  function configureColorControl() {
    if (state.metric.endsWith("zscore")) {
      colorLimit.min = "1";
      colorLimit.max = "6";
      colorLimit.step = "0.5";
      colorLimit.value = String(state.zscoreLimit);
    } else {
      colorLimit.min = "25";
      colorLimit.max = "200";
      colorLimit.step = "5";
      colorLimit.value = String(state.colorPercent);
    }
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
    const zscore = state.metric.endsWith("zscore");
    const limit = zscore
      ? state.zscoreLimit
      : baseLimit * (state.colorPercent / 100);
    const digits = zscore ? 1 : 0;
    const unit = zscore ? "z" : "spikes/s";
    colorLimitValue.textContent = zscore
      ? `±${limit.toFixed(1)} z`
      : `${state.colorPercent}% · ${
          metricIsSequential() ? "0–" : "±"
        }${limit.toFixed(digits)} ${unit}`;
    colorKey.style.background = metricIsSequential()
      ? "linear-gradient(90deg, #f7f7f7, #232323)"
      : "linear-gradient(90deg, #3b4cc0, #f7f7f7, #b40426)";
    colorKeyMin.textContent = metricIsSequential()
      ? "0"
      : `−${limit.toFixed(digits)} ${unit}`;
    colorKeyMax.textContent = metricIsSequential()
      ? `${limit.toFixed(digits)} ${unit}`
      : `+${limit.toFixed(digits)} ${unit}`;
    document.getElementById("color-key-zero").hidden = metricIsSequential();
    colorKey.title = metricIsSequential()
      ? `White 0, black ${limit.toFixed(2)} ${unit}`
      : `Blue −${limit.toFixed(2)}, white 0, red +${limit.toFixed(2)} ${unit}`;
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
      const firstVisible = time.findIndex((value) => value >= displayStart());
      const sourceWidth = time.length - firstVisible;
      context.drawImage(
        offscreen,
        firstVisible,
        0,
        sourceWidth,
        traces.length,
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
    const ticks =
      state.context === "duration" ? [-1.5, -1, 0, 1, 2] : [-1, 0, 1, 2];
    for (const tick of ticks) {
      const x =
        plot.left +
        ((tick - displayStart()) / (time.at(-1) - displayStart())) *
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
      "Time from mismatch stimulus (s)",
      (plot.left + plot.right) / 2,
      plot.bottom + 59,
    );
    const timing = session.events[state.eventIndex].timing.context;
    const timingValues = [
      timing.previousPresentationStartSeconds,
      timing.previousPresentationStopSeconds,
      timing.presentationStartSeconds,
      timing.presentationStopSeconds,
    ].filter(
      (value) =>
        Number.isFinite(value) &&
        value >= displayStart() &&
        value <= time.at(-1),
    );
    for (const value of [...new Set(timingValues)]) {
      const x =
        plot.left +
        ((value - displayStart()) / (time.at(-1) - displayStart())) *
          (plot.right - plot.left);
      context.strokeStyle = Math.abs(value) < 1e-9 ? "#303536" : "#59605e";
      context.setLineDash([6, 5]);
      context.beginPath();
      context.moveTo(x, plot.top);
      context.lineTo(x, plot.bottom);
      context.stroke();
      context.setLineDash([]);
    }
    context.save();
    context.translate(25, (plot.top + plot.bottom) / 2);
    context.rotate(-Math.PI / 2);
    context.fillText("Units", 0, 0);
    context.restore();
    context.font = '18px "IBM Plex Mono", monospace';
    context.fillStyle = "#59605e";
    context.textAlign = "right";
    const rowTicks = state.sortedUnits.length
      ? [
          [0, plot.top + 6],
          [Math.floor(state.sortedUnits.length / 2), (plot.top + plot.bottom) / 2 + 6],
          [state.sortedUnits.length, plot.bottom + 6],
        ]
      : [[0, plot.top + 6]];
    for (const [label, y] of rowTicks) {
      context.fillText(String(label), plot.left - 10, y);
    }
    heatmapDetail.textContent = `${session.sessionId} · ${
      session.events[state.eventIndex].label
    } · ${metricLabel()}`;
    heatmapCanvas.setAttribute(
      "aria-label",
      `${state.sortedUnits.length} unit rows by ${time.length} time bins for ${heatmapDetail.textContent}.`,
    );
  }

  function meanAndSd(traces) {
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
      sem.push(Math.sqrt(variance));
    }
    return { mean, sem };
  }

  function responseTraces(atlas) {
    if (state.scope === "unit") {
      const context = unitRateStats(atlas, state.selectedUnit, 0);
      const control = unitRateStats(atlas, state.selectedUnit, 1);
      return {
        context: context.mean,
        control: control.mean,
        contextSem: context.sem,
        controlSem: control.sem,
      };
    }
    const indices = filteredUnitIndices();
    const context = meanAndSd(
      indices.map((index) => unitRateTrace(atlas, index, 0)),
    );
    const control = meanAndSd(
      indices.map((index) => unitRateTrace(atlas, index, 1)),
    );
    return {
      context: context.mean,
      control: control.mean,
      contextSem: context.sem,
      controlSem: control.sem,
    };
  }

  function baselineOffset(unitIndex, conditionIndex) {
    const session = currentSession();
    return (
      (state.eventIndex * 2 + conditionIndex) * session.unitCount + unitIndex
    );
  }

  function baselineSubtractedTraces(atlas) {
    if (state.scope === "unit") {
      const traces = responseTraces(atlas);
      const contextBaseline = atlas.baselineMean[
        baselineOffset(state.selectedUnit, 0)
      ];
      const controlBaseline = atlas.baselineMean[
        baselineOffset(state.selectedUnit, 1)
      ];
      return {
        context: traces.context.map((value) => value - contextBaseline),
        control: traces.control.map((value) => value - controlBaseline),
        contextSem: traces.contextSem,
        controlSem: traces.controlSem,
      };
    }
    const indices = filteredUnitIndices();
    const context = meanAndSd(
      indices.map((unitIndex) => {
        const baseline = atlas.baselineMean[baselineOffset(unitIndex, 0)];
        return unitRateTrace(atlas, unitIndex, 0).map(
          (value) => value - baseline,
        );
      }),
    );
    const control = meanAndSd(
      indices.map((unitIndex) => {
        const baseline = atlas.baselineMean[baselineOffset(unitIndex, 1)];
        return unitRateTrace(atlas, unitIndex, 1).map(
          (value) => value - baseline,
        );
      }),
    );
    return {
      context: context.mean,
      control: control.mean,
      contextSem: context.sem,
      controlSem: control.sem,
    };
  }

  function responseValues(traces) {
    const values = [];
    traces.context.forEach((value, index) => {
      if (time[index] >= displayStart() && Number.isFinite(value)) values.push(value);
    });
    traces.control.forEach((value, index) => {
      if (time[index] >= displayStart() && Number.isFinite(value)) values.push(value);
    });
    if (traces.contextSem) {
      traces.context.forEach((value, index) => {
        if (value !== null && traces.contextSem[index] !== null) {
          if (time[index] >= displayStart()) {
            values.push(
              value - traces.contextSem[index],
              value + traces.contextSem[index],
            );
          }
        }
      });
    }
    if (traces.controlSem) {
      traces.control.forEach((value, index) => {
        if (value !== null && traces.controlSem[index] !== null) {
          if (time[index] >= displayStart()) {
            values.push(
              value - traces.controlSem[index],
              value + traces.controlSem[index],
            );
          }
        }
      });
    }
    return values;
  }

  function niceTickStep(span, targetTicks = 4) {
    const raw = Math.max(span / targetTicks, 1e-9);
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const normalized = raw / magnitude;
    const factor = [1, 2, 5, 10].find((value) => normalized <= value);
    return factor * magnitude;
  }

  function responseAxis(traces, baselineSubtracted) {
    const values = responseValues(traces);
    const minimum = Math.min(...values, 0);
    const maximum = Math.max(...values, 0);
    const span = Math.max(maximum - minimum, 1);
    const paddedMinimum = baselineSubtracted ? minimum - span * 0.05 : 0;
    const paddedMaximum = maximum + span * 0.05;
    const step = niceTickStep(paddedMaximum - paddedMinimum);
    const lower = baselineSubtracted
      ? Math.floor(paddedMinimum / step) * step
      : 0;
    let upper = Math.ceil(paddedMaximum / step) * step;
    if (upper <= lower) upper = lower + step;
    const tickCount = Math.round((upper - lower) / step);
    return {
      range: [lower, upper],
      ticks: Array.from(
        { length: tickCount + 1 },
        (_, index) => lower + index * step,
      ),
    };
  }

  function formatRateTick(value) {
    if (Math.abs(value) < 1e-9) return "0";
    return value.toFixed(2).replace(/\.?0+$/, "");
  }

  function responseX(index, plot) {
    return (
      plot.left +
      ((time[index] - displayStart()) / (time.at(-1) - displayStart())) *
        (plot.right - plot.left)
    );
  }

  function drawResponseLine(context, values, plot, yRange, colorValue, dashed = false) {
    context.save();
    context.strokeStyle = colorValue;
    context.lineWidth = 4;
    if (dashed) context.setLineDash([11, 8]);
    context.beginPath();
    let drawing = false;
    values.forEach((value, index) => {
      if (time[index] < displayStart()) return;
      const x = responseX(index, plot);
      const y =
        plot.bottom -
        ((value - yRange[0]) / (yRange[1] - yRange[0])) *
          (plot.bottom - plot.top);
      if (drawing) context.lineTo(x, y);
      else context.moveTo(x, y);
      drawing = true;
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
    const visible = values
      .map((_, index) => index)
      .filter((index) => time[index] >= displayStart());
    visible.forEach((index, position) => {
      const value = values[index];
      const x = responseX(index, plot);
      const y =
        plot.bottom -
        ((value + sem[index] - yRange[0]) / (yRange[1] - yRange[0])) *
          (plot.bottom - plot.top);
      if (position) context.lineTo(x, y);
      else context.moveTo(x, y);
    });
    [...visible].reverse().forEach((index) => {
      const x = responseX(index, plot);
      const y =
        plot.bottom -
        ((values[index] - sem[index] - yRange[0]) / (yRange[1] - yRange[0])) *
          (plot.bottom - plot.top);
      context.lineTo(x, y);
    });
    context.closePath();
    context.fill();
    context.restore();
  }

  function drawResponsePanel(canvas, traces, baselineSubtracted) {
    const axis = responseAxis(traces, baselineSubtracted);
    const yRange = axis.range;
    const context = canvasContext(canvas);
    const plot = { left: 86, right: 1170, top: 22, bottom: 280 };
    const timing = currentSession().events[state.eventIndex].timing.context;
    if (
      Number.isFinite(timing.presentationStartSeconds) &&
      Number.isFinite(timing.presentationStopSeconds)
    ) {
      const startX =
        plot.left +
        ((timing.presentationStartSeconds - displayStart()) /
          (time.at(-1) - displayStart())) *
          (plot.right - plot.left);
      const stopX =
        plot.left +
        ((timing.presentationStopSeconds - displayStart()) /
          (time.at(-1) - displayStart())) *
          (plot.right - plot.left);
      context.fillStyle = "rgba(90, 99, 96, 0.09)";
      context.fillRect(startX, plot.top, stopX - startX, plot.bottom - plot.top);
    }
    context.strokeStyle = "#d5d9d7";
    context.fillStyle = "#59605e";
    context.lineWidth = 1;
    for (const value of axis.ticks) {
      const y =
        plot.bottom -
        ((value - yRange[0]) / (yRange[1] - yRange[0])) *
          (plot.bottom - plot.top);
      context.strokeStyle = Math.abs(value) < 1e-9 ? "#9ca29f" : "#d5d9d7";
      context.beginPath();
      context.moveTo(plot.left, y);
      context.lineTo(plot.right, y);
      context.stroke();
      context.textAlign = "right";
      context.fillText(formatRateTick(value), plot.left - 10, y + 6);
    }
    const ticks =
      state.context === "duration" ? [-1.5, -1, 0, 1, 2] : [-1, 0, 1, 2];
    for (const tick of ticks) {
      const x =
        plot.left +
        ((tick - displayStart()) / (time.at(-1) - displayStart())) *
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
    const timingValues = [
      timing.previousPresentationStartSeconds,
      timing.previousPresentationStopSeconds,
      timing.presentationStartSeconds,
      timing.presentationStopSeconds,
    ].filter(
      (value) =>
        Number.isFinite(value) &&
        value >= displayStart() &&
        value <= time.at(-1),
    );
    for (const value of [...new Set(timingValues)]) {
      const x =
        plot.left +
        ((value - displayStart()) / (time.at(-1) - displayStart())) *
          (plot.right - plot.left);
      context.strokeStyle = Math.abs(value) < 1e-9 ? "#303536" : "#59605e";
      context.setLineDash([6, 5]);
      context.beginPath();
      context.moveTo(x, plot.top);
      context.lineTo(x, plot.bottom);
      context.stroke();
      context.setLineDash([]);
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
      "Time from mismatch stimulus (s)",
      (plot.left + plot.right) / 2,
      plot.bottom + 58,
    );
    context.save();
    context.translate(24, (plot.top + plot.bottom) / 2);
    context.rotate(-Math.PI / 2);
    context.fillText(
      baselineSubtracted
        ? "Δ firing rate"
        : "Firing rate (spikes/s)",
      0,
      0,
    );
    context.restore();
    canvas.setAttribute(
      "aria-label",
      `${state.scope === "unit" ? "Individual-unit" : "Area-mean"} ${
        baselineSubtracted ? "baseline-subtracted " : ""
      }mismatch and control firing-rate traces.`,
    );
  }

  async function render() {
    const session = currentSession();
    loadingMessage.hidden = false;
    try {
      const atlas = await loadAtlas(session);
      drawHeatmap(atlas);
      if (state.selectedUnit !== null) {
        const raw = responseTraces(atlas);
        const baseline = baselineSubtractedTraces(atlas);
        drawResponsePanel(responseCanvas, raw, false);
        drawResponsePanel(baselineResponseCanvas, baseline, true);
        const selection =
          state.scope === "area"
            ? state.area === "all"
              ? "Selected units"
              : selectedAreaLabel()
            : `Unit ${session.units[state.selectedUnit].id}`;
        responseTitle.textContent = `${selection} raw firing rate`;
        baselineResponseTitle.textContent = `${selection} baseline-subtracted firing rate`;
      } else {
        for (const canvas of [responseCanvas, baselineResponseCanvas]) {
          const context = canvasContext(canvas);
          context.fillStyle = "#68706d";
          context.textAlign = "center";
          context.font = '22px "Myriad Pro", Arial, sans-serif';
          context.fillText(
            "No units match the current filters.",
            canvas.width / 2,
            canvas.height / 2,
          );
        }
        responseTitle.textContent = "Raw firing rate";
        baselineResponseTitle.textContent = "Baseline-subtracted firing rate";
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
    configureColorControl();
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
  decoderLabelFilter
    .querySelectorAll("[data-decoder-label]")
    .forEach((element) => {
      element.addEventListener("change", () => {
        const label = element.dataset.decoderLabel;
        if (element.checked) state.decoderLabels.add(label);
        else state.decoderLabels.delete(label);
        renderAreaSelect();
        state.selectedUnit = null;
        render();
      });
    });
  minimumFiringRate.addEventListener("input", () => {
    state.minimumFiringRateHz = Number(minimumFiringRate.value);
    minimumFiringRateValue.textContent = `≥${state.minimumFiringRateHz.toFixed(1)} Hz`;
    renderAreaSelect();
    state.selectedUnit = null;
    render();
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
      configureColorControl();
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
    if (state.metric.endsWith("zscore")) {
      state.zscoreLimit = Number(colorLimit.value);
    } else {
      state.colorPercent = Number(colorLimit.value);
    }
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

  heatmapCanvas.addEventListener("pointermove", async (event) => {
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
    const relativeTime =
      displayStart() +
      ((x - plot.left) / (plot.right - plot.left)) *
        (time.at(-1) - displayStart());
    const binIndex = time.reduce(
      (best, value, index) =>
        Math.abs(value - relativeTime) < Math.abs(time[best] - relativeTime)
          ? index
          : best,
      0,
    );
    const atlas = await loadAtlas(currentSession());
    const value = unitHeatmapTrace(atlas, unitIndex)[binIndex];
    const unitLabel = state.metric.endsWith("zscore") ? "z" : "spikes/s";
    heatmapTooltip.textContent = `Unit ${unit.id} · ${unit.probe} · ${
      unit.location
    } · t=${time[binIndex].toFixed(2)} s · ${
      value === null || !Number.isFinite(value)
        ? "n/a"
        : `${value.toFixed(2)} ${unitLabel}`
    } · ${unit.decoderLabel.toUpperCase()} · ${unit.firingRateHz.toFixed(
      1,
    )} Hz · ${unit.qcPass ? "QC pass" : "QC fail"}`;
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
