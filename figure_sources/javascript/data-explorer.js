(() => {
  "use strict";

  const data = JSON.parse(document.getElementById("explorer-data").textContent);
  const elements = {
    body: document.getElementById("table-body"),
    context: document.getElementById("context-filter"),
    download: document.getElementById("download-csv"),
    empty: document.getElementById("empty-state"),
    headers: document.getElementById("table-headers"),
    interactiveView: document.getElementById("interactive-view"),
    modality: document.getElementById("modality-filter"),
    search: document.getElementById("table-search"),
    status: document.getElementById("row-count"),
    staticView: document.getElementById("static-view"),
    tabs: document.getElementById("dataset-tabs"),
    viewButtons: document.querySelectorAll(".view-button"),
  };
  const modalityLabels = {
    mesoscope: "Two-photon",
    neuropixels: "Neuropixels",
    slap2: "SLAP2",
  };
  const state = { kind: "animals", view: "static", visibleRows: [] };

  function selectView(view) {
    state.view = view;
    elements.interactiveView.hidden = view !== "interactive";
    elements.staticView.hidden = view !== "static";
    elements.viewButtons.forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function buildTabs() {
    ["animals", "sessions"].forEach((kind) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "dataset-tab";
      button.dataset.kind = kind;
      const label = kind === "animals" ? "Animals" : "Sessions";
      button.innerHTML = `${label}<span>${data.tables[kind].rows.length}</span>`;
      button.addEventListener("click", () => selectTable(kind));
      elements.tabs.append(button);
    });
  }

  function selectTable(kind) {
    state.kind = kind;
    elements.search.value = "";
    elements.search.placeholder = kind === "animals" ? "Search animals" : "Search sessions";
    elements.tabs.querySelectorAll("button").forEach((button) => {
      const active = button.dataset.kind === kind;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    populateFilters();
    renderTable();
  }

  function populateFilters() {
    const rows = data.tables[state.kind].rows;
    setOptions(elements.modality, "All modalities", unique(rows, "modality"), modalityLabels);
    if (state.kind === "sessions") {
      setOptions(elements.context, "All contexts", unique(rows, "context"));
      elements.context.setAttribute("aria-label", "Filter by stimulus context");
    } else {
      setOptions(elements.context, "All QC states", unique(rows, "qc"));
      elements.context.setAttribute("aria-label", "Filter by QC state");
    }
  }

  function renderTable() {
    const table = data.tables[state.kind];
    const query = normalize(elements.search.value);
    state.visibleRows = table.rows.filter((row) => {
      const matchesSearch = !query || normalize(row.csvValues.join(" ")).includes(query);
      const matchesModality = !elements.modality.value
        || row.modality === elements.modality.value;
      const secondaryValue = state.kind === "sessions" ? row.context : row.qc;
      const matchesContext = !elements.context.value
        || secondaryValue === elements.context.value;
      return matchesSearch && matchesModality && matchesContext;
    });

    elements.headers.replaceChildren();
    table.headers.forEach((header) => {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = header;
      elements.headers.append(cell);
    });

    elements.body.replaceChildren();
    state.visibleRows.forEach((row) => elements.body.append(renderRow(row, table)));
    elements.status.value = `${state.visibleRows.length} of ${table.rows.length}`;
    elements.status.textContent = elements.status.value;
    elements.empty.hidden = state.visibleRows.length !== 0;
    updateDownloadLink();
  }

  function renderRow(row, table) {
    const tableRow = document.createElement("tr");
    tableRow.className = `modality-${row.modality}`;
    row.values.forEach((value, index) => {
      const cell = document.createElement("td");
      if (index === table.detailsColumn) {
        const details = document.createElement("details");
        details.className = "id-disclosure";
        const summary = document.createElement("summary");
        summary.textContent = "View metadata";
        const list = document.createElement("dl");
        list.className = "metadata-list";
        row.details.forEach((detail) => {
          const term = document.createElement("dt");
          term.textContent = detail.label;
          const description = document.createElement("dd");
          description.textContent = detail.value;
          list.append(term, description);
        });
        details.append(summary, list);
        cell.append(details);
      } else {
        cell.textContent = value;
      }
      tableRow.append(cell);
    });
    return tableRow;
  }

  function setOptions(select, allLabel, values, labels = {}) {
    select.replaceChildren(new Option(allLabel, ""));
    values.forEach((value) => select.append(new Option(labels[value] ?? titleCase(value), value)));
  }

  function unique(rows, key) {
    return Array.from(new Set(rows.map((row) => row[key]).filter(Boolean)));
  }

  function normalize(value) {
    return String(value ?? "").toLowerCase().replace(/\s+/g, " ").trim();
  }

  function titleCase(value) {
    return value.replace(/\b\w/g, (character) => character.toUpperCase());
  }

  function updateDownloadLink() {
    const table = data.tables[state.kind];
    const csv = [table.csvHeaders, ...state.visibleRows.map((row) => row.csvValues)]
      .map((row) => row.map(csvCell).join(","))
      .join("\n");
    elements.download.href = `data:text/csv;charset=utf-8,%EF%BB%BF${encodeURIComponent(csv)}`;
    elements.download.download = `openscope-predictive-processing-${state.kind}.csv`;
  }

  function csvCell(value) {
    return `"${String(value).replaceAll('"', '""')}"`;
  }

  elements.search.addEventListener("input", renderTable);
  elements.modality.addEventListener("change", renderTable);
  elements.context.addEventListener("change", renderTable);
  elements.viewButtons.forEach((button) => {
    button.addEventListener("click", () => selectView(button.dataset.view));
  });
  buildTabs();
  selectTable("animals");
  selectView("static");
})();