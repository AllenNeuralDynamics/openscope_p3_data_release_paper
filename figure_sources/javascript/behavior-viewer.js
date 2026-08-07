(() => {
  "use strict";

  const protocol = JSON.parse(document.getElementById("behavior-data").textContent);
  const elements = {
    cameraLabel: document.getElementById("camera-label"),
    cameraSelector: document.getElementById("camera-selector"),
    contextLabel: document.getElementById("context-label"),
    eventBadge: document.getElementById("event-badge"),
    eventLabel: document.getElementById("event-label"),
    modalitySelector: document.getElementById("modality-selector"),
    interactiveView: document.getElementById("interactive-view"),
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
    traceCanvas: document.getElementById("trace-canvas"),
    traceHeading: document.getElementById("trace-heading"),
    traceUnit: document.getElementById("trace-unit"),
    traceValue: document.getElementById("trace-value"),
    trialNumber: document.getElementById("trial-number"),
    trialType: document.getElementById("trial-type"),
    video: document.getElementById("behavior-video"),
    videoUnavailable: document.getElementById("video-unavailable"),
    viewButtons: document.querySelectorAll(".view-button"),
  };
  const state = {
    cameraIndex: 0,
    localTime: 0,
    playing: false,
    sessionIndex: 0,
    view: "interactive",
    videoToken: 0,
  };
  const contextColors = {
    "Sensorimotor mismatch": "#283185",
    "Standard oddball": "#22bcad",
    "Sequence mismatch": "#b16027",
    "Duration mismatch": "#ccaf2d",
  };

  function currentSession() {
    return protocol.sessions[state.sessionIndex];
  }

  function currentCamera() {
    return currentSession().cameras[state.cameraIndex];
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

  function videoTimeAt(localTime, camera = currentCamera()) {
    const mapping = camera.timeMap;
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
    const fraction = second[0] === first[0]
      ? 0
      : (localTime - first[0]) / (second[0] - first[0]);
    return first[1] + (second[1] - first[1]) * fraction;
  }

  function localTimeAt(videoTime, camera = currentCamera()) {
    const mapping = camera.timeMap;
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
    const fraction = second[1] === first[1]
      ? 0
      : (videoTime - first[1]) / (second[1] - first[1]);
    return first[0] + (second[0] - first[0]) * fraction;
  }

  function formatTime(seconds) {
    const bounded = Math.max(0, Math.min(protocol.durationSeconds, seconds));
    const whole = Math.floor(bounded);
    const tenths = Math.floor((bounded - whole) * 10);
    return `00:${String(whole).padStart(2, "0")}.${tenths}`;
  }

  function buildModalityTabs() {
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

  function buildCameraTabs() {
    elements.cameraSelector.replaceChildren();
    currentSession().cameras.forEach((camera, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "camera-tab";
      button.textContent = camera.label;
      button.setAttribute("aria-label", `${camera.label} camera`);
      button.addEventListener("click", () => selectCamera(index));
      elements.cameraSelector.append(button);
    });
    updateCameraTabs();
  }

  function updateCameraTabs() {
    elements.cameraSelector.querySelectorAll("button").forEach((button, index) => {
      const active = index === state.cameraIndex;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
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
    state.cameraIndex = 0;
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
    elements.traceHeading.textContent = session.traceLabel;
    elements.traceUnit.textContent = session.traceUnit;
    elements.eventLabel.textContent = `${session.event.label} · ${formatTime(session.event.time)}`;
    renderSourceLinks();
    buildCameraTabs();
    loadCamera();
    render();
  }

  function selectCamera(index) {
    const wasPlaying = state.playing;
    elements.video.pause();
    state.cameraIndex = index;
    updateCameraTabs();
    loadCamera(wasPlaying);
  }

  function loadCamera(resume = false) {
    const camera = currentCamera();
    const token = ++state.videoToken;
    elements.cameraLabel.textContent = `${camera.label} camera · public S3`;
    elements.streamStatus.textContent = "Loading S3 stream";
    elements.videoUnavailable.hidden = true;
    elements.video.src = camera.url;
    elements.video.load();

    const seek = () => {
      if (token !== state.videoToken) return;
      elements.video.currentTime = videoTimeAt(state.localTime, camera);
    };
    const ready = () => {
      if (token !== state.videoToken) return;
      elements.streamStatus.textContent = "S3 stream ready";
      elements.videoUnavailable.hidden = true;
      if (resume) play();
    };
    elements.video.addEventListener("loadedmetadata", seek, { once: true });
    elements.video.addEventListener("seeked", ready, { once: true });
  }

  function videoFailed() {
    elements.streamStatus.textContent = "S3 stream unavailable";
    elements.videoUnavailable.hidden = false;
    pause();
  }

  function seek(localTime) {
    state.localTime = Math.max(0, Math.min(protocol.durationSeconds, localTime));
    if (elements.video.readyState >= 1) {
      elements.video.currentTime = videoTimeAt(state.localTime);
    }
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
    elements.playToggle.setAttribute(
      "aria-label",
      state.playing ? "Pause synchronized excerpt" : "Play synchronized excerpt",
    );
    elements.playToggle.title = state.playing ? "Pause" : "Play";
  }

  function tick() {
    if (!state.playing) return;
    if (elements.video.readyState >= 2) {
      state.localTime = localTimeAt(elements.video.currentTime);
    } else {
      state.localTime += 1 / 60;
    }
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
      elements.eventBadge.hidden = true;
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

    const trialType = row.trialType.replaceAll("_", " ");
    const mismatch = row.trialType !== "standard";
    elements.trialType.textContent = trialType;
    elements.trialNumber.textContent = row.trialNumber;
    elements.orientationValue.textContent = `${row.orientationDegrees.toFixed(0)} deg`;
    elements.spatialFrequency.textContent = `${row.spatialFrequency.toFixed(2)} cyc/deg`;
    elements.temporalFrequency.textContent = `${row.temporalFrequency.toFixed(1)} Hz`;
    elements.eventBadge.textContent = mismatch ? "Mismatch" : "Standard";
    elements.eventBadge.hidden = !mismatch;
  }

  function interpolatedTraceValue(trace, time) {
    const index = Math.min(trace.length - 2, Math.max(0, Math.floor(time * 20)));
    const first = trace[index];
    const second = trace[index + 1];
    const fraction = second[0] === first[0] ? 0 : (time - first[0]) / (second[0] - first[0]);
    return first[1] + (second[1] - first[1]) * Math.max(0, Math.min(1, fraction));
  }

  function drawTrace() {
    const session = currentSession();
    const trace = session.trace;
    const canvas = elements.traceCanvas;
    const context = canvas.getContext("2d");
    const margins = { bottom: 24, left: 58, right: 18, top: 16 };
    const width = canvas.width - margins.left - margins.right;
    const height = canvas.height - margins.top - margins.bottom;
    const values = trace.map((point) => point[1]);
    const maximum = Math.max(1, ...values.map((value) => Math.abs(value))) * 1.08;
    const x = (time) => margins.left + time / protocol.durationSeconds * width;
    const y = (value) => margins.top + (maximum - value) / (2 * maximum) * height;

    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
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
    trace.forEach((point, index) => {
      if (index === 0) context.moveTo(x(point[0]), y(point[1]));
      else context.lineTo(x(point[0]), y(point[1]));
    });
    context.stroke();

    context.strokeStyle = "#b44235";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(x(session.event.time), margins.top);
    context.lineTo(x(session.event.time), margins.top + height);
    context.stroke();

    context.strokeStyle = "#202322";
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(x(state.localTime), margins.top);
    context.lineTo(x(state.localTime), margins.top + height);
    context.stroke();

    context.fillStyle = "#707674";
    context.font = "12px IBM Plex Mono, monospace";
    context.textAlign = "right";
    context.fillText(maximum.toFixed(0), margins.left - 7, margins.top + 4);
    context.fillText("0", margins.left - 7, y(0) + 4);
    context.fillText((-maximum).toFixed(0), margins.left - 7, margins.top + height + 4);
    context.textAlign = "center";
    for (const time of [0, 4, 8, 12, 16]) {
      context.fillText(`${time}s`, x(time), canvas.height - 5);
    }

    const value = interpolatedTraceValue(trace, state.localTime);
    elements.traceValue.textContent = `${value.toFixed(1)} ${session.traceUnit}`;
  }

  function render() {
    elements.timeline.value = state.localTime;
    elements.playbackTime.textContent = `${formatTime(state.localTime)} / ${formatTime(protocol.durationSeconds)}`;
    drawStimulus(activeStimulus());
    drawTrace();
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
  selectView("interactive");
  selectSession(0);
})();