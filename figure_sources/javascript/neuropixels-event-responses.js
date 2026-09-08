(() => {
  "use strict";

  const data = JSON.parse(
    document.getElementById("neuropixels-event-data").textContent,
  );
  let time = [];
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
    qc: "qc",
    decoderLabels: new Set(["mua", "sua"]),
    minimumFiringRateHz: 1,
    neuronTypes: new Set(["RS", "FS", "SST"]),
    baselineSubtracted: true,
    scope: "area",
    selectedUnit: null,
    sort: "area",
    view: "interactive",
    zscoreLimit: 3,
    sortedUnits: [],
  };
  const atlasCache = new Map();
  let renderSequence = 0;

  const contextTabs = document.getElementById("context-tabs");
  const eventSelect = document.getElementById("event-select");
  const areaSelect = document.getElementById("area-select");
  const qcTabs = document.getElementById("qc-tabs");
  const decoderLabelFilter = document.getElementById("decoder-label-filter");
  const neuronTypeFilter = document.getElementById("neuron-type-filter");
  const baselineSubtractedControl = document.getElementById(
    "baseline-subtracted",
  );
  const minimumFiringRate = document.getElementById("minimum-firing-rate");
  const minimumFiringRateValue = document.getElementById(
    "minimum-firing-rate-value",
  );
  const scopeTabs = document.getElementById("scope-tabs");
  const responseSelectionControl = document.getElementById(
    "response-selection-control",
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
  const colorKey = document.getElementById("color-key");
  const loadingMessage = document.getElementById("loading-message");
  const responseCanvas = document.getElementById("response-canvas");
  const responseTitle = document.getElementById("response-title");
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
        fetchGzip(session.sdfMeanAtlas.path).then((sdfMeanBuffer) => ({
          baselineMean: decodeFloat32Base64(session.baselineMeanHzBase64),
          baselineStd: decodeFloat32Base64(session.baselineStdHzBase64),
          quantizationScale: session.sdfMeanAtlas.quantizationScalePerHz,
          sdfMean: new Uint16Array(sdfMeanBuffer),
          responseDelta: decodeFloat32Base64(session.responseDeltaHzBase64),
          responseContext: decodeFloat32Base64(session.responseContextHzBase64),
          responseControl: decodeFloat32Base64(session.responseControlHzBase64),
          traceEventIndex: -1,
          traces: [[], []],
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
          atlasCache.clear();
          state.context = context;
          state.eventIndex = 0;
          state.area = "all";
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

  function areaSourceUnits() {
    const session = currentSession();
    return session.units.filter(unitMatchesBaseFilters);
  }

  function unitMatchesBaseFilters(unit) {
    return (
      (state.qc === "all" || unit.qcPass) &&
      state.decoderLabels.has(unit.decoderLabel) &&
      state.neuronTypes.has(unit.neuronType) &&
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
    responseSelectionControl.hidden = !individual;
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

  function areaOrderingMode() {
    if (state.area === "all") return "parent";
    if (state.area.startsWith("group:")) return "location";
    return "depth";
  }

  function unitIdentityOrder(leftUnit, rightUnit) {
    return (
      leftUnit.probe.localeCompare(rightUnit.probe) ||
      leftUnit.depthUm - rightUnit.depthUm ||
      leftUnit.id - rightUnit.id
    );
  }

  function sortedUnitIndices(atlas) {
    const session = currentSession();
    const indices = filteredUnitIndices();
    return indices.sort((left, right) => {
      if (state.sort === "area") {
        const leftUnit = session.units[left];
        const rightUnit = session.units[right];
        const mode = areaOrderingMode();
        if (mode === "depth") {
          return (
            leftUnit.depthUm - rightUnit.depthUm ||
            unitIdentityOrder(leftUnit, rightUnit)
          );
        }
        if (mode === "parent") {
          return (
            leftUnit.parentAreaGraphOrder - rightUnit.parentAreaGraphOrder ||
            leftUnit.parentArea.localeCompare(rightUnit.parentArea) ||
            leftUnit.areaGraphOrder - rightUnit.areaGraphOrder ||
            leftUnit.location.localeCompare(rightUnit.location) ||
            unitIdentityOrder(leftUnit, rightUnit)
          );
        }
        return (
          leftUnit.areaGraphOrder - rightUnit.areaGraphOrder ||
          leftUnit.location.localeCompare(rightUnit.location) ||
          unitIdentityOrder(leftUnit, rightUnit)
        );
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
      } · ${unit.neuronType} · ${
        unit.decoderLabel.toUpperCase()
      } · ${unit.firingRateHz.toFixed(1)} Hz`;
      unitSelect.append(option);
    }
    unitSelect.value = state.selectedUnit === null ? "" : String(state.selectedUnit);
  }

  function atlasIndex(eventIndex, conditionIndex, unitIndex, binIndex) {
    const session = currentSession();
    const binCount = time.length;
    return (
      (((eventIndex * 2 + conditionIndex) * session.unitCount + unitIndex) *
        binCount) +
      binIndex
    );
  }

  function unitRateStats(atlas, unitIndex, conditionIndex) {
    return {
      mean: unitRateTrace(atlas, unitIndex, conditionIndex),
      sem: null,
    };
  }

  function unitRateTrace(atlas, unitIndex, conditionIndex) {
    if (atlas.traceEventIndex !== state.eventIndex) {
      atlas.traceEventIndex = state.eventIndex;
      atlas.traces = [[], []];
    }
    if (!atlas.traces[conditionIndex][unitIndex]) {
      atlas.traces[conditionIndex][unitIndex] = time.map((_, binIndex) => {
        const index = atlasIndex(
          state.eventIndex,
          conditionIndex,
          unitIndex,
          binIndex,
        );
        return atlas.sdfMean[index] / atlas.quantizationScale;
      });
    }
    return atlas.traces[conditionIndex][unitIndex];
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

  function automaticLimit(atlas, unitIndices) {
    const sample = [];
    const stride = Math.max(1, Math.floor(unitIndices.length / 250));
    for (let row = 0; row < unitIndices.length; row += stride) {
      const unitIndex = unitIndices[row];
      const traces = metricIsSequential()
        ? [
            unitRateTrace(atlas, unitIndex, 0),
            unitRateTrace(atlas, unitIndex, 1),
          ]
        : [unitHeatmapTrace(atlas, unitIndex)];
      for (const trace of traces) {
        for (const value of trace) {
          if (value !== null && Number.isFinite(value)) {
            sample.push(
              metricIsSequential() ? Math.max(0, value) : Math.abs(value),
            );
          }
        }
      }
    }
    if (!sample.length) return 1;
    sample.sort((left, right) => left - right);
    return Math.max(0.25, sample[Math.floor(sample.length * 0.98)]);
  }

  function displayStart() {
    return currentSession().windowSeconds[0];
  }

  function displayEnd() {
    return currentSession().windowSeconds[1];
  }

  function presentationTimingValues(timing) {
    const start = timing.presentationStartSeconds;
    const stop = timing.presentationStopSeconds;
    if (
      !Number.isFinite(start) ||
      !Number.isFinite(stop) ||
      start >= stop ||
      start < displayStart() ||
      stop > displayEnd()
    ) {
      throw new Error("Mismatch presentation timing is invalid for display.");
    }
    return [start, stop];
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
      mismatch: "mismatch SDF",
      control: "control SDF",
      difference: "mismatch − control SDF",
      "mismatch-zscore": "mismatch baseline z-score",
      "control-zscore": "control baseline z-score",
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

  function heatmapAreaGroups() {
    if (state.sort !== "area" || areaOrderingMode() === "depth") return [];
    const session = currentSession();
    const field = areaOrderingMode() === "parent" ? "parentArea" : "location";
    const groups = [];
    state.sortedUnits.forEach((unitIndex, row) => {
      const label = session.units[unitIndex][field];
      const current = groups.at(-1);
      if (current?.label === label) {
        current.endRow = row + 1;
      } else {
        groups.push({ label, startRow: row, endRow: row + 1 });
      }
    });
    return groups;
  }

  function configureHeatmapHeight(areaGroups) {
    const labelHeight = areaGroups.length ? areaGroups.length * 18 + 100 : 650;
    heatmapCanvas.height = Math.max(650, labelHeight);
  }

  function plotHorizontalBounds() {
    return { left: 125, right: 1170 };
  }

  function heatmapPlot() {
    return {
      ...plotHorizontalBounds(),
      top: 20,
      bottom: heatmapCanvas.height - 80,
    };
  }

  function heatmapRowY(row, plot) {
    if (!state.sortedUnits.length) return plot.top;
    return (
      plot.top +
      (row / state.sortedUnits.length) * (plot.bottom - plot.top)
    );
  }

  function areaLabelPositions(groups, plot) {
    if (!groups.length) return [];
    const gap = 17;
    const top = plot.top + 7;
    const bottom = plot.bottom - 7;
    const positions = groups.map((group) =>
      heatmapRowY((group.startRow + group.endRow) / 2, plot),
    );
    positions[0] = Math.max(top, positions[0]);
    for (let index = 1; index < positions.length; index += 1) {
      positions[index] = Math.max(positions[index], positions[index - 1] + gap);
    }
    positions[positions.length - 1] = Math.min(
      bottom,
      positions[positions.length - 1],
    );
    for (let index = positions.length - 2; index >= 0; index -= 1) {
      positions[index] = Math.min(positions[index], positions[index + 1] - gap);
    }
    return positions;
  }

  function heatmapYAxisMetadata(areaGroups) {
    if (state.sort !== "area") {
      return {
        label: "Sorted unit ordering",
        ticks: state.sortedUnits.length
          ? [
              "0",
              String(Math.floor(state.sortedUnits.length / 2)),
              String(state.sortedUnits.length),
            ]
          : ["0"],
      };
    }
    const mode = areaOrderingMode();
    if (mode === "depth") {
      const session = currentSession();
      const depths = state.sortedUnits.map(
        (unitIndex) => session.units[unitIndex].depthUm,
      );
      return {
        label: "Depth on probe",
        ticks: depths.length
          ? [
              `${Math.round(depths[0])} µm`,
              `${Math.round(depths.at(-1))} µm`,
            ]
          : [],
      };
    }
    return {
      label: mode === "parent" ? "Parent area" : "Area",
      ticks: areaGroups.map((group) => group.label),
    };
  }

  function drawHeatmapYAxis(context, plot, areaGroups) {
    const axis = heatmapYAxisMetadata(areaGroups);
    context.save();
    context.font = '21px "Myriad Pro", Arial, sans-serif';
    context.fillStyle = "#303536";
    context.textAlign = "center";
    context.translate(25, (plot.top + plot.bottom) / 2);
    context.rotate(-Math.PI / 2);

    if (state.sort !== "area") {
      context.fillText(axis.label, 0, 0);
      context.restore();
      context.font = '18px "IBM Plex Mono", monospace';
      context.fillStyle = "#59605e";
      context.textAlign = "right";
      const rowTicks = state.sortedUnits.length
        ? [
            [axis.ticks[0], plot.top + 6],
            [
              axis.ticks[1],
              (plot.top + plot.bottom) / 2 + 6,
            ],
            [axis.ticks[2], plot.bottom + 6],
          ]
        : [[axis.ticks[0], plot.top + 6]];
      for (const [label, y] of rowTicks) {
        context.fillText(String(label), plot.left - 10, y);
      }
      return;
    }

    const mode = areaOrderingMode();
    if (mode === "depth") {
      context.fillText(axis.label, 0, 0);
      context.restore();
      context.font = '18px "IBM Plex Mono", monospace';
      context.fillStyle = "#59605e";
      context.textAlign = "right";
      if (axis.ticks.length) {
        context.fillText(axis.ticks[0], plot.left - 10, plot.top + 6);
        context.fillText(axis.ticks[1], plot.left - 10, plot.bottom + 6);
      }
      return;
    }

    context.fillText(axis.label, 0, 0);
    context.restore();
    const labelPositions = areaLabelPositions(areaGroups, plot);
    context.font = '16px "IBM Plex Mono", monospace';
    context.fillStyle = "#59605e";
    context.strokeStyle = "#8d9591";
    context.lineWidth = 1;
    context.textAlign = "right";
    areaGroups.forEach((group, index) => {
      const center = heatmapRowY((group.startRow + group.endRow) / 2, plot);
      const labelY = labelPositions[index];
      if (group.startRow > 0) {
        const boundary = heatmapRowY(group.startRow, plot);
        context.save();
        context.globalAlpha = 0.58;
        context.strokeStyle = "#ffffff";
        context.beginPath();
        context.moveTo(plot.left, boundary);
        context.lineTo(plot.right, boundary);
        context.stroke();
        context.restore();
      }
      context.beginPath();
      context.moveTo(plot.left - 3, center);
      context.lineTo(plot.left - 9, center);
      context.lineTo(plot.left - 14, labelY);
      context.stroke();
      context.fillText(group.label, plot.left - 18, labelY + 5);
    });
  }

  function drawHeatmap(atlas) {
    const session = currentSession();
    state.sortedUnits = sortedUnitIndices(atlas);
    renderUnitSelect();
    const areaGroups = heatmapAreaGroups();
    configureHeatmapHeight(areaGroups);
    const traces = state.sortedUnits.map((unitIndex) =>
      unitHeatmapTrace(atlas, unitIndex),
    );
    const baseLimit = automaticLimit(atlas, filteredUnitIndices());
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
    const plot = heatmapPlot();
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
    const ticks =
      state.context === "duration"
        ? [-1.5, -1, 0, 1, 1.5]
        : [-0.75, -0.5, 0, 0.5, 0.75];
    for (const tick of ticks) {
      const x =
        plot.left +
        ((tick - displayStart()) / (displayEnd() - displayStart())) *
          (plot.right - plot.left);
      context.strokeStyle = "#59605e";
      context.beginPath();
      context.moveTo(x, plot.bottom);
      context.lineTo(x, plot.bottom + 5);
      context.stroke();
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
    const timingValues = presentationTimingValues(timing);
    for (const value of [...new Set(timingValues)]) {
      const x =
        plot.left +
        ((value - displayStart()) / (displayEnd() - displayStart())) *
          (plot.right - plot.left);
      context.strokeStyle = Math.abs(value) < 1e-9 ? "#303536" : "#59605e";
      context.setLineDash([6, 5]);
      context.beginPath();
      context.moveTo(x, plot.top);
      context.lineTo(x, plot.bottom);
      context.stroke();
      context.setLineDash([]);
    }
    drawHeatmapYAxis(context, plot, areaGroups);
    const yAxis = heatmapYAxisMetadata(areaGroups);
    heatmapCanvas.dataset.yAxisLabel = yAxis.label;
    heatmapCanvas.dataset.yTickLabels = yAxis.ticks.join("|");
    const heatmapDescription = `${session.sessionId} · ${
      session.events[state.eventIndex].label
    } · ${metricLabel()} · ${state.sortedUnits.length.toLocaleString()} units`;
    heatmapCanvas.setAttribute(
      "aria-label",
      `${state.sortedUnits.length} unit rows by ${time.length} time bins for ${
        heatmapDescription
      }, ordered by ${
        state.sort === "area"
          ? areaOrderingMode() === "depth"
            ? "depth on probe"
            : areaOrderingMode() === "parent"
              ? "parent area in Allen graph order"
              : "exact area in Allen graph order"
          : sortSelect.selectedOptions[0]?.textContent
      }. ${yAxis.label} labels: ${yAxis.ticks.join(", ")}.`,
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
        values.length > 1
          ? values.reduce((sum, value) => sum + (value - average) ** 2, 0) /
            (values.length - 1)
          : 0;
      mean.push(average);
      sem.push(Math.sqrt(variance / values.length));
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
    const context = meanAndSem(
      indices.map((unitIndex) => {
        const baseline = atlas.baselineMean[baselineOffset(unitIndex, 0)];
        return unitRateTrace(atlas, unitIndex, 0).map(
          (value) => value - baseline,
        );
      }),
    );
    const control = meanAndSem(
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
      ((time[index] - displayStart()) / (displayEnd() - displayStart())) *
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
      if (value === null || !Number.isFinite(value)) {
        drawing = false;
        return;
      }
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
      .filter(
        (index) =>
          time[index] >= displayStart() &&
          values[index] !== null &&
          Number.isFinite(values[index]) &&
          sem[index] !== null &&
          Number.isFinite(sem[index]),
      );
    if (!visible.length) {
      context.restore();
      return;
    }
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
    const plot = { ...plotHorizontalBounds(), top: 22, bottom: 280 };
    const timing = currentSession().events[state.eventIndex].timing.context;
    if (
      Number.isFinite(timing.presentationStartSeconds) &&
      Number.isFinite(timing.presentationStopSeconds)
    ) {
      const startX =
        plot.left +
        ((timing.presentationStartSeconds - displayStart()) /
          (displayEnd() - displayStart())) *
          (plot.right - plot.left);
      const stopX =
        plot.left +
        ((timing.presentationStopSeconds - displayStart()) /
          (displayEnd() - displayStart())) *
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
      context.strokeStyle = "#59605e";
      context.beginPath();
      context.moveTo(plot.left - 5, y);
      context.lineTo(plot.left, y);
      context.stroke();
      context.textAlign = "right";
      context.fillText(formatRateTick(value), plot.left - 10, y + 6);
    }
    const ticks =
      state.context === "duration"
        ? [-1.5, -1, 0, 1, 1.5]
        : [-0.75, -0.5, 0, 0.5, 0.75];
    for (const tick of ticks) {
      const x =
        plot.left +
        ((tick - displayStart()) / (displayEnd() - displayStart())) *
          (plot.right - plot.left);
      context.strokeStyle = "#59605e";
      context.beginPath();
      context.moveTo(x, plot.bottom);
      context.lineTo(x, plot.bottom + 5);
      context.stroke();
      context.textAlign = "center";
      context.fillText(String(tick), x, plot.bottom + 27);
    }
    const timingValues = presentationTimingValues(timing);
    for (const value of [...new Set(timingValues)]) {
      const x =
        plot.left +
        ((value - displayStart()) / (displayEnd() - displayStart())) *
          (plot.right - plot.left);
      context.strokeStyle = Math.abs(value) < 1e-9 ? "#303536" : "#59605e";
      context.setLineDash([6, 5]);
      context.beginPath();
      context.moveTo(x, plot.top);
      context.lineTo(x, plot.bottom);
      context.stroke();
      context.setLineDash([]);
    }
    context.strokeStyle = "#8d9591";
    context.beginPath();
    context.moveTo(plot.left, plot.top);
    context.lineTo(plot.left, plot.bottom);
    context.lineTo(plot.right, plot.bottom);
    context.stroke();
    if (baselineSubtracted && yRange[0] <= 0 && yRange[1] >= 0) {
      const zeroY =
        plot.bottom -
        ((0 - yRange[0]) / (yRange[1] - yRange[0])) *
          (plot.bottom - plot.top);
      context.strokeStyle = "#8d9591";
      context.lineWidth = 1.5;
      context.beginPath();
      context.moveTo(plot.left, zeroY);
      context.lineTo(plot.right, zeroY);
      context.stroke();
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
      }mismatch and control spike-density functions.`,
    );
  }

  async function render() {
    const sequence = ++renderSequence;
    const session = currentSession();
    loadingMessage.hidden = false;
    try {
      const atlas = await loadAtlas(session);
      if (sequence !== renderSequence) return;
      drawHeatmap(atlas);
      if (state.selectedUnit !== null) {
        const traces = state.baselineSubtracted
          ? baselineSubtractedTraces(atlas)
          : responseTraces(atlas);
        drawResponsePanel(responseCanvas, traces, state.baselineSubtracted);
        responseTitle.textContent =
          state.scope === "area"
            ? `Mismatch response averaged over units in ${selectedAreaLabel()}`
            : `Mismatch response for unit ${session.units[state.selectedUnit].id}`;
      } else {
        const context = canvasContext(responseCanvas);
        context.fillStyle = "#68706d";
        context.textAlign = "center";
        context.font = '22px "Myriad Pro", Arial, sans-serif';
        context.fillText(
          "No units match the current filters.",
          responseCanvas.width / 2,
          responseCanvas.height / 2,
        );
        responseTitle.textContent = "Mismatch response";
      }
      loadingMessage.hidden = true;
    } catch (error) {
      if (sequence !== renderSequence) return;
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
    time = currentSession().timeBinCentersSeconds;
    document.documentElement.style.setProperty(
      "--accent",
      contextColors[state.context],
    );
    renderContextTabs();
    renderEventSelect();
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
  neuronTypeFilter.querySelectorAll("[data-neuron-type]").forEach((element) => {
    element.addEventListener("change", () => {
      const neuronType = element.dataset.neuronType;
      if (element.checked) state.neuronTypes.add(neuronType);
      else state.neuronTypes.delete(neuronType);
      renderAreaSelect();
      state.selectedUnit = null;
      render();
    });
  });
  baselineSubtractedControl.addEventListener("change", () => {
    state.baselineSubtracted = baselineSubtractedControl.checked;
    render();
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
    const plot = heatmapPlot();
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
    const capturedContext = state.context;
    const capturedEventIndex = state.eventIndex;
    const unit = currentSession().units[unitIndex];
    const relativeTime =
      displayStart() +
      ((x - plot.left) / (plot.right - plot.left)) *
        (displayEnd() - displayStart());
    const binIndex = time.reduce(
      (best, value, index) =>
        Math.abs(value - relativeTime) < Math.abs(time[best] - relativeTime)
          ? index
          : best,
      0,
    );
    const atlas = await loadAtlas(currentSession());
    if (
      state.context !== capturedContext ||
      state.eventIndex !== capturedEventIndex ||
      !state.sortedUnits.includes(unitIndex)
    ) {
      heatmapTooltip.hidden = true;
      return;
    }
    const value = unitHeatmapTrace(atlas, unitIndex)[binIndex];
    const unitLabel = state.metric.endsWith("zscore") ? "z" : "spikes/s";
    heatmapTooltip.textContent = `Unit ${unit.id} · ${unit.probe} · ${
      unit.location
    }${
      unit.parentArea === unit.location ? "" : ` (${unit.parentArea})`
    } · ${Math.round(unit.depthUm)} µm · t=${time[binIndex].toFixed(2)} s · ${
      value === null || !Number.isFinite(value)
        ? "n/a"
        : `${value.toFixed(2)} ${unitLabel}`
    } · ${unit.neuronType} · ${unit.decoderLabel.toUpperCase()} · ${
      unit.firingRateHz.toFixed(
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
    const plot = heatmapPlot();
    if (y < plot.top || y > plot.bottom) return;
    const row = Math.min(
      state.sortedUnits.length - 1,
      Math.floor(
        ((y - plot.top) / (plot.bottom - plot.top)) * state.sortedUnits.length,
      ),
    );
    state.selectedUnit = state.sortedUnits[row];
    state.scope = "unit";
    renderResponseSelection();
    setPressed(scopeTabs, "scope", state.scope);
    render();
  });

  configureSession();
})();
