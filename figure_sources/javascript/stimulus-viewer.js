(() => {
  "use strict";

  const protocol = JSON.parse(document.getElementById("simulator-data").textContent);
  const canvas = document.getElementById("stimulus-canvas");
  const context = canvas.getContext("2d", { alpha: false });
  const playbackDuration = protocol.playback_duration_seconds;
  const elements = {
    blockTrack: document.getElementById("block-track"),
    contextSelector: document.getElementById("context-selector"),
    mismatchBadge: document.getElementById("mismatch-badge"),
    monitorFrame: document.getElementById("screen-toggle"),
    playIcon: document.getElementById("play-icon"),
    playToggle: document.getElementById("play-toggle"),
    playbackTime: document.getElementById("playback-time"),
    playbackView: document.getElementById("playback-view"),
    sessionSelector: document.getElementById("session-selector"),
    sessionTitle: document.getElementById("session-title"),
    stimulusVideo: document.getElementById("stimulus-video"),
    staticPanel: document.getElementById("static-panel"),
    trialLabel: document.getElementById("trial-label"),
    viewButtons: document.querySelectorAll(".view-button"),
  };

  const sessionLabels = ["Standard oddball", "Sensorimotor", "Sequence", "Duration"];
  const blockLabels = ["C1", "Context", "C1", "C2", "C3", "C4", "Movie", "RF"];
  const blockColors = ["#ffffff", "#202322", "#ffffff", "#eeeeee", "#d7d9d8", "#bfc3c1", "#8d9390", "#f5f5f5"];
  const state = {
    blockIndex: 1,
    elapsed: 0,
    lastFrameTime: performance.now(),
    movieReady: false,
    playing: false,
    sessionIndex: 0,
    view: "playback",
  };

  let angularCoordinates;
  let gratingImage;

  function currentSession() {
    return protocol.sessions[state.sessionIndex];
  }

  function currentBlock() {
    return protocol.blocks[state.blockIndex];
  }

  function selectView(view) {
    state.view = view;
    elements.playbackView.hidden = view !== "playback";
    elements.staticPanel.hidden = view !== "static";
    if (view === "static") setPlaying(false);
    elements.viewButtons.forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function formatTime(seconds) {
    const bounded = Math.max(0, Math.min(seconds, playbackDuration));
    const minutes = Math.floor(bounded / 60);
    const remainingSeconds = Math.floor(bounded % 60);
    return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
  }

  function contrastTextColor(hexColor) {
    const channels = hexColor.slice(1).match(/.{2}/g).map((value) => {
      const channel = Number.parseInt(value, 16) / 255;
      return channel <= 0.04045
        ? channel / 12.92
        : ((channel + 0.055) / 1.055) ** 2.4;
    });
    const luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    return luminance > 0.179 ? "#0a0a0a" : "#ffffff";
  }

  function buildSessionTabs() {
    protocol.sessions.forEach((session, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "session-tab";
      button.style.setProperty("--tab-color", session.color);
      button.style.setProperty("--tab-text-color", contrastTextColor(session.color));
      button.textContent = sessionLabels[index];
      button.setAttribute("aria-label", `${session.name}: ${session.mismatch}`);
      button.addEventListener("click", () => selectSession(index));
      elements.sessionSelector.append(button);
    });
  }

  function buildBlockTrack() {
    const totalMinutes = protocol.blocks.reduce((total, block) => total + block.duration_minutes, 0);
    const contextIndex = protocol.blocks.findIndex((block) => block.category === "context");
    const contextStart = protocol.blocks
      .slice(0, contextIndex)
      .reduce((total, block) => total + block.duration_minutes, 0) / totalMinutes * 100;
    const contextWidth = protocol.blocks[contextIndex].duration_minutes / totalMinutes * 100;
    elements.contextSelector.style.setProperty("--context-start", `${contextStart}%`);
    elements.contextSelector.style.setProperty("--context-width", `${contextWidth}%`);
    elements.contextSelector.style.setProperty(
      "--context-center",
      `${contextStart + contextWidth / 2}%`,
    );
    protocol.blocks.forEach((block, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `block-tab${block.category === "context" ? " context" : ""}`;
      button.style.flexBasis = `${(block.duration_minutes / totalMinutes) * 100}%`;
      button.style.setProperty("--block-color", blockColors[index]);
      button.textContent = blockLabels[index];
      button.title = `${block.name}: ${block.duration_minutes.toFixed(1)} min`;
      button.setAttribute("aria-label", button.title);
      button.addEventListener("click", () => selectBlock(index));
      elements.blockTrack.append(button);
    });
  }

  function selectSession(index) {
    state.sessionIndex = index;
    state.blockIndex = 1;
    state.elapsed = 0;
    const session = currentSession();
    document.documentElement.style.setProperty("--accent", session.color);
    elements.sessionTitle.textContent = "Context block";
    const contextButton = elements.blockTrack.querySelectorAll("button")[1];
    contextButton.textContent = "Context";
    contextButton.title = `${session.name} context: ${currentBlock().duration_minutes.toFixed(1)} min`;
    contextButton.setAttribute("aria-label", contextButton.title);
    elements.sessionSelector.querySelectorAll("button").forEach((button, buttonIndex) => {
      const active = buttonIndex === index;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    updateBlockState();
  }

  function selectBlock(index) {
    state.blockIndex = index;
    state.elapsed = 0;
    updateBlockState();
  }

  function updateBlockState() {
    const session = currentSession();
    elements.sessionTitle.textContent = state.blockIndex === 1
      ? "Context block"
      : currentBlock().name;
    elements.blockTrack.querySelectorAll("button").forEach((button, index) => {
      const active = index === state.blockIndex;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    updateMediaState();
    drawFrame();
    updatePlaybackUi();
  }

  function setPlaying(playing) {
    state.playing = playing;
    elements.playIcon.textContent = playing ? "II" : String.fromCharCode(9654);
    elements.playToggle.classList.toggle("playing", playing);
    elements.playToggle.setAttribute("aria-label", playing ? "Pause stimulus" : "Play stimulus");
    elements.playToggle.title = playing ? "Pause stimulus" : "Play stimulus";
    if (currentBlock().name === "Natural movie" && state.movieReady) {
      if (playing) {
        elements.stimulusVideo.play().catch(() => undefined);
      } else {
        elements.stimulusVideo.pause();
      }
    }
  }

  function togglePlayback() {
    if (!state.playing && state.elapsed >= playbackDuration) {
      state.elapsed = 0;
    }
    setPlaying(!state.playing);
  }

  function initializeAngularCoordinates() {
    const pixelCount = canvas.width * canvas.height;
    const azimuth = new Float32Array(pixelCount);
    const altitude = new Float32Array(pixelCount);
    let index = 0;
    for (let y = 0; y < canvas.height; y += 1) {
      const normalizedY = 1 - ((y + 0.5) / canvas.height) * 2;
      const altitudeDegrees = normalizedY * 95 / 2;
      for (let x = 0; x < canvas.width; x += 1) {
        const normalizedX = ((x + 0.5) / canvas.width) * 2 - 1;
        azimuth[index] = normalizedX * 120 / 2;
        altitude[index] = altitudeDegrees;
        index += 1;
      }
    }
    angularCoordinates = { altitude, azimuth };
    gratingImage = context.createImageData(canvas.width, canvas.height);
  }

  function representativeWheelPhase(seconds) {
    return seconds * 1.25 + 0.2 * Math.sin(seconds * 0.8) + 0.07 * Math.sin(seconds * 2.7);
  }

  function sourceTableSpec() {
    const contextSelected = state.blockIndex === 1;
    const excerpt = contextSelected
      ? protocol.stimulusTableExcerpts[String(currentSession().number)]
      : protocol.sharedTableExcerpts[String(state.blockIndex)];
    const excerptTime = state.elapsed % excerpt.durationSeconds;
    let low = 0;
    let high = excerpt.rows.length - 1;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if (excerpt.rows[middle].end <= excerptTime) low = middle + 1;
      else high = middle;
    }
    const row = excerpt.rows[low];
    const withinRow = excerptTime - row.start;
    const visible = withinRow < row.duration;
    let phaseCycles = row.phaseCycles ?? 0;
    if (row.phase === "wheel" && row.temporalFrequency === 0) {
      phaseCycles = representativeWheelPhase(state.elapsed);
    } else if (row.trialType === "prerecorded") {
      const nextRow = excerpt.rows[Math.min(low + 1, excerpt.rows.length - 1)];
      const fraction = row.duration > 0
        ? Math.min(1, withinRow / row.duration)
        : 0;
      phaseCycles += ((nextRow.phaseCycles ?? phaseCycles) - phaseCycles) * fraction;
    } else {
      phaseCycles -= withinRow * row.temporalFrequency;
    }
    const trialType = row.trialType.replaceAll("_", " ");
    const patch = row.diameterX > 0 && row.diameterX < 360
      ? {
          altitude: row.y,
          azimuth: row.x,
          radius: Math.min(row.diameterX, row.diameterY) / 2,
        }
      : undefined;
    const label = row.trialType === "prerecorded"
      ? `Open-loop playback · source T${excerpt.sourceTrialStart}–${excerpt.sourceTrialEnd}`
      : `T${row.trialNumber} · ${trialType} · ${contextSelected ? "shuffled " : ""}source`;
    return {
      contrast: visible ? row.contrast : 0,
      label,
      mismatch: row.isMismatch,
      orientation: row.orientation,
      patch,
      phaseCycles,
      sourceRow: row.sourceRow,
      spatialFrequency: row.spatialFrequency,
    };
  }

  function stimulusSpec() {
    if (currentBlock().name === "Natural movie") return undefined;
    return sourceTableSpec();
  }

  function angularDistanceDegrees(azimuthA, altitudeA, azimuthB, altitudeB) {
    const radians = Math.PI / 180;
    const sinHalfAltitude = Math.sin((altitudeA - altitudeB) * radians / 2);
    const sinHalfAzimuth = Math.sin((azimuthA - azimuthB) * radians / 2);
    const haversine = sinHalfAltitude ** 2
      + Math.cos(altitudeA * radians) * Math.cos(altitudeB * radians)
      * sinHalfAzimuth ** 2;
    return 2 * Math.asin(Math.min(1, Math.sqrt(haversine))) / radians;
  }

  function drawSphericalGrating(spec) {
    if (!angularCoordinates) {
      initializeAngularCoordinates();
    }
    const orientationRadians = spec.orientation * Math.PI / 180;
    const orientationX = Math.cos(orientationRadians);
    const orientationY = Math.sin(orientationRadians);
    const pixels = gratingImage.data;
    for (let index = 0; index < angularCoordinates.azimuth.length; index += 1) {
      const azimuth = angularCoordinates.azimuth[index];
      const altitude = angularCoordinates.altitude[index];
      const insidePatch = !spec.patch || angularDistanceDegrees(
        azimuth,
        altitude,
        spec.patch.azimuth,
        spec.patch.altitude,
      ) <= spec.patch.radius;
      let luminance = 0.5;
      if (insidePatch && spec.contrast > 0) {
        const gratingCoordinate = azimuth * orientationX + altitude * orientationY;
        const sineValue = Math.sin(2 * Math.PI * (
          gratingCoordinate * spec.spatialFrequency + spec.phaseCycles
        ));
        luminance = 0.5 + sineValue * spec.contrast * 0.5;
      }
      const channel = Math.round(Math.max(0, Math.min(1, luminance)) * 255);
      const pixelIndex = index * 4;
      pixels[pixelIndex] = channel;
      pixels[pixelIndex + 1] = channel;
      pixels[pixelIndex + 2] = channel;
      pixels[pixelIndex + 3] = 255;
    }
    context.putImageData(gratingImage, 0, 0);
  }

  function updateMediaState() {
    const movieSelected = currentBlock().name === "Natural movie";
    if (movieSelected && !elements.stimulusVideo.src) {
      elements.stimulusVideo.src = protocol.sources.zebra_movie_asset;
      elements.stimulusVideo.load();
    }
    elements.stimulusVideo.hidden = !movieSelected;
    canvas.hidden = movieSelected;
    if (!movieSelected) {
      elements.stimulusVideo.pause();
    } else if (state.playing && state.movieReady) {
      elements.stimulusVideo.play().catch(() => undefined);
    }
  }

  function drawFrame() {
    if (currentBlock().name === "Natural movie") {
      elements.trialLabel.textContent = "Canonical zebra-noise movie · real source excerpt";
      elements.mismatchBadge.hidden = true;
    } else {
      const spec = stimulusSpec();
      drawSphericalGrating(spec);
      elements.trialLabel.textContent = spec.label;
      elements.mismatchBadge.hidden = !spec.mismatch;
    }
  }

  function updatePlaybackUi() {
    elements.playbackTime.textContent = `${formatTime(state.elapsed)} / ${formatTime(playbackDuration)}`;
  }

  function attachInteractions() {
    elements.viewButtons.forEach((button) => {
      button.addEventListener("click", () => selectView(button.dataset.view));
    });
    elements.playToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      togglePlayback();
    });
    elements.monitorFrame.addEventListener("click", togglePlayback);
    elements.stimulusVideo.addEventListener("canplay", () => {
      state.movieReady = true;
      updateMediaState();
    });
    elements.stimulusVideo.addEventListener("error", () => {
      state.movieReady = false;
    });
    document.addEventListener("keydown", (event) => {
      if (event.code === "Space" && state.view === "playback") {
        event.preventDefault();
        togglePlayback();
      }
    });
  }

  function playbackStep() {
    const timestamp = performance.now();
    const deltaSeconds = Math.min((timestamp - state.lastFrameTime) / 1000, 1);
    state.lastFrameTime = timestamp;
    if (state.playing) {
      state.elapsed += deltaSeconds;
      if (state.elapsed >= playbackDuration) {
        state.elapsed = 0;
        if (state.movieReady) elements.stimulusVideo.currentTime = 0;
      }
      drawFrame();
      updatePlaybackUi();
    }
  }

  buildSessionTabs();
  buildBlockTrack();
  attachInteractions();
  selectSession(0);
  selectView("playback");
  setPlaying(false);
  window.setInterval(playbackStep, 1000 / 30);
})();