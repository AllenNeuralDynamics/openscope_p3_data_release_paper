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
    note: document.getElementById("data-access-note"),
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
  const tableLabels = {
    animals: "Animals",
    sessions: "Sessions",
    dataAccess: "Data Access",
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
    ["animals", "sessions", "dataAccess"].forEach((kind) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "dataset-tab";
      button.dataset.kind = kind;
      const label = tableLabels[kind];
      button.innerHTML = `${label}<span>${data.tables[kind].rows.length}</span>`;
      button.addEventListener("click", () => selectTable(kind));
      elements.tabs.append(button);
    });
  }

  function selectTable(kind) {
    state.kind = kind;
    elements.search.value = "";
    elements.search.placeholder = kind === "animals"
      ? "Search animals"
      : kind === "sessions" ? "Search sessions" : "Search data access";
    elements.tabs.querySelectorAll("button").forEach((button) => {
      const active = button.dataset.kind === kind;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    elements.note.hidden = kind !== "dataAccess";
    populateFilters();
    renderTable();
  }

  function populateFilters() {
    const rows = data.tables[state.kind].rows;
    if (state.kind === "dataAccess") {
      setOptions(elements.modality, null, ["neuropixels", "mesoscope", "slap2"], modalityLabels);
      elements.modality.value = "neuropixels";
    } else {
      setOptions(elements.modality, "All modalities", unique(rows, "modality"), modalityLabels);
    }
    if (state.kind === "sessions" || state.kind === "dataAccess") {
      setOptions(elements.context, "All contexts", unique(rows, "context"));
      elements.context.setAttribute("aria-label", "Filter by stimulus context");
    } else {
      setOptions(elements.context, "All QC states", unique(rows, "qc"));
      elements.context.setAttribute("aria-label", "Filter by QC state");
    }
  }

  function renderTable() {
    const table = data.tables[state.kind];
    const columns = visibleColumns(table);
    const query = normalize(elements.search.value);
    state.visibleRows = table.rows.filter((row) => {
      const matchesSearch = !query || normalize(row.csvValues.join(" ")).includes(query);
      const matchesModality = !elements.modality.value
        || row.modality === elements.modality.value;
      const secondaryValue = state.kind === "sessions" || state.kind === "dataAccess"
        ? row.context : row.qc;
      const matchesContext = !elements.context.value
        || secondaryValue === elements.context.value;
      return matchesSearch && matchesModality && matchesContext;
    });

    elements.headers.replaceChildren();
    columns.forEach(({ header }) => {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = header;
      elements.headers.append(cell);
    });

    elements.body.replaceChildren();
    state.visibleRows.forEach((row) => elements.body.append(renderRow(row, table, columns)));
    elements.status.value = `${state.visibleRows.length} of ${table.rows.length}`;
    elements.status.textContent = elements.status.value;
    elements.empty.hidden = state.visibleRows.length !== 0;
    updateDownloadLink();
  }

  function renderRow(row, table, columns) {
    const tableRow = document.createElement("tr");
    tableRow.className = `modality-${row.modality}`;
    columns.forEach(({ header, index }) => {
      const value = row.values[index];
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
      } else if (table.linkColumns?.includes(header)) {
        appendLinks(cell, value, header);
      } else {
        cell.textContent = value;
      }
      tableRow.append(cell);
    });
    return tableRow;
  }

  function visibleColumns(table) {
    const headers = state.kind === "dataAccess"
      ? table.columnViews[elements.modality.value]
      : table.headers;
    return headers.map((header) => ({ header, index: table.headers.indexOf(header) }));
  }

  function appendLinks(cell, value, header) {
    if (!value) return;
    String(value).split("\n").filter(Boolean).forEach((url, linkIndex) => {
      if (linkIndex) cell.append(document.createElement("br"));
      if (url === "INTERNAL") {
        const label = document.createElement("span");
        label.className = "internal-asset";
        label.textContent = "INTERNAL";
        cell.append(label);
        return;
      }
      const link = document.createElement("a");
      link.className = "asset-link";
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = header === "DANDI link" ? "Open on DANDI" : "Open S3 asset";
      cell.append(link);
    });
  }

  function setOptions(select, allLabel, values, labels = {}) {
    select.replaceChildren();
    if (allLabel !== null) select.append(new Option(allLabel, ""));
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
    const columns = visibleColumns(table);
    const csv = [
      columns.map(({ header }) => header),
      ...state.visibleRows.map((row) => columns.map(({ index }) => row.csvValues[index])),
    ]
      .map((row) => row.map(csvCell).join(","))
      .join("\n");
    elements.download.href = `data:text/csv;charset=utf-8,%EF%BB%BF${encodeURIComponent(csv)}`;
    const suffix = state.kind === "dataAccess"
      ? `${state.kind}-${elements.modality.value}` : state.kind;
    elements.download.download = `openscope-predictive-processing-${suffix}.csv`;
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
  selectView("interactive");
})();