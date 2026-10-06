(() => {
  "use strict";

  const data = JSON.parse(
    document.getElementById("sensorimotor-running-data").textContent
  );
  const analysis = data.analysis || {};
  const thresholds = (analysis.thresholds_cm_s || [1, 2, 5, 10]).map(Number);
  const defaultThreshold = Number(analysis.default_threshold_cm_s || 5);
  const minimumTrials = Number(analysis.minimum_qualifying_trials || 8);
  const EVENT_ORDER = [
    "motor_halt",
    "motor_omission",
    "motor_orientation_45",
    "motor_orientation_90",
  ];
  const MODALITY_LABELS = { neuropixels: "Neuropixels", mesoscope: "Mesoscope" };

  const sessions = (data.sessions || []).filter((row) => row && row.context);
  const elements = {
    rows: document.getElementById("running-rows"),
    summary: document.getElementById("row-summary"),
    threshold: document.getElementById("threshold-select"),
    sort: document.getElementById("sort-select"),
    download: document.getElementById("download-csv"),
    note: document.getElementById("unavailable-note"),
    statSessions: document.getElementById("stat-sessions"),
    statMedian: document.getElementById("stat-median"),
    statStationary: document.getElementById("stat-stationary"),
    statAvailable: document.getElementById("stat-available"),
  };

  const state = { modality: "all", threshold: defaultThreshold, sort: "speed" };

  const key = (value) => String(Number(value));

  function thresholdEntry(row, threshold) {
    const table = row.context.thresholds || {};
    return table[key(threshold)] || null;
  }

  function perTypeCount(entry, label) {
    if (!entry || !entry.per_label) return null;
    const value = entry.per_label[label];
    return value === undefined ? null : Number(value);
  }

  function trialsPerType(row) {
    // Each mismatch type is presented the same number of times in every session.
    const total = Number(row.context.mismatch_trials || 0);
    return total / EVENT_ORDER.length;
  }

  function visibleRows() {
    const rows = sessions.filter(
      (row) => state.modality === "all" || row.modality === state.modality
    );
    const sorted = rows.slice();
    sorted.sort((a, b) => {
      if (state.sort === "subject") {
        return String(a.subject).localeCompare(String(b.subject));
      }
      if (state.sort === "modality") {
        const byModality = String(a.modality).localeCompare(String(b.modality));
        if (byModality !== 0) return byModality;
        return b.context.block.mean_cm_s - a.context.block.mean_cm_s;
      }
      if (state.sort === "fraction") {
        const ea = thresholdEntry(a, state.threshold);
        const eb = thresholdEntry(b, state.threshold);
        return (eb ? eb.qualifying_fraction : 0) - (ea ? ea.qualifying_fraction : 0);
      }
      return b.context.block.mean_cm_s - a.context.block.mean_cm_s;
    });
    return sorted;
  }

  function median(values) {
    if (!values.length) return null;
    const sorted = values.slice().sort((x, y) => x - y);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2
      ? sorted[middle]
      : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  function cell(text, className) {
    const td = document.createElement("td");
    if (className) td.className = className;
    td.textContent = text;
    return td;
  }

  function databarCell(fraction, text, className) {
    const td = document.createElement("td");
    td.className = `databar${className ? ` ${className}` : ""}`;
    const fill = document.createElement("div");
    fill.className = "databar-fill";
    fill.style.width = `${Math.max(0, Math.min(1, fraction)) * 100}%`;
    const label = document.createElement("span");
    label.textContent = text;
    td.append(fill, label);
    return td;
  }

  function render() {
    const rows = visibleRows();
    elements.rows.textContent = "";

    rows.forEach((row) => {
      const entry = thresholdEntry(row, state.threshold);
      const block = row.context.block;
      const perType = trialsPerType(row);
      const tr = document.createElement("tr");

      tr.append(cell(row.session_id || row.asset_path, "text session"));
      tr.append(cell(row.subject, "text"));
      tr.append(cell(MODALITY_LABELS[row.modality] || row.modality, "text"));
      tr.append(cell(block.mean_cm_s.toFixed(2)));
      tr.append(cell(block.median_cm_s.toFixed(2)));

      const runningFraction = Number(
        (row.context.block_running_fraction_by_threshold || {})[
          key(state.threshold)
        ] ?? block.running_fraction
      );
      tr.append(
        databarCell(runningFraction, `${(runningFraction * 100).toFixed(1)}%`)
      );

      if (entry) {
        const fraction = Number(entry.qualifying_fraction || 0);
        tr.append(
          databarCell(
            fraction,
            `${entry.qualifying_trials} (${(fraction * 100).toFixed(0)}%)`
          )
        );
        EVENT_ORDER.forEach((label) => {
          const count = perTypeCount(entry, label);
          if (count === null) {
            tr.append(cell("–"));
            return;
          }
          const fractionOfType = perType > 0 ? count / perType : 0;
          tr.append(
            databarCell(
              fractionOfType,
              `${(fractionOfType * 100).toFixed(0)}% (${count})`,
              count >= minimumTrials ? "pass" : "fail"
            )
          );
        });
      } else {
        for (let index = 0; index < 5; index += 1) tr.append(cell("–"));
      }
      elements.rows.append(tr);
    });

    const means = rows.map((row) => row.context.block.mean_cm_s);
    const stationary = rows.filter(
      (row) => row.context.block.median_cm_s === 0
    ).length;
    const available = rows.filter((row) => {
      const entry = thresholdEntry(row, state.threshold);
      return entry ? entry.available : false;
    }).length;

    const medianValue = median(means);
    elements.statSessions.textContent = String(rows.length);
    elements.statMedian.textContent =
      medianValue === null ? "–" : medianValue.toFixed(2);
    elements.statStationary.textContent = `${stationary} of ${rows.length}`;
    elements.statAvailable.textContent = `${available} of ${rows.length}`;
    elements.summary.textContent =
      `${rows.length} session${rows.length === 1 ? "" : "s"} · ` +
      `≥${state.threshold} cm/s gate · ${minimumTrials}-trial minimum`;

    updateDownload(rows);
  }

  function updateDownload(rows) {
    const header = [
      "session_id",
      "subject",
      "modality",
      "dandiset_id",
      "block_mean_cm_s",
      "block_median_cm_s",
      "block_p90_cm_s",
      "running_fraction",
      "threshold_cm_s",
      "qualifying_trials",
      "qualifying_fraction",
      ...EVENT_ORDER.map((label) => `${label}_trials`),
      ...EVENT_ORDER.map((label) => `${label}_fraction`),
    ];
    const lines = [header.join(",")];
    rows.forEach((row) => {
      const entry = thresholdEntry(row, state.threshold);
      const block = row.context.block;
      const perType = trialsPerType(row);
      const counts = EVENT_ORDER.map((label) => perTypeCount(entry, label));
      const runningFraction = Number(
        (row.context.block_running_fraction_by_threshold || {})[
          key(state.threshold)
        ] ?? block.running_fraction
      );
      lines.push(
        [
          row.session_id || "",
          row.subject,
          row.modality,
          row.dandiset_id || "",
          block.mean_cm_s.toFixed(4),
          block.median_cm_s.toFixed(4),
          block.p90_cm_s.toFixed(4),
          runningFraction.toFixed(6),
          state.threshold,
          entry ? entry.qualifying_trials : "",
          entry ? Number(entry.qualifying_fraction).toFixed(6) : "",
          ...counts.map((value) => (value === null ? "" : value)),
          ...counts.map((value) =>
            value === null || perType <= 0 ? "" : (value / perType).toFixed(6)
          ),
        ].join(",")
      );
    });
    const blob = new Blob([`${lines.join("\n")}\n`], {
      type: "text/csv;charset=utf-8",
    });
    if (elements.download.dataset.url) {
      URL.revokeObjectURL(elements.download.dataset.url);
    }
    const url = URL.createObjectURL(blob);
    elements.download.href = url;
    elements.download.dataset.url = url;
  }

  function buildThresholds() {
    thresholds.forEach((threshold) => {
      const option = document.createElement("option");
      option.value = String(threshold);
      option.textContent = `≥ ${threshold} cm/s`;
      if (threshold === defaultThreshold) option.selected = true;
      elements.threshold.append(option);
    });
  }

  function buildUnavailableNote() {
    const unavailable = (data.modalities || {}).unavailable || {};
    const names = Object.keys(unavailable);
    if (!names.length) return;
    const parts = names.map((name) => {
      const record = unavailable[name] || {};
      const label = MODALITY_LABELS[name] || name.toUpperCase();
      return `${label}: ${record.reason || "unavailable"}`;
    });
    elements.note.textContent = `Not included — ${parts.join("; ")}.`;
    elements.note.hidden = false;
  }

  function bind() {
    document.querySelectorAll(".modality-button").forEach((button) => {
      button.addEventListener("click", () => {
        state.modality = button.dataset.modality;
        document.querySelectorAll(".modality-button").forEach((other) => {
          const active = other === button;
          other.classList.toggle("active", active);
          other.setAttribute("aria-pressed", active ? "true" : "false");
        });
        render();
      });
    });
    elements.threshold.addEventListener("change", (event) => {
      state.threshold = Number(event.target.value);
      render();
    });
    elements.sort.addEventListener("change", (event) => {
      state.sort = event.target.value;
      render();
    });
  }

  buildThresholds();
  buildUnavailableNote();
  bind();
  render();
})();
