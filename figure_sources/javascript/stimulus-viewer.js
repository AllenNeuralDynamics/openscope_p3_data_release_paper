(() => {
  "use strict";

  const protocol = JSON.parse(document.getElementById("simulator-data").textContent);
  const canvas = document.getElementById("stimulus-canvas");
  const context = canvas.getContext("2d", { alpha: false });
  const playbackDuration = protocol.playback_duration_seconds;
  const elements = {
    blockTrack: document.getElementById("block-track"),
    ecephysSource: document.getElementById("ecephys-source"),
    generatorSource: document.getElementById("generator-source"),
    mesoscopeSource: document.getElementById("mesoscope-source"),
    mismatchBadge: document.getElementById("mismatch-badge"),
    monitorFrame: document.getElementById("screen-toggle"),
    playIcon: document.getElementById("play-icon"),
    playToggle: document.getElementById("play-toggle"),
    playbackTime: document.getElementById("playback-time"),
    sessionSelector: document.getElementById("session-selector"),
    sessionTitle: document.getElementById("session-title"),
    stimulusVideo: document.getElementById("stimulus-video"),
    syncSquare: document.getElementById("sync-square"),
    tableSource: document.getElementById("table-source"),
    trialLabel: document.getElementById("trial-label"),
    workflowSource: document.getElementById("workflow-source"),
  };

  const sessionLabels = ["Oddball", "Sensorimotor", "Sequence", "Duration"];
  const blockLabels = ["C1", "Context", "C1", "C2", "C3", "C4", "Movie", "RF"];
  const blockColors = ["#dceaf3", "#dceee9", "#dceaf3", "#ececec", "#f5e6d9", "#e4e3f5", "#e7eadf", "#f2f2c8"];
  const state = {
    blockIndex: 1,
    elapsed: 0,
    lastFrameTime: performance.now(),
    movieReady: false,
    playing: false,
    sessionIndex: 0,
  };

  let angularCoordinates;
  let gratingImage;

  function currentSession() {
    return protocol.sessions[state.sessionIndex];
  }

  function currentBlock() {
    return protocol.blocks[state.blockIndex];
  }

  function formatTime(seconds) {
    const bounded = Math.max(0, Math.min(seconds, playbackDuration));
    const minutes = Math.floor(bounded / 60);
    const remainingSeconds = Math.floor(bounded % 60);
    return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
  }

  function buildSessionTabs() {
    protocol.sessions.forEach((session, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "session-tab";
      button.style.setProperty("--tab-color", session.color);
      button.textContent = sessionLabels[index];
      button.setAttribute("aria-label", `${session.name}: ${session.mismatch}`);
      button.addEventListener("click", () => selectSession(index));
      elements.sessionSelector.append(button);
    });
  }

  function buildBlockTrack() {
    const totalMinutes = protocol.blocks.reduce((total, block) => total + block.duration_minutes, 0);
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
    elements.sessionTitle.textContent = session.name;
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
      ? session.name
      : currentBlock().name;
    elements.blockTrack.querySelectorAll("button").forEach((button, index) => {
      const active = index === state.blockIndex;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    updateSourceLinks();
    updateMediaState();
    drawFrame();
    updatePlaybackUi();
  }

  function updateSourceLinks() {
    const sessionSource = protocol.sources.sessions.find((source) => source.number === currentSession().number);
    const movieSelected = currentBlock().name === "Natural movie";
    elements.tableSource.href = movieSelected
      ? protocol.sources.zebra_movie_url
      : sessionSource.example_table_url;
    elements.tableSource.textContent = movieSelected ? "movie" : "example table";
    elements.generatorSource.href = protocol.sources.generator_url;
    elements.workflowSource.href = protocol.sources.workflow_url;
    elements.ecephysSource.href = protocol.sources.recorded_tables.ecephys;
    elements.mesoscopeSource.href = protocol.sources.recorded_tables.mesoscope;
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
    const horizontalScale = Math.tan((120 / 2) * Math.PI / 180);
    const verticalScale = Math.tan((95 / 2) * Math.PI / 180);
    let index = 0;
    for (let y = 0; y < canvas.height; y += 1) {
      const normalizedY = 1 - ((y + 0.5) / canvas.height) * 2;
      const altitudeDegrees = Math.atan(normalizedY * verticalScale) * 180 / Math.PI;
      for (let x = 0; x < canvas.width; x += 1) {
        const normalizedX = ((x + 0.5) / canvas.width) * 2 - 1;
        azimuth[index] = Math.atan(normalizedX * horizontalScale) * 180 / Math.PI;
        altitude[index] = altitudeDegrees;
        index += 1;
      }
    }
    angularCoordinates = { altitude, azimuth };
    gratingImage = context.createImageData(canvas.width, canvas.height);
  }

  function oddballSpec() {
    const trialDuration = 0.686;
    const trialIndex = Math.floor(state.elapsed / trialDuration);
    const withinTrial = state.elapsed % trialDuration;
    const mismatch = trialIndex > 0 && trialIndex % 16 === 0;
    const variants = [
      { kind: "orientation", label: "45 deg orientation deviant", orientation: 45 },
      { kind: "orientation", label: "90 deg orientation deviant", orientation: 90 },
      { kind: "halt", label: "Motion halt" },
      { kind: "omission", label: "Stimulus omission" },
    ];
    const variant = variants[Math.floor(trialIndex / 16 - 1) % variants.length];
    const visible = withinTrial < 0.343;
    const spec = {
      contrast: visible ? 1 : 0,
      label: "Frequent standard 0 deg",
      mismatch,
      orientation: 0,
      phaseCycles: -state.elapsed * 2,
      spatialFrequency: 0.04,
    };
    if (mismatch && visible) {
      spec.label = variant.label;
      if (variant.kind === "orientation") {
        spec.orientation = variant.orientation;
      } else if (variant.kind === "halt") {
        spec.phaseCycles = -trialIndex * trialDuration * 2;
      } else {
        spec.contrast = 0;
      }
    }
    return spec;
  }

  function representativeWheelPhase(seconds) {
    return seconds * 1.25 + 0.2 * Math.sin(seconds * 0.8) + 0.07 * Math.sin(seconds * 2.7);
  }

  function sensorimotorSpec() {
    const eventInterval = 11;
    const eventNumber = Math.floor(state.elapsed / eventInterval);
    const withinEvent = state.elapsed % eventInterval;
    const mismatch = eventNumber > 0 && withinEvent < 0.343;
    const variants = [
      { kind: "halt", label: "Visuomotor halt" },
      { kind: "omission", label: "Visuomotor omission" },
      { kind: "orientation", label: "45 deg visuomotor deviant", orientation: 45 },
      { kind: "orientation", label: "90 deg visuomotor deviant", orientation: 90 },
    ];
    const variant = variants[Math.max(0, eventNumber - 1) % variants.length];
    const spec = {
      contrast: 1,
      label: "Closed-loop optic flow",
      mismatch,
      orientation: 0,
      phaseCycles: representativeWheelPhase(state.elapsed),
      spatialFrequency: 0.04,
    };
    if (mismatch) {
      spec.label = variant.label;
      if (variant.kind === "halt") {
        spec.phaseCycles = representativeWheelPhase(eventNumber * eventInterval);
      } else if (variant.kind === "omission") {
        spec.contrast = 0;
      } else {
        spec.orientation = variant.orientation;
        spec.phaseCycles = -state.elapsed * 2;
      }
    }
    return spec;
  }

  function sequenceSpec() {
    const elementDuration = 0.25;
    const elementsPerSequence = 5;
    const elementCount = Math.floor(state.elapsed / elementDuration);
    const sequenceNumber = Math.floor(elementCount / elementsPerSequence);
    const elementIndex = elementCount % elementsPerSequence;
    const sequence = [
      { name: "A", orientation: 90, contrast: 1 },
      { name: "B", orientation: 45, contrast: 1 },
      { name: "C", orientation: 0, contrast: 1 },
      { name: "D", orientation: 45, contrast: 1 },
      { name: "Gray", orientation: 0, contrast: 0 },
    ];
    const variants = [
      { label: "C becomes B", orientation: 45, contrast: 1, halt: false },
      { label: "Novel 90 deg element", orientation: 90, contrast: 1, halt: false },
      { label: "Stationary sequence element", orientation: 0, contrast: 1, halt: true },
      { label: "Sequence omission", orientation: 0, contrast: 0, halt: false },
    ];
    const mismatch = sequenceNumber > 0 && sequenceNumber % 9 === 0 && elementIndex === 2;
    const element = sequence[elementIndex];
    const variant = variants[Math.max(0, Math.floor(sequenceNumber / 9) - 1) % variants.length];
    return {
      contrast: mismatch ? variant.contrast : element.contrast,
      label: mismatch ? variant.label : `Sequence ${element.name}`,
      mismatch,
      orientation: mismatch ? variant.orientation : element.orientation,
      phaseCycles: mismatch && variant.halt ? -sequenceNumber * 1.25 * 2 : -state.elapsed * 2,
      spatialFrequency: 0.04,
    };
  }

  function durationSpec() {
    const trials = [0.343, 0.343, 0.343, 0.15, 0.343, 0.343, 0.5, 0.343, 1.0];
    let localTime = state.elapsed;
    let trialIndex = 0;
    while (localTime >= trials[trialIndex % trials.length] + 0.343) {
      localTime -= trials[trialIndex % trials.length] + 0.343;
      trialIndex += 1;
    }
    const duration = trials[trialIndex % trials.length];
    const mismatch = duration !== 0.343;
    return {
      contrast: localTime < duration ? 1 : 0,
      label: mismatch ? `${Math.round(duration * 1000)} ms duration` : "343 ms duration",
      mismatch,
      orientation: 0,
      phaseCycles: -state.elapsed * 2,
      spatialFrequency: 0.04,
    };
  }

  function standardControlSpec() {
    const orientations = [45, 247.5, 90, 135, 22.5, 315, 180, 67.5, 270, 0, 225, 112.5, 292.5, 157.5];
    const trialDuration = 0.686;
    const trialIndex = Math.floor(state.elapsed / trialDuration);
    const visible = state.elapsed % trialDuration < 0.343;
    const orientation = orientations[trialIndex % orientations.length];
    return {
      contrast: visible ? 1 : 0,
      label: `Control ${orientation} deg`,
      mismatch: false,
      orientation,
      phaseCycles: -state.elapsed * 2,
      spatialFrequency: 0.04,
    };
  }

  function sequentialControlSpec() {
    const orientations = [90, 0, 45, 270, 135, 45, 180, 22.5, 315, 67.5];
    const orientation = orientations[Math.floor(state.elapsed / 0.25) % orientations.length];
    return {
      contrast: 1,
      label: `Shuffled ${orientation} deg`,
      mismatch: false,
      orientation,
      phaseCycles: -state.elapsed * 2,
      spatialFrequency: 0.04,
    };
  }

  function jitterControlSpec() {
    const durations = [0.15, 0.343, 0.5, 0.75, 1.0, 1.5, 0.914];
    let localTime = state.elapsed;
    let trialIndex = 0;
    while (localTime >= durations[trialIndex % durations.length] + 0.343) {
      localTime -= durations[trialIndex % durations.length] + 0.343;
      trialIndex += 1;
    }
    const duration = durations[trialIndex % durations.length];
    return {
      contrast: localTime < duration ? 1 : 0,
      label: `${Math.round(duration * 1000)} ms control`,
      mismatch: false,
      orientation: 0,
      phaseCycles: -state.elapsed * 2,
      spatialFrequency: 0.04,
    };
  }

  function openLoopSpec() {
    return {
      contrast: 1,
      label: "Prerecorded visual flow",
      mismatch: false,
      orientation: 0,
      phaseCycles: representativeWheelPhase(state.elapsed + 13.7),
      spatialFrequency: 0.04,
    };
  }

  function receptiveFieldSpec() {
    const positionIndex = Math.floor(state.elapsed / 0.25) % 81;
    const column = positionIndex % 9;
    const row = Math.floor(positionIndex / 9);
    const orientation = [0, 45, 90][Math.floor(state.elapsed / (0.25 * 81)) % 3];
    return {
      contrast: 0.8,
      label: `RF ${orientation} deg at (${column - 4}, ${4 - row})`,
      mismatch: false,
      orientation,
      patch: { altitude: (4 - row) * 10, azimuth: (column - 4) * 10, radius: 10 },
      phaseCycles: -state.elapsed * 4,
      spatialFrequency: 0.08,
    };
  }

  function stimulusSpec() {
    const blockName = currentBlock().name;
    if (blockName === "Standard control" || blockName === "Standard control repeat") {
      return standardControlSpec();
    }
    if (blockName === "Sequential control") {
      return sequentialControlSpec();
    }
    if (blockName === "Jitter control") {
      return jitterControlSpec();
    }
    if (blockName === "Open-loop playback") {
      return openLoopSpec();
    }
    if (blockName === "Receptive field mapping") {
      return receptiveFieldSpec();
    }
    return [oddballSpec, sensorimotorSpec, sequenceSpec, durationSpec][state.sessionIndex]();
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
      const insidePatch = !spec.patch || Math.hypot(
        azimuth - spec.patch.azimuth,
        altitude - spec.patch.altitude,
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

  function drawZebraFallback() {
    context.fillStyle = "#bfc3b8";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.save();
    context.translate(-35 + ((state.elapsed * 16) % 70), 0);
    for (let stripe = -2; stripe < 11; stripe += 1) {
      context.beginPath();
      for (let y = -10; y <= canvas.height + 10; y += 8) {
        const x = stripe * 58 + Math.sin(y * 0.045 + state.elapsed * 0.7 + stripe) * 19;
        if (y === -10) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      context.lineWidth = 25 + (stripe % 3) * 4;
      context.strokeStyle = stripe % 2 === 0 ? "#202520" : "#eeede4";
      context.stroke();
    }
    context.restore();
  }

  function updateMediaState() {
    const movieSelected = currentBlock().name === "Natural movie";
    if (movieSelected && !elements.stimulusVideo.src) {
      elements.stimulusVideo.src = protocol.sources.zebra_movie_url;
      elements.stimulusVideo.load();
    }
    elements.stimulusVideo.hidden = !(movieSelected && state.movieReady);
    canvas.hidden = movieSelected && state.movieReady;
    if (!movieSelected) {
      elements.stimulusVideo.pause();
    } else if (state.playing && state.movieReady) {
      elements.stimulusVideo.play().catch(() => undefined);
    }
  }

  function drawFrame() {
    if (currentBlock().name === "Natural movie") {
      if (!state.movieReady) drawZebraFallback();
      elements.trialLabel.textContent = "Canonical zebra movie";
      elements.mismatchBadge.hidden = true;
    } else {
      const spec = stimulusSpec();
      drawSphericalGrating(spec);
      elements.trialLabel.textContent = spec.label;
      elements.mismatchBadge.hidden = !spec.mismatch;
    }
    elements.syncSquare.classList.toggle("dark", Math.floor(state.elapsed) % 2 === 0);
  }

  function updatePlaybackUi() {
    elements.playbackTime.textContent = `${formatTime(state.elapsed)} / ${formatTime(playbackDuration)}`;
  }

  function attachInteractions() {
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
      elements.stimulusVideo.hidden = true;
      canvas.hidden = false;
    });
    document.addEventListener("keydown", (event) => {
      if (event.code === "Space") {
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
  setPlaying(false);
  window.setInterval(playbackStep, 1000 / 30);
})();