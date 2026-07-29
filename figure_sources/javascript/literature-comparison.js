(() => {
  "use strict";

  const data = JSON.parse(document.getElementById("literature-data").textContent);
  const elements = {
    body: document.getElementById("table-body"),
    dimension: document.getElementById("dimension-select"),
    dimensionLabel: document.getElementById("dimension-label"),
    download: document.getElementById("download-csv"),
    empty: document.getElementById("empty-state"),
    headers: document.getElementById("table-headers"),
    rowCount: document.getElementById("row-count"),
    search: document.getElementById("row-search"),
    tabs: document.getElementById("mode-tabs"),
  };
  const state = { mode: "parameter", visibleRows: [] };

  function normalize(value) {
    return String(value ?? "").toLowerCase().replace(/\s+/g, " ").trim();
  }

  function csvCell(value) {
    return `"${String(value).replaceAll('"', '""')}"`;
  }

  function setOptions() {
    elements.dimension.replaceChildren();
    const values = state.mode === "parameter" ? data.parameters : data.studies;
    values.forEach((value) => elements.dimension.append(new Option(value, value)));
    elements.dimensionLabel.textContent = state.mode === "parameter" ? "Parameter" : "Study";
    elements.search.placeholder = state.mode === "parameter" ? "Filter studies" : "Filter parameters";
  }

  function rowsForMode() {
    if (state.mode === "parameter") {
      const parameterIndex = data.parameters.indexOf(elements.dimension.value);
      return data.studies.map((study, studyIndex) => [
        study,
        data.values[parameterIndex][studyIndex],
      ]);
    }
    const studyIndex = data.studies.indexOf(elements.dimension.value);
    return data.parameters.map((parameter, parameterIndex) => [
      parameter,
      data.values[parameterIndex][studyIndex],
    ]);
  }

  function headersForMode() {
    return state.mode === "parameter"
      ? ["Publication", elements.dimension.value]
      : ["Parameter", elements.dimension.value];
  }

  function render() {
    const query = normalize(elements.search.value);
    const rows = rowsForMode();
    state.visibleRows = rows.filter((row) => !query || normalize(row.join(" ")).includes(query));

    elements.headers.replaceChildren();
    headersForMode().forEach((header) => {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = header;
      elements.headers.append(cell);
    });

    elements.body.replaceChildren();
    state.visibleRows.forEach((row) => {
      const tableRow = document.createElement("tr");
      row.forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value;
        tableRow.append(cell);
      });
      elements.body.append(tableRow);
    });

    elements.rowCount.textContent = `${state.visibleRows.length} of ${rows.length}`;
    elements.empty.hidden = state.visibleRows.length !== 0;
    const csv = [headersForMode(), ...state.visibleRows]
      .map((row) => row.map(csvCell).join(","))
      .join("\n");
    elements.download.href = `data:text/csv;charset=utf-8,%EF%BB%BF${encodeURIComponent(csv)}`;
    elements.download.download = `openscope-oddball-studies-${state.mode}.csv`;
  }

  function selectMode(mode) {
    state.mode = mode;
    elements.search.value = "";
    elements.tabs.querySelectorAll("button").forEach((button) => {
      const active = button.dataset.mode === mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    setOptions();
    render();
  }

  elements.tabs.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => selectMode(button.dataset.mode));
  });
  elements.dimension.addEventListener("change", render);
  elements.search.addEventListener("input", render);
  selectMode("parameter");
})();
