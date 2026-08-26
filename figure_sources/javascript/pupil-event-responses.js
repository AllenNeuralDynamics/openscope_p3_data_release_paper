(() => {
  "use strict";

  const data = JSON.parse(document.getElementById("pupil-event-data").textContent);
  const time = data.timeGridSeconds;
  const modalityOrder = ["neuropixels", "mesoscope", "slap2"];
  const modalityLabels = {
    neuropixels: "Neuropixels",
    mesoscope: "Mesoscope",
    slap2: "SLAP2",
  };
  const contextOrder = ["standard", "sensorimotor", "sequence", "duration"];
  const contextLabels = {
    standard: "Standard",
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
    cohort: "sequence",
    context: "standard",
    eventId: null,
    modality: "neuropixels",
    mouseId: "830846",
    scale: "percent",
    scope: "mouse",
    view: "interactive",
  };

  const modalityTabs = document.getElementById("modality-tabs");
  const cohortTabs = document.getElementById("cohort-tabs");
  const contextTabs = document.getElementById("context-tabs");
  const eventSelect = document.getElementById("event-select");
  const scaleTabs = document.getElementById("scale-tabs");
  const scopeTabs = document.getElementById("scope-tabs");
  const mouseControl = document.getElementById("mouse-control");
  const mouseSelect = document.getElementById("mouse-select");
  const interactiveView = document.getElementById("interactive-view");
  const staticView = document.getElementById("static-view");
  const unavailableMessage = document.getElementById("unavailable-message");
  const plotContent = document.getElementById("plot-content");
  const selectionTitle = document.getElementById("selection-title");
  const selectionDetail = document.getElementById("selection-detail");
  const pupilTraceCanvas = document.getElementById("pupil-trace-canvas");
  const runningTraceCanvas = document.getElementById("running-trace-canvas");
  const pupilUnavailable = document.getElementById("pupil-unavailable");
  const runningUnavailable = document.getElementById("running-unavailable");
  const pupilEffectCanvas = document.getElementById("pupil-effect-canvas");
  const runningEffectCanvas = document.getElementById("running-effect-canvas");
  const pupilEffectWrapper = document.getElementById("pupil-effect-wrapper");
  const runningEffectWrapper = document.getElementById("running-effect-wrapper");
  const effectPanel = document.getElementById("effect-panel");
  const metadata = document.getElementById("analysis-metadata");

  function unique(values) {
    return [...new Set(values)];
  }

  function summariesForSelection() {
    return data.summaries.filter(
      (record) =>
        record.modality === state.modality &&
        record.cohort === state.cohort &&
        record.context === state.context,
    );
  }

  function currentSummary() {
    return summariesForSelection().find((record) => record.eventId === state.eventId);
  }

  function miceForSelection() {
    return data.mice.filter(
      (record) =>
        record.modality === state.modality &&
        record.cohort === state.cohort &&
        record.context === state.context,
    );
  }

  function currentMouseRecord() {
    return miceForSelection().find((record) => record.mouseId === state.mouseId);
  }

  function currentMouseEvent() {
    return currentMouseRecord()?.events.find(
      (event) =>
        event.id === state.eventId &&
        (event.pupilConditions || event.runningConditions),
    );
  }

  function setAccent() {
    document.documentElement.style.setProperty("--accent", contextColors[state.context]);
  }

  function button(label, value, stateKey, click) {
    const element = document.createElement("button");
    element.type = "button";
    element.textContent = label;
    element.dataset[stateKey] = value;
    element.setAttribute("aria-pressed", String(state[stateKey] === value));
    element.addEventListener("click", click);
    return element;
  }

  function renderModalityTabs() {
    modalityTabs.replaceChildren();
    for (const modality of modalityOrder) {
      if (!data.summaries.some((record) => record.modality === modality)) continue;
      const element = button(modalityLabels[modality], modality, "modality", () => {
        state.modality = modality;
        configureSelection();
      });
      const logo = document.createElement("img");
      logo.src = data.platformLogos[modality];
      logo.alt = "";
      element.prepend(logo);
      modalityTabs.append(element);
    }
  }

  function availableCohorts() {
    return unique(
      data.summaries
        .filter((record) => record.modality === state.modality)
        .map((record) => record.cohort),
    );
  }

  function renderCohortTabs() {
    const cohorts = availableCohorts();
    if (!cohorts.includes(state.cohort)) state.cohort = cohorts[0];
    cohortTabs.replaceChildren();
    for (const cohort of cohorts) {
      cohortTabs.append(
        button(
          cohort === "motor" ? "Motor" : "Sequence",
          cohort,
          "cohort",
          () => {
            state.cohort = cohort;
            configureSelection();
          },
        ),
      );
    }
  }

  function availableContexts() {
    return contextOrder.filter((context) =>
      data.summaries.some(
        (record) =>
          record.modality === state.modality &&
          record.cohort === state.cohort &&
          record.context === context,
      ),
    );
  }

  function renderContextTabs() {
    const contexts = availableContexts();
    if (!contexts.includes(state.context)) state.context = contexts[0];
    contextTabs.replaceChildren();
    for (const context of contexts) {
      contextTabs.append(
        button(contextLabels[context], context, "context", () => {
          state.context = context;
          configureSelection();
        }),
      );
    }
  }

  function renderEventSelect() {
    const summaries = summariesForSelection();
    const previous = state.eventId;
    eventSelect.replaceChildren();
    for (const summary of summaries) {
      const option = document.createElement("option");
      option.value = summary.eventId;
      option.textContent = summary.label;
      eventSelect.append(option);
    }
    state.eventId = summaries.some((summary) => summary.eventId === previous)
      ? previous
      : summaries[0]?.eventId;
    eventSelect.value = state.eventId || "";
  }

  function availableMice() {
    return miceForSelection()
      .filter((mouse) =>
        mouse.events.some(
          (event) =>
            event.id === state.eventId &&
            (event.pupilConditions || event.runningConditions),
        ),
      )
      .map((mouse) => mouse.mouseId)
      .sort();
  }

  function renderMouseSelect() {
    const mice = availableMice();
    if (!mice.includes(state.mouseId)) state.mouseId = mice[0] || null;
    mouseSelect.replaceChildren();
    for (const mouseId of mice) {
      const option = document.createElement("option");
      option.value = mouseId;
      option.textContent = mouseId;
      mouseSelect.append(option);
    }
    mouseSelect.value = state.mouseId || "";
  }

  function configureSelection() {
    renderModalityTabs();
    renderCohortTabs();
    renderContextTabs();
    renderEventSelect();
    renderMouseSelect();
    setAccent();
    render();
  }

  function finiteValues(traces) {
    return traces.flatMap((trace) =>
      trace.filter((value) => value !== null && Number.isFinite(value)),
    );
  }

  function displayEnd() {
    return 4;
  }

  function visibleTrace(trace) {
    return trace.filter((_, index) => time[index] <= displayEnd());
  }

  function rangeForTraces(traces, includeZero) {
    const values = finiteValues(traces.map(visibleTrace));
    if (!values.length) return [0, 1];
    let minimum = Math.min(...values);
    let maximum = Math.max(...values);
    if (includeZero) {
      minimum = Math.min(0, minimum);
      maximum = Math.max(0, maximum);
    }
    const span = Math.max(maximum - minimum, Math.max(Math.abs(minimum), Math.abs(maximum)) * 0.1, 1);
    return [minimum - span * 0.08, maximum + span * 0.08];
  }

  function canvasContext(canvas) {
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.font = '22px "Myriad Pro", Arial, sans-serif';
    context.fillStyle = "#303536";
    context.strokeStyle = "#303536";
    context.lineWidth = 2;
    return context;
  }

  function traceCoordinates(value, index, plot, yRange) {
    const x =
      plot.left +
      ((time[index] - time[0]) / (displayEnd() - time[0])) *
        (plot.right - plot.left);
    const y =
      plot.bottom -
      ((value - yRange[0]) / (yRange[1] - yRange[0])) * (plot.bottom - plot.top);
    return [x, y];
  }

  function drawAxes(context, plot, yRange, yLabel) {
    context.save();
    context.strokeStyle = "#d5d9d7";
    context.fillStyle = "#59605e";
    context.lineWidth = 1;
    context.font = '19px "IBM Plex Mono", monospace';
    const axisValues = [yRange[0], yRange[1]];
    axisValues.push(
      yRange[0] < 0 && yRange[1] > 0
        ? 0
        : (yRange[0] + yRange[1]) / 2,
    );
    axisValues.sort((left, right) => left - right);
    for (const value of axisValues) {
      const fraction = (value - yRange[0]) / (yRange[1] - yRange[0]);
      const y = plot.bottom - fraction * (plot.bottom - plot.top);
      context.beginPath();
      context.moveTo(plot.left, y);
      context.lineTo(plot.right, y);
      context.strokeStyle = Math.abs(value) < 1e-9 ? "#707674" : "#d5d9d7";
      context.stroke();
      context.textAlign = "right";
      context.fillText(
        Math.abs(value) < 1e-9
          ? "0"
          : value.toFixed(Math.abs(value) < 10 ? 1 : 0),
        plot.left - 12,
        y + 6,
      );
    }
    for (const tick of [-2, 0, 2, 4]) {
      const x =
        plot.left +
        ((tick - time[0]) / (displayEnd() - time[0])) *
          (plot.right - plot.left);
      context.beginPath();
      context.moveTo(x, plot.bottom);
      context.lineTo(x, plot.bottom + 7);
      context.strokeStyle = tick === 0 ? "#303536" : "#d5d9d7";
      context.stroke();
      if (tick === 0) {
        context.setLineDash([6, 5]);
        context.beginPath();
        context.moveTo(x, plot.top);
        context.lineTo(x, plot.bottom);
        context.stroke();
        context.setLineDash([]);
      }
      context.fillStyle = "#59605e";
      context.textAlign = "center";
      context.fillText(String(tick), x, plot.bottom + 30);
    }
    context.font = '21px "Myriad Pro", Arial, sans-serif';
    context.fillText("Time from stimulus-table start_time (s)", (plot.left + plot.right) / 2, plot.bottom + 62);
    context.save();
    context.translate(26, (plot.top + plot.bottom) / 2);
    context.rotate(-Math.PI / 2);
    context.fillText(yLabel, 0, 0);
    context.restore();
    context.restore();
  }

  function drawEffectAxes(context, plot, yRange, responseWindowLabel, yLabel) {
    context.save();
    context.strokeStyle = "#d5d9d7";
    context.fillStyle = "#59605e";
    context.lineWidth = 1;
    context.font = '19px "IBM Plex Mono", monospace';
    for (const fraction of [0, 0.5, 1]) {
      const y = plot.bottom - fraction * (plot.bottom - plot.top);
      const value = yRange[0] + fraction * (yRange[1] - yRange[0]);
      context.beginPath();
      context.moveTo(plot.left, y);
      context.lineTo(plot.right, y);
      context.stroke();
      context.textAlign = "right";
      context.fillText(
        value.toFixed(Math.abs(value) < 10 ? 1 : 0),
        plot.left - 12,
        y + 6,
      );
    }
    if (yRange[0] < 0 && yRange[1] > 0) {
      const zeroY =
        plot.bottom -
        ((0 - yRange[0]) / (yRange[1] - yRange[0])) * (plot.bottom - plot.top);
      context.beginPath();
      context.moveTo(plot.left, zeroY);
      context.lineTo(plot.right, zeroY);
      context.strokeStyle = "#707674";
      context.stroke();
      context.fillStyle = "#59605e";
      context.textAlign = "right";
      context.fillText("0", plot.left - 12, zeroY + 6);
    }
    context.font = '21px "Myriad Pro", Arial, sans-serif';
    context.textAlign = "center";
    context.fillText(
      `Mouse effects; response window ${responseWindowLabel}`,
      (plot.left + plot.right) / 2,
      plot.bottom + 38,
    );
    context.save();
    context.translate(26, (plot.top + plot.bottom) / 2);
    context.rotate(-Math.PI / 2);
    context.fillText(yLabel, 0, 0);
    context.restore();
    context.restore();
  }

  function drawLine(context, values, plot, yRange, color, dashed = false) {
    context.save();
    context.strokeStyle = color;
    context.lineWidth = 4;
    if (dashed) context.setLineDash([12, 9]);
    context.beginPath();
    let drawing = false;
    values.forEach((value, index) => {
      if (time[index] > displayEnd()) return;
      if (value === null || !Number.isFinite(value)) {
        drawing = false;
        return;
      }
      const [x, y] = traceCoordinates(value, index, plot, yRange);
      if (drawing) context.lineTo(x, y);
      else context.moveTo(x, y);
      drawing = true;
    });
    context.stroke();
    context.restore();
  }

  function drawBand(context, lower, upper, plot, yRange, color) {
    context.save();
    context.fillStyle = color;
    context.globalAlpha = 0.13;
    const runs = [];
    let run = [];
    for (let index = 0; index < lower.length; index += 1) {
      if (
        time[index] <= displayEnd() &&
        lower[index] !== null &&
        upper[index] !== null
      ) {
        run.push(index);
      } else if (run.length) {
        runs.push(run);
        run = [];
      }
    }
    if (run.length) runs.push(run);
    if (!runs.length) {
      context.restore();
      return;
    }
    for (const indices of runs) {
      context.beginPath();
      indices.forEach((index, position) => {
        const [x, y] = traceCoordinates(upper[index], index, plot, yRange);
        if (position) context.lineTo(x, y);
        else context.moveTo(x, y);
      });
      [...indices].reverse().forEach((index) => {
        const [x, y] = traceCoordinates(lower[index], index, plot, yRange);
        context.lineTo(x, y);
      });
      context.closePath();
      context.fill();
    }
    context.restore();
  }

  function uncertaintyBounds(mean, sem) {
    return {
      lower: mean.map((value, index) =>
        value === null || sem[index] === null ? null : value - sem[index],
      ),
      upper: mean.map((value, index) =>
        value === null || sem[index] === null ? null : value + sem[index],
      ),
    };
  }

  function renderPercentTrace(summary) {
    const pupil = summary.pupil;
    const event = pupil.eventPercentChangeTrace;
    const control = pupil.controlPercentChangeTrace;
    const traces = [
      event.lower,
      event.upper,
      control.lower,
      control.upper,
    ];
    const yRange = rangeForTraces(traces, true);
    const context = canvasContext(pupilTraceCanvas);
    const plot = { left: 105, right: 1170, top: 28, bottom: 340 };
    drawAxes(context, plot, yRange, "Pupil area (% baseline)");
    drawBand(context, control.lower, control.upper, plot, yRange, "#8a918e");
    drawBand(context, event.lower, event.upper, plot, yRange, contextColors[state.context]);
    drawLine(context, control.mean, plot, yRange, "#8a918e", true);
    drawLine(context, event.mean, plot, yRange, contextColors[state.context]);
    pupilTraceCanvas.setAttribute(
      "aria-label",
      `${summary.label} mean pupil percent-change traces for ${modalityLabels[state.modality]} ${state.cohort} cohort, plus or minus one standard error across mice.`,
    );
  }

  function renderMousePercentTrace() {
    const conditions = currentMouseEvent().pupilConditions;
    const event = conditions.event;
    const control = conditions.control;
    const eventBounds = uncertaintyBounds(
      event.percentChangeMeanTrace,
      event.percentChangeSemTrace,
    );
    const controlBounds = uncertaintyBounds(
      control.percentChangeMeanTrace,
      control.percentChangeSemTrace,
    );
    const yRange = rangeForTraces(
      [eventBounds.lower, eventBounds.upper, controlBounds.lower, controlBounds.upper],
      true,
    );
    const context = canvasContext(pupilTraceCanvas);
    const plot = { left: 105, right: 1170, top: 28, bottom: 340 };
    drawAxes(context, plot, yRange, "Pupil area (% baseline)");
    drawBand(
      context,
      controlBounds.lower,
      controlBounds.upper,
      plot,
      yRange,
      "#8a918e",
    );
    drawBand(
      context,
      eventBounds.lower,
      eventBounds.upper,
      plot,
      yRange,
      contextColors[state.context],
    );
    drawLine(context, control.percentChangeMeanTrace, plot, yRange, "#8a918e", true);
    drawLine(
      context,
      event.percentChangeMeanTrace,
      plot,
      yRange,
      contextColors[state.context],
    );
    pupilTraceCanvas.setAttribute(
      "aria-label",
      `${summaryLabel()} mean pupil percent-change traces plus or minus one standard error across valid trials for mouse ${state.mouseId}.`,
    );
  }

  function renderRawTrace() {
    const conditions = currentMouseEvent().pupilConditions;
    const event = conditions.event;
    const control = conditions.control;
    const eventBounds = uncertaintyBounds(event.rawMeanTrace, event.rawSemTrace);
    const controlBounds = uncertaintyBounds(control.rawMeanTrace, control.rawSemTrace);
    const yRange = rangeForTraces(
      [eventBounds.lower, eventBounds.upper, controlBounds.lower, controlBounds.upper],
      false,
    );
    const context = canvasContext(pupilTraceCanvas);
    const plot = { left: 125, right: 1170, top: 28, bottom: 340 };
    drawAxes(context, plot, yRange, "Pupil area (px²)");
    drawBand(
      context,
      controlBounds.lower,
      controlBounds.upper,
      plot,
      yRange,
      "#8a918e",
    );
    drawBand(
      context,
      eventBounds.lower,
      eventBounds.upper,
      plot,
      yRange,
      contextColors[state.context],
    );
    drawLine(context, control.rawMeanTrace, plot, yRange, "#8a918e", true);
    drawLine(context, event.rawMeanTrace, plot, yRange, contextColors[state.context]);
    pupilTraceCanvas.setAttribute(
      "aria-label",
      `${summaryLabel()} raw mean pupil-area traces plus or minus one standard error across valid trials for mouse ${state.mouseId}.`,
    );
  }

  function renderPopulationRunning(summary) {
    const running = summary.running;
    const event = running.eventBaselineChangeTrace;
    const control = running.controlBaselineChangeTrace;
    const yRange = rangeForTraces(
      [event.lower, event.upper, control.lower, control.upper],
      true,
    );
    const context = canvasContext(runningTraceCanvas);
    const plot = { left: 105, right: 1170, top: 28, bottom: 340 };
    drawAxes(context, plot, yRange, "Δ forward speed (cm/s)");
    drawBand(context, control.lower, control.upper, plot, yRange, "#8a918e");
    drawBand(context, event.lower, event.upper, plot, yRange, contextColors[state.context]);
    drawLine(context, control.mean, plot, yRange, "#8a918e", true);
    drawLine(context, event.mean, plot, yRange, contextColors[state.context]);
    runningTraceCanvas.setAttribute(
      "aria-label",
      `${summary.label} mean baseline-subtracted forward-running traces for ${modalityLabels[state.modality]} ${state.cohort} cohort, plus or minus one standard error across mice.`,
    );
  }

  function renderMouseRunning(raw) {
    const conditions = currentMouseEvent().runningConditions;
    const event = conditions.event;
    const control = conditions.control;
    const meanField = raw ? "rawMeanTrace" : "baselineChangeMeanTrace";
    const semField = raw ? "rawSemTrace" : "baselineChangeSemTrace";
    const eventBounds = uncertaintyBounds(event[meanField], event[semField]);
    const controlBounds = uncertaintyBounds(control[meanField], control[semField]);
    const yRange = rangeForTraces(
      [eventBounds.lower, eventBounds.upper, controlBounds.lower, controlBounds.upper],
      !raw,
    );
    const context = canvasContext(runningTraceCanvas);
    const plot = { left: 105, right: 1170, top: 28, bottom: 340 };
    drawAxes(
      context,
      plot,
      yRange,
      raw ? "Forward speed (cm/s)" : "Δ forward speed (cm/s)",
    );
    drawBand(
      context,
      controlBounds.lower,
      controlBounds.upper,
      plot,
      yRange,
      "#8a918e",
    );
    drawBand(
      context,
      eventBounds.lower,
      eventBounds.upper,
      plot,
      yRange,
      contextColors[state.context],
    );
    drawLine(context, control[meanField], plot, yRange, "#8a918e", true);
    drawLine(context, event[meanField], plot, yRange, contextColors[state.context]);
    runningTraceCanvas.setAttribute(
      "aria-label",
      `${summaryLabel()} ${raw ? "raw" : "baseline-subtracted"} forward-running traces plus or minus one standard error across valid trials for mouse ${state.mouseId}.`,
    );
  }

  function renderEffect(canvas, response, summary, yLabel, ariaUnit) {
    const values = response.points.map((point) => point.value);
    const yRange = rangeForTraces([values], true);
    const context = canvasContext(canvas);
    const plot = { left: 105, right: 1170, top: 25, bottom: 180 };
    drawEffectAxes(context, plot, yRange, summary.responseWindowLabel, yLabel);
    const center = (plot.left + plot.right) / 2;
    context.strokeStyle = "#303536";
    context.lineWidth = 5;
    const y = (value) =>
      plot.bottom - ((value - yRange[0]) / (yRange[1] - yRange[0])) * (plot.bottom - plot.top);
    context.beginPath();
    context.moveTo(center, y(response.lower));
    context.lineTo(center, y(response.upper));
    context.stroke();
    response.points.forEach((point, index) => {
      const jitter = ((index * 37) % 17) - 8;
      context.beginPath();
      context.fillStyle = contextColors[state.context];
      context.globalAlpha = 0.72;
      context.arc(center + jitter * 3, y(point.value), 7, 0, Math.PI * 2);
      context.fill();
    });
    context.globalAlpha = 1;
    context.beginPath();
    context.fillStyle = "#ffffff";
    context.strokeStyle = "#303536";
    context.lineWidth = 4;
    context.arc(center, y(response.mean), 10, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    canvas.setAttribute(
      "aria-label",
      `${response.points.length} mouse-level event-minus-control effects with mean ${response.mean.toFixed(2)} ${ariaUnit}.`,
    );
  }

  function summaryLabel() {
    return eventSelect.selectedOptions[0]?.textContent || state.eventId;
  }

  function metadataRows(rows) {
    metadata.replaceChildren();
    for (const [term, value] of rows) {
      const wrapper = document.createElement("div");
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = term;
      dd.textContent = value;
      wrapper.append(dt, dd);
      metadata.append(wrapper);
    }
  }

  function setPanelAvailability(canvas, message, available, reason) {
    canvas.hidden = !available;
    message.hidden = available;
    message.textContent = available ? "" : reason;
  }

  function render() {
    const summary = currentSummary();
    if (!summary) return;
    const mouseEvent = currentMouseEvent();
    const pupilAvailable =
      state.scope === "population"
        ? summary.pupilAvailability.available
        : Boolean(mouseEvent?.pupilConditions);
    const runningAvailable =
      state.scope === "population"
        ? summary.runningAvailability.available && Boolean(summary.running)
        : Boolean(mouseEvent?.runningConditions);
    const unavailable = !pupilAvailable && !runningAvailable;
    unavailableMessage.hidden = !unavailable;
    plotContent.hidden = unavailable;
    if (unavailable) {
      unavailableMessage.textContent =
        state.scope === "population"
          ? "Neither pupil tracking nor running speed has sufficient source-backed coverage for this selection."
          : `Neither pupil tracking nor running speed is available for mouse ${state.mouseId} in this selection.`;
      return;
    }
    mouseControl.hidden = state.scope !== "mouse";
    effectPanel.hidden = state.scope === "mouse";
    setPanelAvailability(
      pupilTraceCanvas,
      pupilUnavailable,
      pupilAvailable,
      state.scope === "population"
        ? summary.pupilAvailability.reason
        : `Pupil tracking is unavailable after trial-level quality control for mouse ${state.mouseId}.`,
    );
    setPanelAvailability(
      runningTraceCanvas,
      runningUnavailable,
      runningAvailable,
      state.scope === "population"
        ? summary.runningAvailability.reason
        : `Processed running speed is unavailable for mouse ${state.mouseId} in this source session.`,
    );
    pupilEffectWrapper.hidden = !pupilAvailable;
    runningEffectWrapper.hidden = !runningAvailable;
    selectionTitle.textContent = `${modalityLabels[state.modality]} · ${state.cohort === "motor" ? "Motor" : "Sequence"} cohort · ${contextLabels[state.context]}`;
    selectionDetail.textContent =
      state.scope === "mouse"
        ? `${summary.label} · mouse ${state.mouseId}`
        : summary.label;
    if (state.scope === "population") {
      if (pupilAvailable) renderPercentTrace(summary);
      if (runningAvailable) renderPopulationRunning(summary);
      if (pupilAvailable) {
        renderEffect(
          pupilEffectCanvas,
          summary.pupil.responsePercentChange,
          summary,
          "Event − control (%)",
          "percent",
        );
      }
      if (runningAvailable) {
        renderEffect(
          runningEffectCanvas,
          summary.running.responseChangeCmS,
          summary,
          "Event − control (cm/s)",
          "centimeters per second",
        );
      }
      metadataRows([
        [
          "Mice",
          `pupil ${summary.pupil?.mouseCount || 0}; running ${summary.running?.mouseCount || 0}`,
        ],
        ["Response window", summary.responseWindowLabel],
        ["Baseline", data.baselineDescriptions[state.context]],
        ["Alignment", "NWB start_time"],
        ["Trace uncertainty", "mean ±1 SEM across mice"],
        ["Scalar uncertainty", "95% mouse-bootstrap interval"],
        ["Trace sampling", "20 Hz linear interpolation; no temporal filtering"],
      ]);
    } else {
      if (pupilAvailable) {
        if (state.scale === "percent") renderMousePercentTrace();
        else renderRawTrace();
      }
      if (runningAvailable) renderMouseRunning(state.scale === "raw");
      const mouse = currentMouseRecord();
      const pupilEventTrials = mouseEvent?.pupilConditions?.event.validTrials || 0;
      const pupilControlTrials = mouseEvent?.pupilConditions?.control.validTrials || 0;
      const runningEventTrials = mouseEvent?.runningConditions?.event.validTrials || 0;
      const runningControlTrials =
        mouseEvent?.runningConditions?.control.validTrials || 0;
      metadataRows([
        ["Mouse", state.mouseId],
        ["Sessions", String(mouse.sessionCount)],
        ["Running source sessions", String(mouse.runningSourceSessionCount)],
        [
          "Valid event trials",
          `pupil ${pupilEventTrials}; running ${runningEventTrials}`,
        ],
        [
          "Valid control trials",
          `pupil ${pupilControlTrials}; running ${runningControlTrials}`,
        ],
        ["Response window", summary.responseWindowLabel],
        [
          "Trace summary",
          "mean ±1 SEM across valid trials; repeated sessions combined within mouse",
        ],
        ["Trace sampling", "20 Hz linear interpolation; no temporal filtering"],
      ]);
    }
  }

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

  scaleTabs.querySelectorAll("[data-scale]").forEach((element) => {
    element.addEventListener("click", () => {
      state.scale = element.dataset.scale;
      if (state.scale === "raw") state.scope = "mouse";
      scaleTabs.querySelectorAll("[data-scale]").forEach((buttonElement) => {
        buttonElement.setAttribute(
          "aria-pressed",
          String(buttonElement.dataset.scale === state.scale),
        );
      });
      scopeTabs.querySelectorAll("[data-scope]").forEach((buttonElement) => {
        const populationDisabled =
          state.scale === "raw" && buttonElement.dataset.scope === "population";
        buttonElement.disabled = populationDisabled;
        buttonElement.setAttribute(
          "aria-pressed",
          String(buttonElement.dataset.scope === state.scope),
        );
      });
      render();
    });
  });
  scopeTabs.querySelectorAll("[data-scope]").forEach((element) => {
    element.addEventListener("click", () => {
      if (element.disabled) return;
      state.scope = element.dataset.scope;
      scopeTabs.querySelectorAll("[data-scope]").forEach((buttonElement) => {
        buttonElement.setAttribute(
          "aria-pressed",
          String(buttonElement.dataset.scope === state.scope),
        );
      });
      render();
    });
  });
  eventSelect.addEventListener("change", () => {
    state.eventId = eventSelect.value;
    renderMouseSelect();
    render();
  });
  mouseSelect.addEventListener("change", () => {
    state.mouseId = mouseSelect.value;
    render();
  });

  configureSelection();
})();
