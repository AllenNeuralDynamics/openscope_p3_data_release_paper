(() => {
  "use strict";

  const protocol = JSON.parse(document.getElementById("eye-tracking-data").textContent);
  const elements = {
    cleaningBanner: document.getElementById("cleaning-banner"),
    cleaningModeLabel: document.getElementById("cleaning-mode-label"),
    cleaningSummary: document.getElementById("cleaning-summary"),
    cleaningToggle: document.getElementById("cleaning-toggle"),
    interpolatedKey: document.getElementById("interpolated-key"),
    interactiveView: document.getElementById("interactive-view"),
    modalitySelector: document.getElementById("modality-selector"),
    overlay: document.getElementById("eye-overlay"),
    overlayKey: document.getElementById("overlay-key"),
    playIcon: document.getElementById("play-icon"),
    playToggle: document.getElementById("play-toggle"),
    playbackTime: document.getElementById("playback-time"),
    processedBlinkBadge: document.getElementById("processed-blink-badge"),
    processedFilterBadge: document.getElementById("processed-filter-badge"),
    processedVideo: document.getElementById("processed-eye-video"),
    processedVideoStage: document.getElementById("processed-video-stage"),
    sessionTitle: document.getElementById("session-title"),
    sourceLinks: document.getElementById("source-links"),
    staticView: document.getElementById("static-view"),
    streamStatus: document.getElementById("stream-status"),
    timeline: document.getElementById("timeline"),
    trace: document.getElementById("pupil-trace"),
    traceHeading: document.getElementById("trace-heading"),
    traceValue: document.getElementById("trace-value"),
    trackingStatus: document.getElementById("tracking-status"),
    video: document.getElementById("eye-video"),
    videoBlinkBadge: document.getElementById("video-blink-badge"),
    videoStage: document.getElementById("video-stage"),
    videoUnavailable: document.getElementById("video-unavailable"),
    viewer: document.getElementById("eye-tracking-viewer"),
    viewButtons: document.querySelectorAll(".view-button"),
  };
  const state = {
    cleaningEnabled: false,
    enabledFitIds: new Set(["pupil", "corneal_reflection", "ellipse"]),
    localTime: 0,
    pendingScrubVideoTime: null,
    playing: false,
    sessionIndex: 0,
    videoToken: 0,
    view: "interactive",
  };
  const fitOrder = ["pupil", "corneal_reflection", "ellipse"];
  const fitColors = {
    pupil: "#45e6d1",
    corneal_reflection: "#ffd166",
    ellipse: "#ff6b8a",
  };
  const cleaningParameters = { maxIsolatedLength: 4, previousSampleCount: 50, zscoreThreshold: 3 };
  const cleanedSessionCache = new WeakMap();

  function currentSession() {
    return protocol.sessions[state.sessionIndex];
  }

  function fitById(fitId) {
    return currentSession().fits[fitId];
  }

  function unwrapAngles(values, blinks) {
    const unwrapped = values.slice();
    let previous = null;
    unwrapped.forEach((value, index) => {
      if (blinks[index] || !Number.isFinite(value)) {
        previous = null;
        return;
      }
      let adjusted = value;
      if (previous !== null) {
        while (adjusted - previous > Math.PI) adjusted -= 2 * Math.PI;
        while (adjusted - previous < -Math.PI) adjusted += 2 * Math.PI;
      }
      unwrapped[index] = adjusted;
      previous = adjusted;
    });
    return unwrapped;
  }

  function cleanField(values, blinks) {
    const { maxIsolatedLength, previousSampleCount, zscoreThreshold } = cleaningParameters;
    const median = (items) => {
      const ordered = items.slice().sort((first, second) => first - second);
      const middle = Math.floor(ordered.length / 2);
      return ordered.length % 2
        ? ordered[middle]
        : (ordered[middle - 1] + ordered[middle]) / 2;
    };
    const isOutlier = (value, history) => {
      if (!Number.isFinite(value) || history.length < 2) return false;
      const baseline = history.slice(-previousSampleCount);
      const baselineMedian = median(baseline);
      const mad = median(baseline.map((value) => Math.abs(value - baselineMedian)));
      const robustScale = 1.4826 * mad;
      const deviation = Math.abs(value - baselineMedian);
      return robustScale > 0
        ? deviation / robustScale > zscoreThreshold
        : deviation > 0;
    };

    const cleaned = values.slice();
    const replacedIndices = [];
    let history = [];
    let pendingIndices = [];
    const commitRawPending = () => {
      pendingIndices.forEach((index) => history.push(values[index]));
      pendingIndices = [];
    };
    for (let index = 0; index < values.length; index += 1) {
      const value = values[index];
      if (blinks[index] || !Number.isFinite(value)) {
        commitRawPending();
        history = [];
        continue;
      }
      if (isOutlier(value, history)) {
        pendingIndices.push(index);
        if (pendingIndices.length > maxIsolatedLength) commitRawPending();
        continue;
      }
      if (pendingIndices.length) {
        if (history.length) {
          const leftValue = history[history.length - 1];
          const span = pendingIndices.length + 1;
          pendingIndices.forEach((pendingIndex, offset) => {
            const fraction = (offset + 1) / span;
            cleaned[pendingIndex] = leftValue + fraction * (value - leftValue);
            history.push(cleaned[pendingIndex]);
            replacedIndices.push(pendingIndex);
          });
        } else {
          commitRawPending();
        }
        pendingIndices = [];
      }
      history.push(value);
    }
    commitRawPending();
    return { cleaned, replacedIndices };
  }

  function cleanedSession(session) {
    if (cleanedSessionCache.has(session)) return cleanedSessionCache.get(session);
    let replacedSampleCount = 0;
    let replacedValueCount = 0;
    const areaReplacedIndicesByFit = {};
    const fits = Object.fromEntries(fitOrder.map((fitId) => {
      const rawSamples = session.fits[fitId].samples;
      const samples = rawSamples.map((sample) => sample.slice());
      const blinks = rawSamples.map((sample) => Boolean(sample[7]));
      const replacedSampleIndices = new Set();
      const areaReplacedIndices = new Set();
      for (let fieldIndex = 1; fieldIndex <= 6; fieldIndex += 1) {
        let values = rawSamples.map((sample) => Number(sample[fieldIndex]));
        if (fieldIndex === 6) values = unwrapAngles(values, blinks);
        const result = cleanField(values, blinks);
        result.cleaned.forEach((value, index) => { samples[index][fieldIndex] = value; });
        result.replacedIndices.forEach((index) => replacedSampleIndices.add(index));
        if (fieldIndex === 5) {
          result.replacedIndices.forEach((index) => areaReplacedIndices.add(index));
        }
        replacedValueCount += result.replacedIndices.length;
      }
      replacedSampleCount += replacedSampleIndices.size;
      areaReplacedIndicesByFit[fitId] = areaReplacedIndices;
      return [fitId, samples];
    }));
    const result = { areaReplacedIndicesByFit, fits, replacedSampleCount, replacedValueCount };
    cleanedSessionCache.set(session, result);
    return result;
  }

  function fitSamples(fitId) {
    return state.cleaningEnabled
      ? cleanedSession(currentSession()).fits[fitId]
      : fitById(fitId).samples;
  }

  function updateCleaningMode() {
    state.cleaningEnabled = elements.cleaningToggle.checked;
    elements.viewer.classList.toggle("filtered-view", state.cleaningEnabled);
    elements.cleaningBanner.hidden = !state.cleaningEnabled;
    elements.interpolatedKey.hidden = !state.cleaningEnabled;
    elements.processedFilterBadge.hidden = !state.cleaningEnabled;
    elements.cleaningModeLabel.textContent = state.cleaningEnabled ? "FILTERED" : "RAW DATA";
    if (state.cleaningEnabled) {
      const cleaned = cleanedSession(currentSession());
      elements.cleaningSummary.textContent = `${cleaned.replacedSampleCount} samples `
        + `(${cleaned.replacedValueCount} geometry values) interpolated · `
        + `up to 50 previous processed samples · median/MAD · |z| > 3 · `
        + `runs of 1–4 samples only`;
    }
    render();
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

  function sampleAt(time, fitId) {
    const samples = fitSamples(fitId);
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
      button.textContent = session.id.includes("-candidate-")
        ? `${session.label} · ${session.subject}`
        : session.label;
      button.setAttribute("aria-label", `${session.label}, mouse ${session.subject}`);
      button.addEventListener("click", () => selectSession(index));
      elements.modalitySelector.append(button);
    });
  }

  function buildFitControls() {
    fitOrder.forEach((fitId) => {
      const label = document.createElement("label");
      label.className = "fit-control";
      label.style.setProperty("--fit-color", fitColors[fitId]);
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = true;
      checkbox.dataset.fitId = fitId;
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.enabledFitIds.add(fitId);
        else state.enabledFitIds.delete(fitId);
        render();
      });
      const swatch = document.createElement("i");
      swatch.className = "fit-swatch";
      swatch.setAttribute("aria-hidden", "true");
      label.append(checkbox, swatch, document.createTextNode(fitById(fitId).label));
      elements.overlayKey.append(label);
    });
  }

  function configureViewer() {
    const reference = fitById("pupil").fieldReference;
    elements.overlay.width = reference.frameWidth;
    elements.overlay.height = reference.frameHeight;
    elements.videoStage.style.aspectRatio = `${reference.frameWidth} / ${reference.frameHeight}`;
    elements.processedVideoStage.style.aspectRatio = `${reference.frameWidth} / ${reference.frameHeight}`;
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
    elements.modalitySelector.querySelectorAll("button").forEach((button, buttonIndex) => {
      const active = buttonIndex === index;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    elements.sessionTitle.textContent = `Mouse ${session.subject} · ${session.session}`;
    configureViewer();
    renderSourceLinks();
    loadVideo();
    updateCleaningMode();
  }

  function loadVideo(resume = false) {
    const token = ++state.videoToken;
    elements.streamStatus.textContent = "Loading S3 stream";
    elements.videoUnavailable.hidden = true;
    elements.video.src = currentSession().camera.url;
    elements.processedVideo.src = currentSession().camera.url;
    elements.video.load();
    elements.processedVideo.load();
    const seekVideo = () => {
      if (token !== state.videoToken) return;
      const videoTime = videoTimeAt(state.localTime);
      elements.video.currentTime = videoTime;
      elements.processedVideo.currentTime = videoTime;
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
    const videoTime = videoTimeAt(state.localTime);
    if (!state.playing && elements.video.readyState >= 1 && elements.processedVideo.readyState >= 1) {
      state.pendingScrubVideoTime = videoTime;
      elements.video.currentTime = videoTime;
      elements.processedVideo.currentTime = videoTime;
      return;
    }
    if (elements.video.readyState >= 1) elements.video.currentTime = videoTime;
    if (elements.processedVideo.readyState >= 1) elements.processedVideo.currentTime = videoTime;
    render();
  }

  function renderCompletedScrub() {
    if (state.playing || state.pendingScrubVideoTime === null) return;
    const target = state.pendingScrubVideoTime;
    const tolerance = 0.04;
    if (
      elements.video.seeking
      || elements.processedVideo.seeking
      || Math.abs(elements.video.currentTime - target) > tolerance
      || Math.abs(elements.processedVideo.currentTime - target) > tolerance
    ) return;
    state.pendingScrubVideoTime = null;
    state.localTime = localTimeAt(
      (elements.video.currentTime + elements.processedVideo.currentTime) / 2,
    );
    render();
  }

  async function play() {
    if (state.localTime >= protocol.durationSeconds - 0.02) seek(0);
    state.playing = true;
    state.pendingScrubVideoTime = null;
    updatePlayState();
    try {
      await elements.video.play();
      await elements.processedVideo.play();
    } catch {
      state.playing = false;
      updatePlayState();
    }
    requestAnimationFrame(tick);
  }

  function pause() {
    state.playing = false;
    elements.video.pause();
    elements.processedVideo.pause();
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
    if (elements.video.readyState >= 2) {
      state.localTime = localTimeAt(elements.video.currentTime);
      if (
        elements.processedVideo.readyState >= 2
        && Math.abs(elements.processedVideo.currentTime - elements.video.currentTime) > 0.05
      ) elements.processedVideo.currentTime = elements.video.currentTime;
    }
    else state.localTime += 1 / 60;
    if (state.localTime >= protocol.durationSeconds) {
      seek(protocol.durationSeconds);
      pause();
      return;
    }
    render();
    requestAnimationFrame(tick);
  }

  function drawOverlay(samplesByFit) {
    const context = elements.overlay.getContext("2d");
    context.clearRect(0, 0, elements.overlay.width, elements.overlay.height);
    let visibleFits = 0;
    let blink = false;
    fitOrder.forEach((fitId) => {
      const sample = samplesByFit[fitId];
      const [, xValue, yValue, width, height, , angle, sampleBlink] = sample;
      blink ||= sampleBlink;
      const reference = fitById(fitId).fieldReference;
      const inFrame = xValue >= 0
        && xValue < reference.frameWidth
        && yValue >= 0
        && yValue < reference.frameHeight;
      if (!state.enabledFitIds.has(fitId) || sampleBlink || !inFrame || width <= 0 || height <= 0) {
        return;
      }
      visibleFits += 1;
      context.save();
      context.strokeStyle = fitColors[fitId];
      context.fillStyle = fitColors[fitId];
      context.lineWidth = 3;
      context.shadowColor = "rgba(0, 0, 0, 0.75)";
      context.shadowBlur = 3;
      context.beginPath();
      context.ellipse(xValue, yValue, width, height, angle, 0, Math.PI * 2);
      context.stroke();
      context.shadowBlur = 0;
      context.beginPath();
      context.arc(xValue, yValue, 4, 0, Math.PI * 2);
      context.fill();
      const widthMarkerRadius = Math.max(8, Math.min(24, width * 0.35));
      const heightMarkerRadius = Math.max(6, Math.min(18, height * 0.35));
      const widthX = Math.cos(angle) * widthMarkerRadius;
      const widthY = Math.sin(angle) * widthMarkerRadius;
      const heightX = -Math.sin(angle) * heightMarkerRadius;
      const heightY = Math.cos(angle) * heightMarkerRadius;
      context.beginPath();
      context.moveTo(xValue - widthX, yValue - widthY);
      context.lineTo(xValue + widthX, yValue + widthY);
      context.moveTo(xValue - heightX, yValue - heightY);
      context.lineTo(xValue + heightX, yValue + heightY);
      context.stroke();
      context.restore();
    });
    elements.trackingStatus.textContent = blink
      ? "Likely blink"
      : `${visibleFits} fit${visibleFits === 1 ? "" : "s"} shown`;
    elements.trackingStatus.style.color = blink ? "#ff8b7e" : "";
    elements.videoBlinkBadge.hidden = !blink;
    elements.processedBlinkBadge.hidden = !blink;
  }

  function blinkIntervals(samples) {
    const intervals = [];
    let start = null;
    samples.forEach((sample, index) => {
      if (sample[7] && start === null) start = sample[0];
      if (start !== null && (!sample[7] || index === samples.length - 1)) {
        intervals.push([start, sample[0]]);
        start = null;
      }
    });
    return intervals;
  }

  function drawTrace(samplesByFit) {
    const canvas = elements.trace;
    const context = canvas.getContext("2d");
    const displayedFits = fitOrder;
    const layout = { bottom: 28, gap: 14, laneHeight: 104, left: 130, right: 18, top: 12 };
    canvas.height = layout.top + displayedFits.length * layout.laneHeight
      + (displayedFits.length - 1) * layout.gap + layout.bottom;
    const plotWidth = canvas.width - layout.left - layout.right;
    const x = (time) => layout.left + time / protocol.durationSeconds * plotWidth;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    displayedFits.forEach((fitId, laneIndex) => {
      const laneTop = layout.top + laneIndex * (layout.laneHeight + layout.gap);
      const reference = fitById(fitId).fieldReference;
      const minimum = reference.areaLow * 0.9;
      const maximum = reference.areaHigh * 1.1;
      const y = (value) => {
        const bounded = Math.max(minimum, Math.min(maximum, value));
        return laneTop + (maximum - bounded) / (maximum - minimum) * layout.laneHeight;
      };
      context.fillStyle = "#fafbfb";
      context.fillRect(layout.left, laneTop, plotWidth, layout.laneHeight);
      context.fillStyle = "#d4d9d7";
      blinkIntervals(fitSamples(fitId)).forEach(([start, end]) => {
        context.fillRect(x(start), laneTop, Math.max(2, x(end) - x(start)), layout.laneHeight);
      });
      context.strokeStyle = "#e2e5e3";
      context.lineWidth = 1;
      for (const fraction of [0, 0.5, 1]) {
        const gridY = laneTop + fraction * layout.laneHeight;
        context.beginPath();
        context.moveTo(layout.left, gridY);
        context.lineTo(canvas.width - layout.right, gridY);
        context.stroke();
      }
      context.strokeStyle = fitColors[fitId];
      context.lineWidth = 2.5;
      context.beginPath();
      let drawing = false;
      fitSamples(fitId).forEach((point) => {
        if (point[7] || point[5] <= 0) {
          drawing = false;
        } else if (!drawing) {
          context.moveTo(x(point[0]), y(point[5]));
          drawing = true;
        } else {
          context.lineTo(x(point[0]), y(point[5]));
        }
      });
      context.stroke();
      if (state.cleaningEnabled) {
        context.fillStyle = "#b24a00";
        cleanedSession(currentSession()).areaReplacedIndicesByFit[fitId].forEach((index) => {
          const point = fitSamples(fitId)[index];
          if (point[7] || point[5] <= 0) return;
          context.beginPath();
          context.arc(x(point[0]), y(point[5]), 4, 0, Math.PI * 2);
          context.fill();
        });
      }
      context.strokeStyle = "#202322";
      context.beginPath();
      context.moveTo(x(state.localTime), laneTop);
      context.lineTo(x(state.localTime), laneTop + layout.laneHeight);
      context.stroke();
      context.fillStyle = fitColors[fitId];
      context.font = "700 14px Myriad Pro, Arial, sans-serif";
      context.textAlign = "right";
      const titleWords = `${fitById(fitId).label} area`.split(" ");
      const titleLines = [];
      titleWords.forEach((word) => {
        const lineIndex = titleLines.length - 1;
        const candidate = lineIndex >= 0 ? `${titleLines[lineIndex]} ${word}` : word;
        if (lineIndex >= 0 && context.measureText(candidate).width <= layout.left - 24) {
          titleLines[lineIndex] = candidate;
        } else {
          titleLines.push(word);
        }
      });
      titleLines.forEach((line, lineIndex) => {
        context.fillText(line, layout.left - 12, laneTop + 18 + lineIndex * 16);
      });
      context.fillStyle = "#707674";
      context.font = "12px IBM Plex Mono, monospace";
      context.textAlign = "left";
      context.fillText(maximum.toFixed(0), layout.left + 6, laneTop + 14);
      context.fillText(minimum.toFixed(0), layout.left + 6, laneTop + layout.laneHeight - 5);
    });
    context.fillStyle = "#707674";
    context.font = "12px IBM Plex Mono, monospace";
    context.textAlign = "center";
    for (const time of [0, 4, 8, 12, 16]) {
      context.fillText(`${time}s`, x(time), canvas.height - 7);
    }
    elements.traceValue.textContent = displayedFits
      .map((fitId) => `${fitById(fitId).label}: ${samplesByFit[fitId][5].toFixed(0)}`)
      .join(" · ");
  }

  function render() {
    const samplesByFit = Object.fromEntries(
      fitOrder.map((fitId) => [fitId, sampleAt(state.localTime, fitId)]),
    );
    elements.timeline.value = state.localTime;
    elements.playbackTime.textContent = `${formatTime(state.localTime)} / ${formatTime(protocol.durationSeconds)}`;
    drawOverlay(samplesByFit);
    drawTrace(samplesByFit);
  }

  elements.video.addEventListener("error", videoFailed);
  elements.video.addEventListener("ended", pause);
  elements.video.addEventListener("seeked", renderCompletedScrub);
  elements.processedVideo.addEventListener("seeked", renderCompletedScrub);
  elements.cleaningToggle.addEventListener("change", updateCleaningMode);
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
  buildFitControls();
  selectSession(0);
})();