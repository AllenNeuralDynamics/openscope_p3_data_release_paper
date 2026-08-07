(() => {
  "use strict";

  const protocol = JSON.parse(document.getElementById("eye-tracking-data").textContent);
  const elements = {
    areaLabel: document.getElementById("area-label"),
    areaValue: document.getElementById("area-value"),
    contextLabel: document.getElementById("context-label"),
    ellipseValue: document.getElementById("ellipse-value"),
    eventLabel: document.getElementById("event-label"),
    field: document.getElementById("pupil-field"),
    fieldBounds: document.getElementById("field-bounds"),
    fieldHeading: document.getElementById("field-heading"),
    fitSelector: document.getElementById("fit-selector"),
    interactiveView: document.getElementById("interactive-view"),
    modalitySelector: document.getElementById("modality-selector"),
    orientationValue: document.getElementById("orientation-value"),
    playIcon: document.getElementById("play-icon"),
    playToggle: document.getElementById("play-toggle"),
    playbackTime: document.getElementById("playback-time"),
    sessionTitle: document.getElementById("session-title"),
    sourceLinks: document.getElementById("source-links"),
    spatialFrequency: document.getElementById("spatial-frequency"),
    staticView: document.getElementById("static-view"),
    stimulusCanvas: document.getElementById("stimulus-canvas"),
    streamStatus: document.getElementById("stream-status"),
    temporalFrequency: document.getElementById("temporal-frequency"),
    timeline: document.getElementById("timeline"),
    trace: document.getElementById("pupil-trace"),
    traceHeading: document.getElementById("trace-heading"),
    traceValue: document.getElementById("trace-value"),
    trackingStatus: document.getElementById("tracking-status"),
    trialNumber: document.getElementById("trial-number"),
    trialType: document.getElementById("trial-type"),
    video: document.getElementById("eye-video"),
    videoBlinkBadge: document.getElementById("video-blink-badge"),
    videoStage: document.getElementById("video-stage"),
    videoUnavailable: document.getElementById("video-unavailable"),
    viewButtons: document.querySelectorAll(".view-button"),
    xValue: document.getElementById("x-value"),
    yValue: document.getElementById("y-value"),
  };
  const state = {
    fitId: "pupil",
    localTime: 0,
    playing: false,
    sessionIndex: 0,
    videoToken: 0,
    view: "interactive",
  };
  const fitOrder = ["pupil", "corneal_reflection", "ellipse"];
  const contextColors = { "Standard oddball": "#22bcad" };

  function currentSession() {
    return protocol.sessions[state.sessionIndex];
  }

  function currentFit() {
    return currentSession().fits[state.fitId];
  }

  function selectView(view) {
    state.view = view;
    if (view === "static") pause();
    elements.interactiveView.hidden = view !== "interactive";
    elements.staticView.hidden = view !== "static";
    elements.viewButtons.forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function videoTimeAt(localTime) {
    const mapping = currentSession().camera.timeMap;
    if (localTime <= mapping[0][0]) return mapping[0][1];
    if (localTime >= mapping[mapping.length - 1][0]) return mapping[mapping.length - 1][1];
    let low = 0;
    let high = mapping.length - 1;
    while (low + 1 < high) {
      const middle = Math.floor((low + high) / 2);
      if (mapping[middle][0] <= localTime) low = middle;
      else high = middle;
    }
    const first = mapping[low];
    const second = mapping[high];
    const fraction = (localTime - first[0]) / (second[0] - first[0]);
    return first[1] + (second[1] - first[1]) * fraction;
  }

  function localTimeAt(videoTime) {
    const mapping = currentSession().camera.timeMap;
    if (videoTime <= mapping[0][1]) return mapping[0][0];
    if (videoTime >= mapping[mapping.length - 1][1]) return mapping[mapping.length - 1][0];
    let low = 0;
    let high = mapping.length - 1;
    while (low + 1 < high) {
      const middle = Math.floor((low + high) / 2);
      if (mapping[middle][1] <= videoTime) low = middle;
      else high = middle;
    }
    const first = mapping[low];
    const second = mapping[high];
    const fraction = (videoTime - first[1]) / (second[1] - first[1]);
    return first[0] + (second[0] - first[0]) * fraction;
  }

  function formatTime(seconds) {
    const bounded = Math.max(0, Math.min(protocol.durationSeconds, seconds));
    const whole = Math.floor(bounded);
    const tenths = Math.floor((bounded - whole) * 10);
    return `00:${String(whole).padStart(2, "0")}.${tenths}`;
  }

  function sampleAt(time) {
    const samples = currentFit().samples;
    let low = 0;
    let high = samples.length - 1;
    while (low + 1 < high) {
      const middle = Math.floor((low + high) / 2);
      if (samples[middle][0] <= time) low = middle;
      else high = middle;
    }
    return Math.abs(samples[high][0] - time) < Math.abs(samples[low][0] - time)
      ? samples[high]
      : samples[low];
  }

  function buildModalityTabs() {
    protocol.sessions.forEach((session, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "modality-tab";
      button.textContent = session.label;
      button.setAttribute("aria-label", `${session.label}, mouse ${session.subject}`);
      button.addEventListener("click", () => selectSession(index));
      elements.modalitySelector.append(button);
    });
  }

  function buildFitTabs() {
    fitOrder.forEach((fitId) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "fit-tab";
      button.dataset.fitId = fitId;
      button.textContent = currentSession().fits[fitId].label;
      button.addEventListener("click", () => selectFit(fitId));
      elements.fitSelector.append(button);
    });
  }

  function configureFit() {
    const fit = currentFit();
    const reference = fit.fieldReference;
    elements.fitSelector.querySelectorAll("button").forEach((button) => {
      const active = button.dataset.fitId === state.fitId;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    elements.fieldHeading.textContent = `${fit.label} center field`;
    elements.areaLabel.textContent = `${fit.label} area`;
    elements.traceHeading.textContent = `${fit.label} area`;
    elements.field.setAttribute(
      "aria-label",
      `${fit.label} center and area at the current recording time`,
    );
    elements.trace.setAttribute(
      "aria-label",
      `${fit.label} area trace with blink intervals and synchronized playback cursor`,
    );
    elements.field.width = reference.frameWidth;
    elements.field.height = reference.frameHeight;
    elements.field.style.aspectRatio = `${reference.frameWidth} / ${reference.frameHeight}`;
    elements.videoStage.style.aspectRatio = `${reference.frameWidth} / ${reference.frameHeight}`;
    elements.fieldBounds.textContent = `${reference.frameWidth} × ${reference.frameHeight} px frame`;
  }

  function selectFit(fitId) {
    state.fitId = fitId;
    configureFit();
    render();
  }

  function renderSourceLinks() {
    elements.sourceLinks.replaceChildren();
    currentSession().sourceLinks.forEach((source) => {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = source.label;
      elements.sourceLinks.append(link);
    });
  }

  function selectSession(index) {
    pause();
    state.sessionIndex = index;
    state.localTime = 0;
    const session = currentSession();
    document.documentElement.style.setProperty(
      "--accent",
      contextColors[session.context] || "#496375",
    );
    elements.modalitySelector.querySelectorAll("button").forEach((button, buttonIndex) => {
      const active = buttonIndex === index;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    elements.contextLabel.textContent = session.context;
    elements.sessionTitle.textContent = `Mouse ${session.subject} · ${session.session}`;
    elements.eventLabel.textContent = `${session.event.label} · ${formatTime(session.event.time)}`;
    configureFit();
    renderSourceLinks();
    loadVideo();
    render();
  }

  function loadVideo(resume = false) {
    const token = ++state.videoToken;
    elements.streamStatus.textContent = "Loading S3 stream";
    elements.videoUnavailable.hidden = true;
    elements.video.src = currentSession().camera.url;
    elements.video.load();
    const seekVideo = () => {
      if (token === state.videoToken) elements.video.currentTime = videoTimeAt(state.localTime);
    };
    const ready = () => {
      if (token !== state.videoToken) return;
      elements.streamStatus.textContent = "S3 stream ready";
      if (resume) play();
    };
    elements.video.addEventListener("loadedmetadata", seekVideo, { once: true });
    elements.video.addEventListener("seeked", ready, { once: true });
  }

  function videoFailed() {
    elements.streamStatus.textContent = "S3 stream unavailable";
    elements.videoUnavailable.hidden = false;
    pause();
  }

  function seek(localTime) {
    state.localTime = Math.max(0, Math.min(protocol.durationSeconds, localTime));
    if (elements.video.readyState >= 1) elements.video.currentTime = videoTimeAt(state.localTime);
    render();
  }

  async function play() {
    if (state.localTime >= protocol.durationSeconds - 0.02) seek(0);
    state.playing = true;
    updatePlayState();
    try {
      await elements.video.play();
    } catch {
      state.playing = false;
      updatePlayState();
    }
    requestAnimationFrame(tick);
  }

  function pause() {
    state.playing = false;
    elements.video.pause();
    updatePlayState();
  }

  function togglePlay() {
    if (state.playing) pause();
    else play();
  }

  function updatePlayState() {
    elements.playIcon.innerHTML = state.playing ? "&#10074;&#10074;" : "&#9654;";
    const label = state.playing ? "Pause synchronized excerpt" : "Play synchronized excerpt";
    elements.playToggle.setAttribute("aria-label", label);
    elements.playToggle.title = state.playing ? "Pause" : "Play";
  }

  function tick() {
    if (!state.playing) return;
    if (elements.video.readyState >= 2) state.localTime = localTimeAt(elements.video.currentTime);
    else state.localTime += 1 / 60;
    if (state.localTime >= protocol.durationSeconds) {
      seek(protocol.durationSeconds);
      pause();
      return;
    }
    render();
    requestAnimationFrame(tick);
  }

  function activeStimulus() {
    return currentSession().stimulus.find(
      (row) => row.start <= state.localTime && state.localTime < row.end,
    );
  }

  function drawStimulus(row) {
    const canvas = elements.stimulusCanvas;
    const context = canvas.getContext("2d");
    if (!row) {
      context.fillStyle = "#777";
      context.fillRect(0, 0, canvas.width, canvas.height);
      elements.trialType.textContent = "Inter-stimulus interval";
      elements.trialNumber.textContent = "-";
      elements.orientationValue.textContent = "gray";
      elements.spatialFrequency.textContent = "-";
      elements.temporalFrequency.textContent = "-";
      return;
    }
    const image = context.createImageData(canvas.width, canvas.height);
    const angle = row.orientationDegrees * Math.PI / 180;
    const cosine = Math.cos(angle);
    const sine = Math.sin(angle);
    const elapsed = Math.max(0, state.localTime - row.start);
    const phase = row.phaseCycles - elapsed * row.temporalFrequency;
    for (let y = 0; y < canvas.height; y += 1) {
      const yDegrees = (y / canvas.height - 0.5) * 95;
      for (let x = 0; x < canvas.width; x += 1) {
        const xDegrees = (x / canvas.width - 0.5) * 120;
        const coordinate = xDegrees * cosine + yDegrees * sine;
        const luminance = Math.round(
          128 + 127 * row.contrast * Math.cos(2 * Math.PI * (coordinate * row.spatialFrequency + phase)),
        );
        const pixel = (y * canvas.width + x) * 4;
        image.data[pixel] = luminance;
        image.data[pixel + 1] = luminance;
        image.data[pixel + 2] = luminance;
        image.data[pixel + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
    elements.trialType.textContent = row.trialType.replaceAll("_", " ");
    elements.trialNumber.textContent = row.trialNumber;
    elements.orientationValue.textContent = `${row.orientationDegrees.toFixed(0)} deg`;
    elements.spatialFrequency.textContent = `${row.spatialFrequency.toFixed(2)} cyc/deg`;
    elements.temporalFrequency.textContent = `${row.temporalFrequency.toFixed(1)} Hz`;
  }

  function drawField(sample) {
    const [, xValue, yValue, width, height, area, blink] = sample;
    const reference = currentFit().fieldReference;
    const canvas = elements.field;
    const context = canvas.getContext("2d");
    const inFrame = xValue >= 0
      && xValue < reference.frameWidth
      && yValue >= 0
      && yValue < reference.frameHeight;
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (blink) {
      context.fillStyle = "#111817";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = "#fff";
      context.font = "700 22px Myriad Pro, Arial, sans-serif";
      context.textAlign = "center";
      context.fillText("BLINK", canvas.width / 2, canvas.height / 2 + 7);
    } else if (inFrame) {
      context.fillStyle = "#f6f7f7";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.strokeStyle = "#d9dddb";
      context.lineWidth = 1;
      for (const fraction of [0.25, 0.5, 0.75]) {
        context.beginPath();
        context.moveTo(canvas.width * fraction, 0);
        context.lineTo(canvas.width * fraction, canvas.height);
        context.moveTo(0, canvas.height * fraction);
        context.lineTo(canvas.width, canvas.height * fraction);
        context.stroke();
      }
      context.save();
      context.setLineDash([5, 5]);
      context.strokeStyle = "#79827f";
      context.beginPath();
      context.moveTo(reference.medianX, 0);
      context.lineTo(reference.medianX, canvas.height);
      context.moveTo(0, reference.medianY);
      context.lineTo(canvas.width, reference.medianY);
      context.stroke();
      context.restore();
      const sizeFraction = Math.max(
        0,
        Math.min(1, (area - reference.areaLow) / (reference.areaHigh - reference.areaLow)),
      );
      const radius = 18 + sizeFraction * 36;
      const hue = 182 - sizeFraction * 148;
      context.fillStyle = `hsl(${hue} 68% 45%)`;
      context.strokeStyle = "#202322";
      context.lineWidth = 2;
      context.beginPath();
      context.arc(xValue, yValue, radius, 0, Math.PI * 2);
      context.fill();
      context.stroke();
    } else {
      context.fillStyle = "#5a302c";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = "#fff";
      context.font = "700 22px Myriad Pro, Arial, sans-serif";
      context.textAlign = "center";
      context.fillText("OUT-OF-FRAME FIT", canvas.width / 2, canvas.height / 2 + 7);
    }
    elements.trackingStatus.textContent = blink
      ? "Likely blink"
      : inFrame
        ? "Tracked"
        : "Tracking artifact";
    elements.trackingStatus.style.color = blink || !inFrame ? "#b44235" : "";
    elements.videoBlinkBadge.hidden = !blink;
    elements.xValue.textContent = `${xValue.toFixed(1)} px`;
    elements.yValue.textContent = `${yValue.toFixed(1)} px`;
    elements.areaValue.textContent = area > 0 ? `${area.toFixed(0)} px²` : "-";
    elements.ellipseValue.textContent = `${width.toFixed(1)} × ${height.toFixed(1)} px`;
  }

  function blinkIntervals(samples) {
    const intervals = [];
    let start = null;
    samples.forEach((sample, index) => {
      if (sample[6] && start === null) start = sample[0];
      if (start !== null && (!sample[6] || index === samples.length - 1)) {
        intervals.push([start, sample[0]]);
        start = null;
      }
    });
    return intervals;
  }

  function drawTrace(sample) {
    const session = currentSession();
    const fit = currentFit();
    const samples = fit.samples;
    const canvas = elements.trace;
    const context = canvas.getContext("2d");
    const margins = { bottom: 25, left: 64, right: 18, top: 14 };
    const width = canvas.width - margins.left - margins.right;
    const height = canvas.height - margins.top - margins.bottom;
    const reference = fit.fieldReference;
    const minimum = reference.areaLow * 0.9;
    const maximum = reference.areaHigh * 1.1;
    const x = (time) => margins.left + time / protocol.durationSeconds * width;
    const y = (value) => {
      const bounded = Math.max(minimum, Math.min(maximum, value));
      return margins.top + (maximum - bounded) / (maximum - minimum) * height;
    };
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#d4d9d7";
    blinkIntervals(samples).forEach(([start, end]) => {
      context.fillRect(x(start), margins.top, Math.max(2, x(end) - x(start)), height);
    });
    context.strokeStyle = "#e2e5e3";
    context.lineWidth = 1;
    for (const fraction of [0, 0.5, 1]) {
      const gridY = margins.top + fraction * height;
      context.beginPath();
      context.moveTo(margins.left, gridY);
      context.lineTo(canvas.width - margins.right, gridY);
      context.stroke();
    }
    context.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent");
    context.lineWidth = 2;
    context.beginPath();
    let drawing = false;
    samples.forEach((point) => {
      if (point[6] || point[5] <= 0) {
        drawing = false;
      } else if (!drawing) {
        context.moveTo(x(point[0]), y(point[5]));
        drawing = true;
      } else {
        context.lineTo(x(point[0]), y(point[5]));
      }
    });
    context.stroke();
    context.strokeStyle = "#b44235";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(x(session.event.time), margins.top);
    context.lineTo(x(session.event.time), margins.top + height);
    context.stroke();
    context.strokeStyle = "#202322";
    context.beginPath();
    context.moveTo(x(state.localTime), margins.top);
    context.lineTo(x(state.localTime), margins.top + height);
    context.stroke();
    context.fillStyle = "#707674";
    context.font = "12px IBM Plex Mono, monospace";
    context.textAlign = "right";
    context.fillText(maximum.toFixed(0), margins.left - 7, margins.top + 4);
    context.fillText(minimum.toFixed(0), margins.left - 7, margins.top + height + 4);
    context.textAlign = "center";
    for (const time of [0, 4, 8, 12, 16]) {
      context.fillText(`${time}s`, x(time), canvas.height - 5);
    }
    elements.traceValue.textContent = sample[5] > 0 ? `${sample[5].toFixed(0)} px²` : "-";
  }

  function render() {
    const sample = sampleAt(state.localTime);
    elements.timeline.value = state.localTime;
    elements.playbackTime.textContent = `${formatTime(state.localTime)} / ${formatTime(protocol.durationSeconds)}`;
    drawStimulus(activeStimulus());
    drawField(sample);
    drawTrace(sample);
  }

  elements.video.addEventListener("error", videoFailed);
  elements.video.addEventListener("ended", pause);
  elements.playToggle.addEventListener("click", togglePlay);
  elements.timeline.addEventListener("input", (event) => seek(Number(event.target.value)));
  elements.timeline.addEventListener("change", () => {
    if (state.playing) play();
  });
  elements.viewButtons.forEach((button) => {
    button.addEventListener("click", () => selectView(button.dataset.view));
  });
  elements.timeline.max = protocol.durationSeconds;
  buildModalityTabs();
  buildFitTabs();
  selectSession(0);
})();