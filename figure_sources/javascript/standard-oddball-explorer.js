(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("oddball-data").textContent);
  const get = (id) => document.getElementById(id);
  const state = { modality: "neuropixels", event: "orientation_90", area: "all",
    screen: "all", metric: "context", sort: "rastermap", scope: "population",
    source: null, color: 100 };
  const cache = new Map();
  let visibleRows = [];
  const screens = ["q1", "q2", "joint"];
  const colors = ["#56B4E9", "#E69F00", "#148f82"];
  const labels = ["Q1", "Q2", "Both"];
  const plot = { left: 85, right: 1020, top: 22, bottom: 355 };
  function dataset() {
    const d = data.datasets.find((item) => item.id === state.modality);
    const population = d.populations[state.event];
    if (!population) throw new Error(`Missing ${d.id}/${state.event} population data.`);
    return { ...d, population };
  }
  const eventLabel = () => data.events.find((e) => e.id === state.event).label;
  function decode(d) {
    const key = `${d.id}:${d.population.event}`;
    if (!cache.has(key)) {
      const raw = atob(d.population.values);
      const bytes = Uint8Array.from(raw, (c) => c.charCodeAt(0));
      const view = new DataView(bytes.buffer);
      const values = new Float64Array(raw.length / 8);
      for (let i = 0; i < values.length; i += 1) values[i] = view.getFloat64(i * 8, true);
      if (values.length !== d.population.shape.reduce((a, b) => a * b, 1)) {
        throw new Error("Population data shape mismatch.");
      }
      cache.set(key, values);
    }
    return cache.get(key);
  }
  function signal(d, condition, row, column) {
    const [, n, t] = d.population.shape;
    return decode(d)[(condition * n + row) * t + column];
  }
  function metric(d, row, column) {
    const context = signal(d, 0, row, column), control = signal(d, 1, row, column);
    return state.metric === "difference" ? context - control
      : state.metric === "control" ? control : context;
  }
  function options(select, items, selected) {
    select.replaceChildren(...items.map(({ id, label }) => {
      const option = document.createElement("option");
      option.value = id; option.textContent = label; return option;
    }));
    select.value = selected;
  }
  function tabs() {
    get("modality-tabs").replaceChildren(...data.datasets.map((d) => {
      const button = document.createElement("button");
      button.type = "button"; button.textContent = d.label;
      button.dataset.modality = d.id;
      button.setAttribute("aria-pressed", String(state.modality === d.id));
      button.addEventListener("click", () => {
        state.modality = d.id; state.area = "all"; state.source = null;
        tabs(); areas(); render();
      });
      return button;
    }));
  }
  function areas() {
    const d = dataset();
    const groups = [...new Set([
      ...d.cohort.map((r) => r.group), ...d.population.units.map((u) => u.group),
    ])];
    get("area-label").textContent = d.id === "slap2" ? "DMD (VISp)" : "Area";
    options(get("area-select"), [
      { id: "all", label: d.id === "slap2" ? "Both DMDs" : "All available areas" },
      ...groups.map((g) => ({ id: g, label: g })),
    ], state.area);
  }
  function orderedRows(d) {
    const p = d.population;
    let rows = p.order.filter((i) => {
      const unit = p.units[i];
      return (state.area === "all" || unit.group === state.area)
        && (state.screen === "all" || unit[state.screen]);
    });
    function magnitude(i) {
      const indices = p.time.map((t, k) => ({ t, k })).filter(({ t }) => t >= 0 && t < 0.5);
      return Math.abs(indices.reduce((s, { k }) => s + metric(d, i, k), 0) / indices.length);
    }
    function peak(i) {
      let best = 0, index = null;
      p.time.forEach((t, k) => {
        if (t >= 0 && metric(d, i, k) > best) { best = metric(d, i, k); index = k; }
      });
      return index === null ? Infinity : p.time[index];
    }
    if (state.sort !== "rastermap") rows.sort((a, b) => {
      if (state.sort === "area") return p.units[a].group.localeCompare(p.units[b].group);
      return state.sort === "peak" ? peak(a) - peak(b) : magnitude(b) - magnitude(a);
    });
    if (d.id === "slap2") {
      rows = ["DMD1", "DMD2"].flatMap((g) => rows.filter((i) => p.units[i].group === g));
    }
    return rows;
  }
  function clear(canvas) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.font = "16px Arial, sans-serif"; ctx.fillStyle = "#293133";
    return ctx;
  }
  function color(value, limit) {
    const strength = Math.min(1, Math.abs(value) / limit);
    const end = value < 0 ? [45, 125, 190] : [196, 47, 39];
    return end.map((c) => Math.round(255 + (c - 255) * strength));
  }
  function colorbar(d, limit) {
    const canvas = get("colorbar-canvas"), ctx = clear(canvas);
    const left = 350, width = 400, top = 32, height = 16;
    for (let x = 0; x < width; x += 1) {
      ctx.fillStyle = `rgb(${color((2 * x / (width - 1) - 1) * limit, limit).join(",")})`;
      ctx.fillRect(left + x, top, 1, height);
    }
    ctx.strokeStyle = "#293133"; ctx.strokeRect(left, top, width, height);
    ctx.fillStyle = "#293133"; ctx.textAlign = "center";
    ctx.fillText(d.color_label, left + width / 2, 20);
    const suffix = d.id === "mesoscope" ? "%" : d.id === "slap2" ? " a.u." : "";
    for (const [fraction, label] of [
      [0, `−${limit.toPrecision(3)}${suffix}`], [0.5, "0"],
      [1, `+${limit.toPrecision(3)}${suffix}`],
    ]) {
      const x = left + fraction * width;
      ctx.beginPath(); ctx.moveTo(x, top + height); ctx.lineTo(x, top + height + 5);
      ctx.stroke(); ctx.fillText(label, x, 73);
    }
    canvas.setAttribute("aria-label", `${d.color_label}, ${state.metric}: blue ${
      -limit} ${d.unit}, white zero, red ${limit} ${d.unit}; values outside limits saturate.`);
  }
  function xTime(d, t, left = plot.left, right = plot.right) {
    const [start, stop] = d.population.window;
    return left + (t - start) / (stop - start) * (right - left);
  }
  function timeAxis(ctx, d, bottom) {
    ctx.fillStyle = "#293133"; ctx.textAlign = "center";
    for (const t of [-1.5, -1, -0.5, 0, 0.5, 1, 1.5]) {
      ctx.fillText(String(t), xTime(d, t), bottom + 24);
    }
    ctx.fillText("Time from deviant (s)", (plot.left + plot.right) / 2, bottom + 52);
    ctx.beginPath(); ctx.strokeStyle = "#293133"; ctx.lineWidth = 1;
    ctx.moveTo(plot.left, bottom); ctx.lineTo(plot.right, bottom); ctx.stroke();
    ctx.textAlign = "left";
  }
  function heatmap(d) {
    const canvas = get("heatmap-canvas"), ctx = clear(canvas);
    const p = d.population, tCount = p.time.length, rows = visibleRows;
    const absolute = rows.flatMap((row) => p.time.map((_, k) => Math.abs(metric(d, row, k))));
    absolute.sort((a, b) => a - b);
    const limit = Math.max(absolute[Math.floor((absolute.length - 1) * 0.99)], 1e-9)
      * state.color / 100;
    colorbar(d, limit);
    const image = ctx.createImageData(tCount, rows.length);
    rows.forEach((row, r) => p.time.forEach((_, k) => {
      const offset = (r * tCount + k) * 4;
      image.data.set([...color(metric(d, row, k), limit), 255], offset);
    }));
    const buffer = document.createElement("canvas");
    buffer.width = tCount; buffer.height = rows.length;
    buffer.getContext("2d").putImageData(image, 0, 0);
    ctx.imageSmoothingEnabled = false;
    const dt = p.time[1] - p.time[0];
    const imageStart = xTime(d, p.time[0] - dt / 2);
    const imageStop = xTime(d, p.time[p.time.length - 1] + dt / 2);
    ctx.save(); ctx.beginPath();
    ctx.rect(plot.left, plot.top, plot.right - plot.left, plot.bottom - plot.top); ctx.clip();
    ctx.drawImage(buffer, imageStart, plot.top, imageStop - imageStart, plot.bottom - plot.top);
    ctx.restore();
    ctx.fillText("1", 50, plot.top + 14);
    ctx.fillText(String(rows.length), 40, plot.bottom);
    for (let r = 1; r < rows.length; r += 1) {
      if (d.id === "slap2" && p.units[rows[r]].group !== p.units[rows[r - 1]].group) {
        const y = plot.top + r / rows.length * (plot.bottom - plot.top);
        ctx.beginPath(); ctx.strokeStyle = "#293133";
        ctx.moveTo(plot.left, y); ctx.lineTo(plot.right, y); ctx.stroke();
      }
    }
    if (d.id === "slap2") for (const g of ["DMD1", "DMD2"]) {
      const ranks = rows.map((row, r) => p.units[row].group === g ? r : -1).filter((r) => r >= 0);
      if (ranks.length) {
        const middle = (ranks[0] + ranks[ranks.length - 1] + 1) / 2;
        const y = plot.top + middle / rows.length * (plot.bottom - plot.top);
        ctx.fillText(g, plot.right + 8, y); ctx.fillText(`n=${ranks.length}`, plot.right + 8, y + 19);
      }
    }
    presentationGuides(ctx, d, plot.top, plot.bottom, false);
    timeAxis(ctx, d, plot.bottom);
    canvas.setAttribute("aria-label", `${d.label}, ${eventLabel()}, ${rows.length} ${
      d.kind}, ${state.metric} change heatmap in ${d.unit}. Blue negative, red positive.`);
  }
  function sourceReadout(d, row) {
    const u = d.population.units[row];
    const number = (v) => v === null ? "undefined" : Number(v).toPrecision(4);
    get("source-readout").textContent = `${u.label} · Q1 p=${number(u.q1_p)}, MI=${
      number(u.q1_mi)} · Q2 p=${number(u.q2_p)}, MI=${number(u.q2_mi)} · context/control trials ${
      u.q2_context_trials}/${u.q2_control_trials}. Wider display recorded-trial ranges: ${
      u.display_trial_counts.map((range) => range.join("–")).join(" context / ")} control.`;
  }
  function presentationGuides(ctx, d, top, bottom, shading) {
    for (const presentation of d.population.presentations) {
      const [start, stop] = presentation.span;
      const clippedStart = Math.max(d.population.window[0], start);
      const clippedStop = Math.min(d.population.window[1], stop);
      if (clippedStart >= clippedStop) continue;
      const mismatch = presentation.offset === 0;
      if (shading) {
        ctx.fillStyle = mismatch ? "#77777722" : "#cfaf6e33";
        ctx.fillRect(xTime(d, clippedStart), top,
          xTime(d, clippedStop) - xTime(d, clippedStart), bottom - top);
      }
      ctx.beginPath(); ctx.strokeStyle = mismatch ? "#333" : "#777";
      ctx.lineWidth = mismatch ? 1 : 0.6; ctx.setLineDash(mismatch ? [5, 4] : [2, 4]);
      ctx.moveTo(xTime(d, clippedStart), top);
      ctx.lineTo(xTime(d, clippedStart), bottom); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = "#293133"; ctx.textAlign = "center";
      ctx.fillText(presentation.label, xTime(d, (clippedStart + clippedStop) / 2), top - 5);
    }
    ctx.textAlign = "left";
  }
  function trace(d) {
    const ctx = clear(get("response-canvas")), p = d.population;
    const rows = state.scope === "source"
      ? visibleRows.filter((i) => p.units[i].id === state.source) : visibleRows;
    if (!rows.length) throw new Error("Selected trace source is unavailable.");
    const tCount = p.time.length;
    const curves = [0, 1].map((condition) => p.time.map((_, k) => {
      const values = rows.map((row) => signal(d, condition, row, k));
      const mean = values.reduce((a, b) => a + b, 0) / rows.length;
      const sem = rows.length > 1 && state.scope === "population"
        ? Math.sqrt(values.reduce((s, v) => s + (v - mean) ** 2, 0)
          / (rows.length - 1) / rows.length) : 0;
      return { mean, sem };
    }));
    let low = 0, high = 0;
    curves.flat().forEach(({ mean, sem }) => { low = Math.min(low, mean - sem);
      high = Math.max(high, mean + sem); });
    const pad = Math.max((high - low) * 0.1, 0.001); low -= pad; high += pad;
    const bottom = 215, top = 32;
    const y = (v) => bottom - (v - low) / (high - low) * (bottom - top);
    presentationGuides(ctx, d, top, bottom, true);
    for (const v of [low + pad, 0, high - pad]) {
      ctx.fillStyle = "#293133"; ctx.textAlign = "right";
      ctx.fillText(v.toPrecision(3), plot.left - 10, y(v) + 5);
    }
    ctx.textAlign = "left"; ctx.fillText(d.unit, 14, 16);
    curves.forEach((curve, condition) => {
      const c = condition === 0 ? "#148f82" : "#777777";
      ctx.beginPath();
      curve.forEach(({ mean, sem }, k) => {
        const x = xTime(d, p.time[k]);
        if (k === 0) ctx.moveTo(x, y(mean + sem)); else ctx.lineTo(x, y(mean + sem));
      });
      for (let k = tCount - 1; k >= 0; k -= 1) {
        ctx.lineTo(xTime(d, p.time[k]), y(curve[k].mean - curve[k].sem));
      }
      ctx.closePath(); ctx.fillStyle = `${c}33`; ctx.fill();
      ctx.beginPath(); ctx.strokeStyle = c; ctx.lineWidth = 2;
      curve.forEach(({ mean }, k) => {
        if (k === 0) ctx.moveTo(xTime(d, p.time[k]), y(mean));
        else ctx.lineTo(xTime(d, p.time[k]), y(mean));
      }); ctx.stroke();
    });
    ctx.setLineDash([5, 4]); ctx.beginPath(); ctx.strokeStyle = "#555"; ctx.lineWidth = 1;
    ctx.moveTo(xTime(d, 0), top); ctx.lineTo(xTime(d, 0), bottom); ctx.stroke();
    ctx.setLineDash([]); timeAxis(ctx, d, bottom);
    get("response-title").textContent = `Context (teal) / control (grey): ${
      state.scope === "source" ? p.units[rows[0]].label : `${rows.length} selected ${d.kind}`}`;
    get("response-canvas").setAttribute("aria-label", `${d.label}, ${eventLabel()}: ${
      state.scope === "source" ? "single-source trial mean, no trial SEM" :
      `${rows.length} equally weighted sources, across-source SEM, not cohort uncertainty`}.`);
    if (state.scope === "source") sourceReadout(d, rows[0]);
  }
  function cohort(d) {
    const rows = d.cohort.filter((r) => r.event === state.event
      && (state.area === "all" || r.group === state.area));
    const ctx = clear(get("cohort-canvas"));
    get("cohort-canvas").hidden = !rows.length;
    get("cohort-empty").hidden = rows.length > 0;
    get("cohort-empty").textContent = "No eligible jointly testable cohort summary is available for this area/event. This is not a zero-responsive result.";
    if (!rows.length) return;
    const left = 85, right = 1020, bottom = 240, top = 40;
    const y = (fraction) => bottom - fraction * (bottom - top);
    ctx.fillStyle = "#293133"; ctx.textAlign = "right";
    for (const f of [0, 0.5, 1]) ctx.fillText(String(f * 100), left - 10, y(f) + 5);
    ctx.textAlign = "left"; ctx.fillText("Responsive (%)", 12, 20);
    labels.forEach((label, j) => {
      ctx.fillStyle = colors[j]; ctx.fillRect(380 + j * 110, 10, 16, 16);
      ctx.fillStyle = "#293133"; ctx.fillText(label, 401 + j * 110, 24);
    });
    const width = (right - left) / rows.length;
    rows.forEach((r, i) => {
      screens.forEach((s, j) => {
        const center = left + (i + 0.5) * width + (j - 1) * width * 0.23;
        const barWidth = Math.min(45, width * 0.2), fraction = r.counts[s] / r.n;
        ctx.fillStyle = colors[j]; ctx.globalAlpha = 0.65;
        ctx.fillRect(center - barWidth / 2, y(fraction), barWidth, bottom - y(fraction));
        ctx.globalAlpha = 1;
        if (r.intervals[s]) {
          ctx.beginPath(); ctx.strokeStyle = "#333";
          ctx.moveTo(center, y(r.intervals[s][0])); ctx.lineTo(center, y(r.intervals[s][1]));
          ctx.stroke();
        }
        r.points.forEach((m, k) => {
          const x = center + (k - (r.points.length - 1) / 2) * Math.min(5, barWidth / r.points.length);
          ctx.beginPath(); ctx.fillStyle = "white"; ctx.strokeStyle = "#333";
          if (d.id === "slap2" && m.mouse === "829704") {
            ctx.rect(x - 2.5, y(m.counts[s] / m.n) - 2.5, 5, 5);
          } else {
            ctx.arc(x, y(m.counts[s] / m.n), 2.5, 0, 2 * Math.PI);
          }
          ctx.fill(); ctx.stroke();
        });
      });
      ctx.fillStyle = "#293133"; ctx.textAlign = "center";
      ctx.fillText(r.group === "Hippocampus" ? "HIP" : r.group, left + (i + 0.5) * width, bottom + 25);
      ctx.fillText(`n=${r.n.toLocaleString()}`, left + (i + 0.5) * width, bottom + 47);
    });
    ctx.textAlign = "left";
    get("cohort-canvas").setAttribute("aria-label", `${d.label}, ${eventLabel()}. ${
      rows.map((r) => `${r.group}, jointly testable n=${r.n}: ${
        screens.map((s, j) => `${labels[j]} ${r.counts[s]}/${r.n}`).join(", ")}. ${
        r.points.map((m) => `Mouse ${m.mouse}, n=${m.n}: ${
          screens.map((s, j) => `${labels[j]} ${m.counts[s]}`).join(", ")}`).join("; ")}`
      ).join(". ")}`);
  }
  function render() {
    const d = dataset();
    get("color-limit-value").textContent = `${state.color}%`;
    for (const id of ["responsiveness-select", "metric-select", "sort-select",
      "scope-select", "color-limit"]) get(id).disabled = false;
    visibleRows = orderedRows(d);
    const show = visibleRows.length > 0;
    get("source-control").hidden = state.scope !== "source" || !show;
    if (!show) get("source-select").replaceChildren();
    get("population-panels").hidden = !show;
    get("unavailable-message").hidden = show;
    get("unavailable-message").textContent =
      "No population sources match this area/responsiveness selection. Cohort bars remain independent of population filters.";
    get("source-readout").textContent = "";
    if (show) {
      if (!visibleRows.some((i) => d.population.units[i].id === state.source)) {
        state.source = d.population.units[visibleRows[0]].id;
      }
      options(get("source-select"), visibleRows.map((i) => ({
        id: d.population.units[i].id, label: d.population.units[i].label,
      })), state.source);
      get("heatmap-title").textContent = `${d.label}: ${state.metric} change (${d.unit})`;
      heatmap(d); trace(d);
    }
    cohort(d);
  }
  for (const [id, key] of [
    ["event-select", "event"], ["area-select", "area"], ["responsiveness-select", "screen"],
    ["metric-select", "metric"], ["sort-select", "sort"], ["scope-select", "scope"],
    ["source-select", "source"],
  ]) get(id).addEventListener("change", () => { state[key] = get(id).value; render(); });
  get("color-limit").addEventListener("input", () => {
    state.color = Number(get("color-limit").value); render();
  });
  function chooseRow(row) {
    const d = dataset();
    if (!visibleRows.length) return;
    state.scope = "source"; state.source = d.population.units[row].id;
    get("scope-select").value = "source"; render();
  }
  get("heatmap-canvas").addEventListener("click", (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) * 1100 / rect.width;
    const y = (event.clientY - rect.top) * 420 / rect.height;
    if (x < plot.left || x > plot.right || y < plot.top || y >= plot.bottom) return;
    chooseRow(visibleRows[Math.floor((y - plot.top) / (plot.bottom - plot.top) * visibleRows.length)]);
  });
  get("heatmap-canvas").addEventListener("keydown", (event) => {
    if (!["ArrowUp", "ArrowDown", "Enter"].includes(event.key) || !visibleRows.length) return;
    event.preventDefault();
    const index = visibleRows.findIndex((i) => dataset().population.units[i].id === state.source);
    const next = Math.max(0, Math.min(visibleRows.length - 1,
      index + (event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0)));
    chooseRow(visibleRows[next]);
  });
  options(get("event-select"), data.events, state.event);
  tabs(); areas(); render();
})();
