/* Mesoscope ROI signal-to-noise by imaging plane.
 *
 * Four coupled views over one session's eight simultaneously-acquired planes:
 * the segmented field shaded by the chosen SNR definition, that definition
 * against ROI mask area, the dF/F excerpt behind whichever ROI is selected, and
 * the same ROI scored by all three definitions side by side.
 *
 * No runtime dependencies. All numbers come from the embedded JSON payload,
 * which the extractor wrote from the processed NWB.
 */
(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("mesoscope-data").textContent);

  var METRICS = [
    { key: "frac_events_gt4sd", label: "Events > 4 SD", unit: "fraction",
      signal: "n_events", noise: "baseline_noise_sd",
      signalLabel: "events detected", noiseLabel: "baseline SD (raw)" },
    { key: "event_amplitude_snr", label: "Event amplitude SNR", unit: "ratio",
      signal: null, noise: "successive_diff_noise",
      signalLabel: "P95 peak amplitude", noiseLabel: "std(diff(f))/sqrt(2)" },
    { key: "percentile_range_snr", label: "Percentile-range SNR", unit: "ratio",
      signal: null, noise: "fast_residual_mad_sd",
      signalLabel: "P95 - P50 of dF/F", noiseLabel: "fast-residual MAD-SD" }
  ];

  /* -- viridis, sampled at nine stops and interpolated ------------------ */
  var RAMP = [
    [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142], [38, 130, 142],
    [31, 158, 137], [53, 183, 121], [109, 205, 89], [180, 222, 44], [253, 231, 37]
  ];

  function ramp(t) {
    if (!isFinite(t)) return [136, 136, 136];
    t = Math.max(0, Math.min(1, t));
    var x = t * (RAMP.length - 1), i = Math.min(RAMP.length - 2, Math.floor(x)), f = x - i;
    var a = RAMP[i], b = RAMP[i + 1];
    return [Math.round(a[0] + f * (b[0] - a[0])),
            Math.round(a[1] + f * (b[1] - a[1])),
            Math.round(a[2] + f * (b[2] - a[2]))];
  }

  function rgb(c) { return "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")"; }

  /* -- decoding --------------------------------------------------------- */
  function decodeBytes(b64) {
    var bin = atob(b64), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function decodeInt16(b64, scale) {
    var bytes = decodeBytes(b64);
    var q = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2);
    var out = new Float32Array(q.length);
    for (var i = 0; i < q.length; i++) out[i] = q[i] * scale;
    return out;
  }

  function decodeUint16(b64) {
    var bytes = decodeBytes(b64);
    return new Uint16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2);
  }

  /* -- formatting ------------------------------------------------------- */
  function fmt(v, digits) {
    if (v === null || v === undefined || !isFinite(v)) return "n/a";
    return v.toFixed(digits === undefined ? 2 : digits);
  }

  function quantile(sorted, q) {
    if (!sorted.length) return NaN;
    var pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }

  /* -- per-plane derived state, built once on demand -------------------- */
  var planes = DATA.planes;

  planes.forEach(function (p) {
    p.dff = null; p.events = null; p.labels = null; p.projection = null;
  });

  function traces(p) {
    if (p.dff === null) {
      p.dff = decodeInt16(p.dffBase64, p.dffScale);
      p.events = decodeInt16(p.eventsBase64, p.eventsScale);
    }
    return p;
  }

  /* Label image: 0 = background, i+1 = ROI i. Rasterized from the run-length
   * encoding the extractor wrote, so it is exact rather than an outline. */
  function runsOf(p) {
    if (!p.runs) p.runs = decodeUint16(p.maskRunsBase64);
    return p.runs;
  }

  function labels(p) {
    if (p.labels === null) {
      var runs = runsOf(p);
      var lab = new Int32Array(p.imageWidth * p.imageHeight);
      for (var i = 0; i < p.nRois; i++) {
        for (var k = p.maskRunOffsets[i]; k < p.maskRunOffsets[i + 1]; k += 3) {
          var row = runs[k], col = runs[k + 1], len = runs[k + 2], base = row * p.imageWidth + col;
          for (var j = 0; j < len; j++) lab[base + j] = i + 1;
        }
      }
      p.labels = lab;
    }
    return p.labels;
  }

  /* -- shared metric scaling ------------------------------------------- */
  /* Colour limits are pooled over every plane so a shade means the same thing
   * in VISp_0 as in VISl_7; that comparison is the point of the figure. */
  var limits = {};
  METRICS.forEach(function (m) {
    var all = [];
    planes.forEach(function (p) {
      p.rois.forEach(function (r) { if (r[m.key] !== null && isFinite(r[m.key])) all.push(r[m.key]); });
    });
    all.sort(function (a, b) { return a - b; });
    limits[m.key] = { lo: quantile(all, 0.02), hi: quantile(all, 0.98), median: quantile(all, 0.5) };
  });

  function norm(metricKey, value) {
    var L = limits[metricKey];
    if (value === null || !isFinite(value)) return NaN;
    if (L.hi <= L.lo) return 0.5;
    return (value - L.lo) / (L.hi - L.lo);
  }

  /* -- state ------------------------------------------------------------ */
  var state = { metric: METRICS[0], planeIndex: 0, roi: 0 };

  var el = {
    viewer: document.getElementById("mesoscope-plane-snr"),
    interactiveView: document.getElementById("interactive-view"),
    staticView: document.getElementById("static-view"),
    subtitle: document.getElementById("subtitle"),
    picker: document.getElementById("metric-picker"),
    strip: document.getElementById("plane-strip"),
    map: document.getElementById("map"),
    scatter: document.getElementById("scatter"),
    trace: document.getElementById("trace"),
    colorbar: document.getElementById("colorbar"),
    mapMetric: document.getElementById("map-metric"),
    scatterMetric: document.getElementById("scatter-metric"),
    mapCaption: document.getElementById("map-caption"),
    scatterCaption: document.getElementById("scatter-caption"),
    roiTable: document.querySelector("#roi-table tbody"),
    provenance: document.getElementById("provenance"),
    space: document.getElementById("space"),
    spaceMetric: document.getElementById("space-metric"),
    spaceCaption: document.getElementById("space-caption"),
    areaPicker: document.getElementById("area-picker")
  };

  /* -- 3D ROI positions by area ------------------------------------------
     Image x, image y and true imaging depth in microns. Depth is used rather
     than plane rank so the sheet spacing is physical: these planes are not
     evenly spaced, and the depth effect is the figure's main result. */
  var spaceState = { yaw: 0.78, pitch: 0.46, zoom: 1.0, area: null };

  function areas() {
    var seen = [];
    planes.forEach(function (p) {
      if (seen.indexOf(p.structure) < 0) seen.push(p.structure);
    });
    return seen;
  }

  function areaPlanes(area) {
    return planes.filter(function (p) { return p.structure === area; })
                 .sort(function (a, b) { return a.depthUm - b.depthUm; });
  }

  function depthRange() {
    var d = planes.map(function (p) { return p.depthUm; });
    return [Math.min.apply(null, d), Math.max.apply(null, d)];
  }

  function rotate3(x, y, z) {
    x -= 0.5; y -= 0.5; z -= 0.5;
    var cy = Math.cos(spaceState.yaw), sy = Math.sin(spaceState.yaw);
    var cp = Math.cos(spaceState.pitch), sp = Math.sin(spaceState.pitch);
    var x1 = cy * x - sy * z, z1 = sy * x + cy * z;
    return [x1, cp * y - sp * z1, sp * y + cp * z1];
  }

  function project3(x, y, z, c) {
    var r = rotate3(x, y, z);
    var scale = Math.min(c.width, c.height) * 0.70 * spaceState.zoom;
    var persp = 1.8 / (1.8 - r[2]);
    return { x: c.width / 2 + r[0] * scale * persp,
             y: c.height / 2 - r[1] * scale * persp, z: r[2] };
  }

  function spacePoints() {
    var out = [], dr = depthRange(), span = Math.max(1e-6, dr[1] - dr[0]);
    areaPlanes(spaceState.area).forEach(function (p) {
      var pi = planes.indexOf(p), zz = (p.depthUm - dr[0]) / span;
      p.rois.forEach(function (r, i) {
        out.push({ x: r.roi_centroid_x_pix / p.imageWidth,
                   y: r.roi_centroid_y_pix / p.imageHeight,
                   z: zz, planeIndex: pi, roiIndex: i, roi: r, depthUm: p.depthUm });
      });
    });
    return out;
  }

  function drawSpace() {
    var c = el.space, ctx = c.getContext("2d"), m = state.metric;
    ctx.clearRect(0, 0, c.width, c.height);
    var dr = depthRange(), span = Math.max(1e-6, dr[1] - dr[0]);

    areaPlanes(spaceState.area).forEach(function (p) {
      var zz = (p.depthUm - dr[0]) / span;
      var corners = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]].map(function (q) {
        return project3(q[0], q[1], zz, c);
      });
      ctx.beginPath();
      corners.forEach(function (q, i) { i ? ctx.lineTo(q.x, q.y) : ctx.moveTo(q.x, q.y); });
      ctx.strokeStyle = "rgba(138,137,133,0.55)";
      ctx.lineWidth = 1;
      ctx.stroke();
      var lab = corners.reduce(function (a, b) { return b.x < a.x ? b : a; });
      ctx.fillStyle = "#52514e";
      ctx.font = "12px 'Myriad Pro', Arial, sans-serif";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(p.depthUm.toFixed(0) + " \u00b5m ", lab.x, lab.y);
    });

    // painter's algorithm: far points first, so near ROIs read on top
    var pts = spacePoints().map(function (q) {
      var pr = project3(q.x, q.y, q.z, c);
      q.px = pr.x; q.py = pr.y; q.pz = pr.z; return q;
    }).sort(function (a, b) { return a.pz - b.pz; });

    pts.forEach(function (q) {
      var sel = q.planeIndex === state.planeIndex && q.roiIndex === state.roi;
      ctx.beginPath();
      ctx.arc(q.px, q.py, sel ? 4.5 : 2.2, 0, Math.PI * 2);
      ctx.fillStyle = rgb(ramp(norm(m.key, q.roi[m.key])));
      ctx.fill();
      if (sel) {
        ctx.lineWidth = 1.6;
        ctx.strokeStyle = "#eb6834";
        ctx.stroke();
      }
    });
    el.spaceCaption.textContent =
      "Each dot is one ROI of " + spaceState.area + " at its position in the field and its "
      + "plane depth (" + dr[0].toFixed(0) + "\u2013" + dr[1].toFixed(0) + " \u00b5m). "
      + "Drag to rotate, scroll to zoom, click a dot to select that ROI.";
  }

  function nearestSpacePoint(cx, cy) {
    var best = null;
    spacePoints().forEach(function (q) {
      var pr = project3(q.x, q.y, q.z, el.space);
      var d = (pr.x - cx) * (pr.x - cx) + (pr.y - cy) * (pr.y - cy);
      if (!best || d < best.d) best = { d: d, q: q };
    });
    return best && best.d < 400 ? best.q : null;
  }

  function buildAreaPicker() {
    spaceState.area = areas()[0];
    areas().forEach(function (a) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "area-button";
      b.textContent = a;
      b.setAttribute("role", "radio");
      b.addEventListener("click", function () { spaceState.area = a; render(); });
      el.areaPicker.appendChild(b);
      b.dataset.area = a;
    });
  }

  function bindSpace() {
    var drag = null;
    el.space.addEventListener("mousedown", function (e) {
      drag = { x: e.clientX, y: e.clientY, moved: false };
      el.space.style.cursor = "grabbing";
    });
    window.addEventListener("mousemove", function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
      spaceState.yaw += dx * 0.008;
      spaceState.pitch = Math.max(-1.35, Math.min(1.35, spaceState.pitch + dy * 0.008));
      drag.x = e.clientX; drag.y = e.clientY;
      drawSpace();
    });
    window.addEventListener("mouseup", function () {
      if (drag) el.space.style.cursor = "grab";
      drag = null;
    });
    el.space.addEventListener("wheel", function (e) {
      e.preventDefault();
      spaceState.zoom = Math.max(0.45, Math.min(2.6,
        spaceState.zoom * (e.deltaY < 0 ? 1.12 : 0.88)));
      drawSpace();
    }, { passive: false });
    el.space.addEventListener("click", function (e) {
      var b = el.space.getBoundingClientRect();
      var q = nearestSpacePoint((e.clientX - b.left) * el.space.width / b.width,
                                (e.clientY - b.top) * el.space.height / b.height);
      if (q) { state.planeIndex = q.planeIndex; state.roi = q.roiIndex; render(); }
    });
  }

  function plane() { return planes[state.planeIndex]; }

  /* -- map -------------------------------------------------------------- */
  var projectionCache = {};

  function drawMap() {
    var p = plane(), cv = el.map, ctx = cv.getContext("2d");
    cv.width = p.imageWidth; cv.height = p.imageHeight;

    var img = projectionCache[p.plane];
    if (!img) {
      img = new Image();
      img.onload = function () { drawMap(); };
      img.src = "data:image/png;base64," + p.projectionPng;
      projectionCache[p.plane] = img;
    }
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, cv.width, cv.height);
    if (img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, cv.width, cv.height);

    var lab = labels(p);
    var overlay = ctx.getImageData(0, 0, cv.width, cv.height);
    var px = overlay.data;
    var colours = p.rois.map(function (r) { return ramp(norm(state.metric.key, r[state.metric.key])); });
    var ALPHA = 0.72;
    for (var i = 0; i < lab.length; i++) {
      var id = lab[i];
      if (!id) continue;
      var c = colours[id - 1], o = i * 4;
      px[o] = c[0] * ALPHA + px[o] * (1 - ALPHA);
      px[o + 1] = c[1] * ALPHA + px[o + 1] * (1 - ALPHA);
      px[o + 2] = c[2] * ALPHA + px[o + 2] * (1 - ALPHA);
    }
    ctx.putImageData(overlay, 0, 0);

    /* selected ROI outlined in white */
    var sel = state.roi;
    if (sel >= 0 && sel < p.nRois) {
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = Math.max(1, p.imageWidth / 420);
      var runs = runsOf(p);
      ctx.beginPath();
      for (var k = p.maskRunOffsets[sel]; k < p.maskRunOffsets[sel + 1]; k += 3) {
        ctx.rect(runs[k + 1], runs[k], runs[k + 2], 1);
      }
      ctx.stroke();
    }
  }

  function roiAt(event) {
    var p = plane(), rect = el.map.getBoundingClientRect();
    var x = Math.floor((event.clientX - rect.left) / rect.width * p.imageWidth);
    var y = Math.floor((event.clientY - rect.top) / rect.height * p.imageHeight);
    if (x < 0 || y < 0 || x >= p.imageWidth || y >= p.imageHeight) return -1;
    return labels(p)[y * p.imageWidth + x] - 1;
  }

  /* -- scatter: metric against ROI area --------------------------------- */
  function drawScatter() {
    var p = plane(), cv = el.scatter, ctx = cv.getContext("2d");
    var W = cv.width, H = cv.height, L = 52, R = 10, T = 10, B = 38;
    ctx.clearRect(0, 0, W, H);

    var pts = p.rois.filter(function (r) {
      return r.roi_area_pix !== null && r[state.metric.key] !== null && isFinite(r[state.metric.key]);
    });
    var areas = pts.map(function (r) { return r.roi_area_pix; }).sort(function (a, b) { return a - b; });
    var vals = pts.map(function (r) { return r[state.metric.key]; }).sort(function (a, b) { return a - b; });
    if (!pts.length) return;
    var ax0 = 0, ax1 = quantile(areas, 0.99) * 1.05;
    var ay0 = Math.min(0, quantile(vals, 0.01)), ay1 = quantile(vals, 0.99) * 1.05;
    if (ay1 <= ay0) ay1 = ay0 + 1;

    function sx(v) { return L + (v - ax0) / (ax1 - ax0) * (W - L - R); }
    function sy(v) { return H - B - (v - ay0) / (ay1 - ay0) * (H - T - B); }

    ctx.strokeStyle = "#d8dde3"; ctx.fillStyle = "#5b6570";
    ctx.font = "12px 'Myriad Pro', Arial, sans-serif";
    ctx.lineWidth = 1;
    var ti;
    for (ti = 0; ti <= 4; ti++) {
      var gy = sy(ay0 + (ay1 - ay0) * ti / 4);
      ctx.beginPath(); ctx.moveTo(L, gy); ctx.lineTo(W - R, gy); ctx.stroke();
      ctx.textAlign = "right"; ctx.textBaseline = "middle";
      ctx.fillText(fmt(ay0 + (ay1 - ay0) * ti / 4, ay1 < 5 ? 2 : 1), L - 6, gy);
    }
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (ti = 0; ti <= 4; ti++) {
      var vx = ax0 + (ax1 - ax0) * ti / 4;
      ctx.fillText(Math.round(vx), sx(vx), H - B + 6);
    }
    ctx.fillText("ROI mask area (pixels)", (L + W - R) / 2, H - 16);
    ctx.save();
    ctx.translate(13, (T + H - B) / 2); ctx.rotate(-Math.PI / 2);
    ctx.textBaseline = "bottom"; ctx.fillText(state.metric.label, 0, 0);
    ctx.restore();

    pts.forEach(function (r) {
      ctx.fillStyle = rgb(ramp(norm(state.metric.key, r[state.metric.key])));
      ctx.globalAlpha = 0.75;
      ctx.beginPath(); ctx.arc(sx(r.roi_area_pix), sy(r[state.metric.key]), 2.6, 0, 6.2832); ctx.fill();
    });
    ctx.globalAlpha = 1;

    var sel = p.rois[state.roi];
    if (sel && sel.roi_area_pix !== null && isFinite(sel[state.metric.key])) {
      ctx.strokeStyle = "#1f2328"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(sx(sel.roi_area_pix), sy(sel[state.metric.key]), 5.5, 0, 6.2832); ctx.stroke();
    }
  }

  /* -- trace ------------------------------------------------------------ */
  function drawTrace() {
    var p = traces(plane()), cv = el.trace, ctx = cv.getContext("2d");
    var W = cv.width, H = cv.height, L = 54, R = 12, T = 12, B = 34;
    var n = p.excerptFrames, off = state.roi * n;
    ctx.clearRect(0, 0, W, H);
    if (state.roi < 0 || state.roi >= p.nRois) return;

    var dff = p.dff.subarray(off, off + n), ev = p.events.subarray(off, off + n);
    var lo = Infinity, hi = -Infinity, i;
    for (i = 0; i < n; i++) { if (dff[i] < lo) lo = dff[i]; if (dff[i] > hi) hi = dff[i]; }
    if (!(hi > lo)) { hi = lo + 1; }
    var pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    var evMax = 0;
    for (i = 0; i < n; i++) if (ev[i] > evMax) evMax = ev[i];

    var traceH = evMax > 0 ? (H - T - B) * 0.74 : (H - T - B);
    function sx(k) { return L + k / (n - 1) * (W - L - R); }
    function sy(v) { return T + traceH - (v - lo) / (hi - lo) * traceH; }

    ctx.strokeStyle = "#e6e9ed"; ctx.lineWidth = 1;
    ctx.fillStyle = "#5b6570"; ctx.font = "12px 'Myriad Pro', Arial, sans-serif";
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (i = 0; i <= 3; i++) {
      var v = lo + (hi - lo) * i / 3, gy = sy(v);
      ctx.beginPath(); ctx.moveTo(L, gy); ctx.lineTo(W - R, gy); ctx.stroke();
      ctx.fillText(fmt(v, 2), L - 6, gy);
    }

    ctx.strokeStyle = rgb(ramp(norm(state.metric.key, p.rois[state.roi][state.metric.key])));
    ctx.lineWidth = 1.3; ctx.beginPath();
    for (i = 0; i < n; i++) { if (i === 0) ctx.moveTo(sx(i), sy(dff[i])); else ctx.lineTo(sx(i), sy(dff[i])); }
    ctx.stroke();

    if (evMax > 0) {
      var evTop = T + traceH + 10, evH = H - B - evTop;
      ctx.strokeStyle = "#c2410c"; ctx.lineWidth = 1;
      for (i = 0; i < n; i++) {
        if (ev[i] <= 0) continue;
        var h = Math.max(1.5, ev[i] / evMax * evH);
        ctx.beginPath(); ctx.moveTo(sx(i), evTop + evH); ctx.lineTo(sx(i), evTop + evH - h); ctx.stroke();
      }
      ctx.fillStyle = "#c2410c"; ctx.textAlign = "left"; ctx.textBaseline = "bottom";
      ctx.fillText("detected events", L + 2, evTop + evH - 1);
    }

    ctx.fillStyle = "#5b6570"; ctx.textAlign = "center"; ctx.textBaseline = "top";
    var dur = n * p.dtSeconds;
    for (i = 0; i <= 6; i++) {
      var t = dur * i / 6;
      ctx.fillText(t.toFixed(0), sx((n - 1) * i / 6), H - B + 8);
    }
    ctx.fillText("seconds from excerpt start (t = " + (p.excerptStartFrame * p.dtSeconds).toFixed(0) +
                 " s into the recording)", (L + W - R) / 2, H - 14);
    ctx.save();
    ctx.translate(14, (T + T + traceH) / 2); ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center"; ctx.textBaseline = "bottom"; ctx.fillText("dF/F", 0, 0);
    ctx.restore();
  }

  /* -- ROI table -------------------------------------------------------- */
  function drawTable() {
    var p = plane(), r = p.rois[state.roi];
    el.roiTable.innerHTML = "";
    METRICS.forEach(function (m) {
      var tr = document.createElement("tr");
      if (m.key === state.metric.key) tr.className = "is-active";
      var signalValue = m.signal ? fmt(r[m.signal], 0) : "—";
      var cells = [m.label, fmt(r[m.key], m.key === "frac_events_gt4sd" ? 3 : 2),
                   m.signal ? signalValue + " " + m.signalLabel : m.signalLabel,
                   fmt(r[m.noise], 4) + " (" + m.noiseLabel + ")"];
      cells.forEach(function (text, idx) {
        var cell = document.createElement(idx === 0 ? "th" : "td");
        if (idx === 0) cell.scope = "row";
        cell.textContent = text;
        tr.appendChild(cell);
      });
      el.roiTable.appendChild(tr);
    });
    var extra = document.createElement("tr");
    extra.innerHTML = "<th scope=\"row\">ROI " + r.roi_index + "</th><td>" +
      fmt(r.roi_area_pix, 0) + " px</td><td>event rate " + fmt(r.event_rate_hz, 3) +
      " Hz</td><td>soma probability " + fmt(r.soma_probability, 2) + "</td>";
    el.roiTable.appendChild(extra);
  }

  /* -- chrome ----------------------------------------------------------- */
  function planeMedian(p, key) {
    var v = [];
    p.rois.forEach(function (r) { if (r[key] !== null && isFinite(r[key])) v.push(r[key]); });
    v.sort(function (a, b) { return a - b; });
    return quantile(v, 0.5);
  }

  function buildPicker() {
    METRICS.forEach(function (m) {
      var b = document.createElement("button");
      b.type = "button"; b.setAttribute("role", "radio"); b.textContent = m.label;
      b.addEventListener("click", function () { state.metric = m; render(); });
      m.node = b;
      el.picker.appendChild(b);
    });
  }

  function buildStrip() {
    planes.forEach(function (p, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.innerHTML = "<span class=\"pname\">" + p.plane + "</span>" +
        "<span class=\"pmeta\">" + p.nRois + " ROIs" +
        (p.depthUm === null ? "" : " · " + Math.round(p.depthUm) + " um") + "</span>" +
        "<span class=\"pbar\"><span></span></span>";
      b.addEventListener("click", function () {
        state.planeIndex = i; state.roi = defaultRoi(p); render();
      });
      p.node = b;
      el.strip.appendChild(b);
    });
  }

  /* Open each plane on a median-SNR ROI rather than ROI 0, so the first thing
   * the reader sees is representative of that plane. */
  function defaultRoi(p) {
    var key = state.metric.key;
    var scored = p.rois.filter(function (r) { return r[key] !== null && isFinite(r[key]); });
    if (!scored.length) return 0;
    scored.sort(function (a, b) { return a[key] - b[key]; });
    return scored[Math.floor(scored.length / 2)].roi_index;
  }

  function buildColorbar() {
    var stops = RAMP.map(function (c, i) {
      return rgb(c) + " " + (i / (RAMP.length - 1) * 100).toFixed(0) + "%";
    }).join(", ");
    el.colorbar.innerHTML = "<span class=\"lo\"></span>" +
      "<span class=\"ramp\" style=\"background: linear-gradient(to right, " + stops + ")\"></span>" +
      "<span class=\"hi\"></span>";
  }

  function render() {
    var p = plane(), m = state.metric, L = limits[m.key];
    METRICS.forEach(function (x) { x.node.setAttribute("aria-checked", String(x === m)); });
    planes.forEach(function (x, i) {
      x.node.setAttribute("aria-pressed", String(i === state.planeIndex));
      var med = planeMedian(x, m.key), t = norm(m.key, med);
      var bar = x.node.querySelector(".pbar span");
      bar.style.width = (Math.max(0, Math.min(1, t)) * 100).toFixed(1) + "%";
      bar.style.background = rgb(ramp(t));
    });

    el.mapMetric.textContent = m.label;
    el.scatterMetric.textContent = m.label;
    el.colorbar.querySelector(".lo").textContent = fmt(L.lo, m.key === "frac_events_gt4sd" ? 3 : 2);
    el.colorbar.querySelector(".hi").textContent = fmt(L.hi, m.key === "frac_events_gt4sd" ? 3 : 2);

    el.mapCaption.textContent = p.plane + " · " + p.structure +
      (p.depthUm === null ? "" : " at " + Math.round(p.depthUm) + " um") +
      " · " + p.nRois + " ROIs · " + p.projectionLabel +
      ". Colour limits are the 2nd-98th percentile pooled over all planes; click an ROI to inspect it.";
    el.scatterCaption.textContent = "Each point is one ROI in " + p.plane +
      ". A definition that tracks area rather than signal quality would lie on a rising line here.";

    el.spaceMetric.textContent = m.label;
    Array.prototype.forEach.call(el.areaPicker.querySelectorAll(".area-button"), function (b) {
      b.setAttribute("aria-checked", String(b.dataset.area === spaceState.area));
    });

    drawMap(); drawScatter(); drawSpace(); drawTrace(); drawTable();
  }

  /* -- wire up ---------------------------------------------------------- */
  function bindRedrawOnInteractive() {
    var button = document.querySelector('[data-view="interactive"]');
    if (button) button.addEventListener("click", function () { render(); });
  }

  function init() {
    el.subtitle.textContent = "Session " + DATA.sessionId + " · " + planes.length +
      " simultaneously-acquired planes · " +
      planes.reduce(function (a, p) { return a + p.nRois; }, 0) + " ROIs · " +
      DATA.excerptSeconds + " s dF/F excerpt per ROI. " +
      "Each definition is computed over the full recording, not the excerpt.";
    el.provenance.textContent = "Source: " + DATA.sessionSource +
      " · event detector: " + planes[0].eventDetector.replace("_", " ") +
      " · recording length " + (planes[0].durationSeconds / 60).toFixed(1) + " min at " +
      (1 / planes[0].dtSeconds).toFixed(2) + " Hz.";

    buildPicker(); buildStrip(); buildColorbar();

    el.map.addEventListener("click", function (e) {
      var id = roiAt(e);
      if (id >= 0) { state.roi = id; render(); }
    });
    el.map.addEventListener("keydown", function (e) {
      var p = plane();
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { state.roi = (state.roi + 1) % p.nRois; }
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { state.roi = (state.roi - 1 + p.nRois) % p.nRois; }
      else return;
      e.preventDefault(); render();
    });

    bindRedrawOnInteractive();
    buildAreaPicker();
    bindSpace();
    state.roi = defaultRoi(planes[0]);
    render();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
