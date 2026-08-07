(() => {
  "use strict";

  const data = JSON.parse(document.getElementById("unit-yield-data").textContent);
  const SVG_NS = "http://www.w3.org/2000/svg";
  const mouseNeutral = "#9AA29F";
  const selectedMouse = "#087F8C";
  const elements = {
    chart: document.getElementById("unit-yield-chart"),
    download: document.getElementById("download-csv"),
    mouse: document.getElementById("mouse-select"),
    summary: document.getElementById("record-summary"),
    table: document.getElementById("session-table-body"),
    tableCount: document.getElementById("session-row-count"),
    tooltip: document.getElementById("chart-tooltip"),
  };
  const state = { metric: "percent", mouse: "all" };
  const mouseIds = [...new Set(data.records.map((record) => record.mouse_id))].sort();

  function svgElement(tag, attributes = {}, text = "") {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, value));
    if (text) element.textContent = text;
    return element;
  }

  function csvCell(value) {
    return `"${String(value ?? "").replaceAll('"', '""')}"`;
  }

  function visibleRecords() {
    return data.records.filter(
      (record) => state.mouse === "all" || record.mouse_id === state.mouse,
    );
  }

  function plottedRecords() {
    return visibleRecords().filter((record) => record.included);
  }

  function niceMaximum(value) {
    if (!Number.isFinite(value) || value <= 0) return 100;
    const magnitude = 10 ** Math.floor(Math.log10(value));
    const normalized = value / magnitude;
    const step = normalized <= 1.2 ? 1.2 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
    return step * magnitude;
  }

  function formatValue(value, digits = 1) {
    return Number(value).toLocaleString(undefined, {
      maximumFractionDigits: digits,
      minimumFractionDigits: digits,
    });
  }

  function tooltipText(record) {
    const percent = record.percentOfDay1 == null ? "Excluded" : `${formatValue(record.percentOfDay1)}%`;
    return `<strong>Mouse ${record.mouse_id} · Day ${record.day}</strong><br>`
      + `${record.date}<br>${record.qcUnitCount.toLocaleString()} of `
      + `${record.total_unit_count.toLocaleString()} units pass QC<br>`
      + `${record.probeCount} probes · ${formatValue(record.unitsPerProbe)} QC units/probe<br>`
      + `${percent} of day 1`;
  }

  function showTooltip(record, clientX, clientY) {
    elements.tooltip.innerHTML = tooltipText(record);
    elements.tooltip.hidden = false;
    const width = elements.tooltip.offsetWidth;
    const height = elements.tooltip.offsetHeight;
    elements.tooltip.style.left = `${Math.min(clientX + 12, window.innerWidth - width - 8)}px`;
    elements.tooltip.style.top = `${Math.max(8, Math.min(clientY + 12, window.innerHeight - height - 8))}px`;
  }

  function hideTooltip() {
    elements.tooltip.hidden = true;
  }

  function renderChart() {
    const records = plottedRecords();
    const summary = data.summary;
    const valueKey = state.metric === "percent" ? "percentOfDay1" : "unitsPerProbe";
    const meanKey = state.metric === "percent" ? "meanPercent" : "meanUnitsPerProbe";
    const yLabel = state.metric === "percent"
      ? "QC units per probe (% of day 1)"
      : "QC units per probe";
    const width = 960;
    const height = 410;
    const margin = { left: 82, right: 24, top: 24, bottom: 64 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const days = summary.map((row) => row.day);
    const minDay = Math.min(...days);
    const maxDay = Math.max(...days);
    const allValues = [
      ...records.map((record) => record[valueKey]),
      ...summary.map((row) => row[meanKey]),
    ];
    const rawMaximum = Math.max(...allValues);
    const yMax = state.metric === "percent" ? 140 : niceMaximum(rawMaximum * 1.08);
    const x = (day) => margin.left
      + (maxDay === minDay ? plotWidth / 2 : (day - minDay) / (maxDay - minDay) * plotWidth);
    const y = (value) => margin.top + plotHeight - value / yMax * plotHeight;

    elements.chart.replaceChildren(
      svgElement("title", { id: "chart-title" }, "Neuropixels unit yield across recording days"),
      svgElement(
        "desc",
        { id: "chart-description" },
        "Individual mouse trajectories and daily means for QC-passing unit yield.",
      ),
      svgElement("rect", { width, height, fill: "#FFFFFF" }),
    );

    const tickCount = 5;
    for (let index = 0; index <= tickCount; index += 1) {
      const value = yMax * index / tickCount;
      const tickY = y(value);
      elements.chart.append(
        svgElement("line", {
          x1: margin.left - 6, y1: tickY, x2: margin.left, y2: tickY,
          stroke: "#69716F", "stroke-width": 1.5,
        }),
        svgElement("text", {
          x: margin.left - 12, y: tickY + 4, "text-anchor": "end",
          fill: "#68706E", "font-family": "Myriad Pro, Arial, sans-serif", "font-size": 12,
        }, state.metric === "percent" ? `${Math.round(value)}` : formatValue(value, 0)),
      );
    }

    if (state.metric === "percent") {
      elements.chart.append(svgElement("line", {
        x1: margin.left, y1: y(100), x2: width - margin.right, y2: y(100),
        stroke: "#5E6664", "stroke-width": 1.5, "stroke-dasharray": "7 6",
      }));
    }

    const byMouse = new Map();
    records.forEach((record) => {
      if (!byMouse.has(record.mouse_id)) byMouse.set(record.mouse_id, []);
      byMouse.get(record.mouse_id).push(record);
    });
    byMouse.forEach((mouseRecords, mouseId) => {
      mouseRecords.sort((first, second) => first.day - second.day);
      const points = mouseRecords.map((record) => `${x(record.day)},${y(record[valueKey])}`).join(" ");
      const color = state.mouse === "all" ? mouseNeutral : selectedMouse;
      elements.chart.append(svgElement("polyline", {
        points, fill: "none", stroke: color,
        "stroke-width": state.mouse === "all" ? 1.5 : 2.5,
        "stroke-opacity": state.mouse === "all" ? 0.62 : 1,
      }));
      mouseRecords.forEach((record) => {
        const point = svgElement("circle", {
          cx: x(record.day), cy: y(record[valueKey]), r: state.mouse === "all" ? 4.5 : 6,
          fill: color, "fill-opacity": state.mouse === "all" ? 0.72 : 1, tabindex: 0,
          role: "img",
          "aria-label": `Mouse ${mouseId}, day ${record.day}, ${formatValue(record[valueKey])}`,
        });
        point.addEventListener("pointerenter", (event) => showTooltip(record, event.clientX, event.clientY));
        point.addEventListener("pointermove", (event) => showTooltip(record, event.clientX, event.clientY));
        point.addEventListener("pointerleave", hideTooltip);
        point.addEventListener("focus", () => {
          const bounds = point.getBoundingClientRect();
          showTooltip(record, bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);
        });
        point.addEventListener("blur", hideTooltip);
        elements.chart.append(point);
      });
    });

    const meanPoints = summary.map((row) => `${x(row.day)},${y(row[meanKey])}`).join(" ");
    elements.chart.append(svgElement("polyline", {
      points: meanPoints, fill: "none", stroke: "#222829", "stroke-width": 5,
    }));
    summary.forEach((row) => elements.chart.append(svgElement("circle", {
      cx: x(row.day), cy: y(row[meanKey]), r: 7, fill: "#222829",
      stroke: "#FFFFFF", "stroke-width": 2,
    })));

    const axisY = margin.top + plotHeight;
    elements.chart.append(svgElement("line", {
      x1: margin.left, y1: axisY, x2: width - margin.right, y2: axisY,
      stroke: "#69716F", "stroke-width": 1.5,
    }));
    const summaryByDay = Object.fromEntries(summary.map((row) => [row.day, row]));
    for (let day = minDay; day <= maxDay; day += 1) {
      const dayX = x(day);
      const count = summaryByDay[day]?.sessionCount ?? 0;
      elements.chart.append(
        svgElement("line", {
          x1: dayX, y1: axisY, x2: dayX, y2: axisY + 6,
          stroke: "#69716F", "stroke-width": 1.5,
        }),
        svgElement("text", {
          x: dayX, y: axisY + 26, "text-anchor": "middle", fill: "#303536",
          "font-family": "Myriad Pro, Arial, sans-serif", "font-size": 14, "font-weight": 600,
        }, `Day ${day}`),
        svgElement("text", {
          x: dayX, y: axisY + 44, "text-anchor": "middle", fill: "#68706E",
          "font-family": "Myriad Pro, Arial, sans-serif", "font-size": 12,
        }, `n=${count}`),
      );
    }
    elements.chart.append(svgElement("text", {
      x: 20, y: margin.top + plotHeight / 2, "text-anchor": "middle", fill: "#303536",
      transform: `rotate(-90 20 ${margin.top + plotHeight / 2})`,
      "font-family": "Myriad Pro, Arial, sans-serif", "font-size": 14,
    }, yLabel));

    elements.chart.append(
      svgElement("line", { x1: 722, y1: 16, x2: 756, y2: 16, stroke: "#222829", "stroke-width": 5 }),
      svgElement("circle", { cx: 739, cy: 16, r: 6, fill: "#222829", stroke: "#fff", "stroke-width": 2 }),
      svgElement("text", {
        x: 765, y: 21, fill: "#303536", "font-family": "Myriad Pro, Arial, sans-serif", "font-size": 13,
      }, "Daily mean"),
      svgElement("line", { x1: 854, y1: 16, x2: 888, y2: 16, stroke: mouseNeutral, "stroke-width": 1.5 }),
      svgElement("circle", { cx: 871, cy: 16, r: 4, fill: mouseNeutral }),
      svgElement("text", {
        x: 897, y: 21, fill: "#303536", "font-family": "Myriad Pro, Arial, sans-serif", "font-size": 13,
      }, "Mouse"),
    );
  }

  function renderTable() {
    const records = visibleRecords();
    elements.table.replaceChildren();
    records.forEach((record) => {
      const row = document.createElement("tr");
      row.classList.toggle("excluded", !record.included);
      const sessionLink = document.createElement("a");
      sessionLink.href = `${data.sourceUrl}/files?location=${encodeURIComponent(record.asset_path)}`;
      sessionLink.target = "_blank";
      sessionLink.rel = "noreferrer";
      sessionLink.textContent = record.session_id;
      const values = [
        sessionLink,
        record.mouse_id,
        record.date,
        record.day,
        Number(record.total_unit_count).toLocaleString(),
        record.qcUnitCount.toLocaleString(),
        record.probeCount,
        formatValue(record.unitsPerProbe),
        record.percentOfDay1 == null ? "—" : formatValue(record.percentOfDay1),
      ];
      values.forEach((value) => {
        const cell = document.createElement("td");
        cell.append(value instanceof Node ? value : document.createTextNode(value));
        row.append(cell);
      });
      if (!record.included) row.title = record.exclusionReason;
      elements.table.append(row);
    });

    const headers = [
      "session_id", "mouse_id", "date", "day", "total_unit_count", "qc_unit_count",
      "probe_count", "units_per_probe", "percent_of_day_1", "included", "asset_id", "asset_path",
    ];
    const csvRows = records.map((record) => [
      record.session_id, record.mouse_id, record.date, record.day, record.total_unit_count,
      record.qcUnitCount, record.probeCount, record.unitsPerProbe, record.percentOfDay1,
      record.included, record.asset_id, record.asset_path,
    ]);
    const csv = [headers, ...csvRows].map((values) => values.map(csvCell).join(",")).join("\n");
    elements.download.href = `data:text/csv;charset=utf-8,%EF%BB%BF${encodeURIComponent(csv)}`;
    elements.download.download = `openscope-neuropixels-unit-yield-${state.mouse}.csv`;

    const included = records.filter((record) => record.included);
    const subjectCount = new Set(included.map((record) => record.mouse_id)).size;
    const subjectLabel = subjectCount === 1 ? "mouse" : "mice";
    elements.summary.textContent = `${included.length} plotted sessions · ${subjectCount} ${subjectLabel}`;
    elements.tableCount.textContent = `${records.length} ${records.length === 1 ? "row" : "rows"}`;
  }

  function render() {
    renderChart();
    renderTable();
  }

  elements.mouse.append(new Option("All mice", "all"));
  mouseIds.forEach((mouseId) => elements.mouse.append(new Option(mouseId, mouseId)));
  elements.mouse.addEventListener("change", () => {
    state.mouse = elements.mouse.value;
    render();
  });
  document.querySelectorAll(".metric-button").forEach((button) => {
    button.addEventListener("click", () => {
      state.metric = button.dataset.metric;
      document.querySelectorAll(".metric-button").forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle("active", active);
        candidate.setAttribute("aria-pressed", String(active));
      });
      renderChart();
    });
  });
  render();
})();