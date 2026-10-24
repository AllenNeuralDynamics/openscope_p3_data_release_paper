function selectView(mode) {
            const staticView = document.getElementById('static-view');
            const interactiveView = document.getElementById('interactive-view');
            const buttons = document.querySelectorAll('.figure-mode-switch button');
            
            buttons.forEach(btn => btn.setAttribute('aria-pressed', 'false'));
            document.querySelector(`.figure-mode-switch button[data-view="${mode}"]`).setAttribute('aria-pressed', 'true');
            
            if (mode === 'static') {
                staticView.removeAttribute('hidden');
                interactiveView.setAttribute('hidden', '');
            } else {
                interactiveView.removeAttribute('hidden');
                staticView.setAttribute('hidden', '');
                if (rawData.length > 0) renderAll();
                setTimeout(() => {
                    window.dispatchEvent(new Event('resize'));
                    if (typeof Plotly !== 'undefined') {
                        document.querySelectorAll('.tab-content.active .plot-area').forEach(p => {
                            if (p && p.data) Plotly.Plots.resize(p);
                        });
                    }
                }, 60);
            }
        }

        function syncLegend() {
            const legend = document.getElementById('figure-legend');
            const toggle = document.getElementById('figure-legend-toggle');
            const isHidden = legend.hasAttribute('hidden');
            if (isHidden) {
                legend.removeAttribute('hidden');
                toggle.setAttribute('aria-expanded', 'true');
            } else {
                legend.setAttribute('hidden', '');
                toggle.setAttribute('aria-expanded', 'false');
            }
            toggle.focus();
        }

        document.addEventListener('keydown', (event) => {
            if (event.key === "Escape") {
                const legend = document.getElementById('figure-legend');
                if (!legend.hasAttribute('hidden')) {
                    syncLegend();
                }
            }
        });

        // Data Fetching
        let rawData = [], boundaryData = [], csdData = [], spectralData = [];

        function unpackUnits(unitsPayload) {
            if (!unitsPayload) return [];
            if (Array.isArray(unitsPayload)) return unitsPayload;
            const keys = Object.keys(unitsPayload);
            if (keys.length === 0) return [];
            const n = unitsPayload[keys[0]].length;
            const out = new Array(n);
            for (let i = 0; i < n; i++) {
                const row = {};
                for (let k = 0; k < keys.length; k++) {
                    const key = keys[k];
                    row[key] = unitsPayload[key][i];
                }
                out[i] = row;
            }
            return out;
        }

        async function fetchDashboardPayload(url) {
            const response = await fetch(url);
            if (!response.ok) throw new Error("HTTP " + response.status);
            const buffer = await response.arrayBuffer();
            const bytes = new Uint8Array(buffer);
            let jsonText;
            if (bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b) {
                if (typeof DecompressionStream === "undefined") {
                    throw new Error("Browser does not support DecompressionStream('gzip').");
                }
                const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
                jsonText = await new Response(stream).text();
            } else {
                jsonText = new TextDecoder("utf-8").decode(bytes);
            }
            return JSON.parse(jsonText);
        }

        fetchDashboardPayload('media/ecephys-qc-dashboard/ecephys-qc-dashboard.json.gz')
            .then(data => {
                rawData = unpackUnits(data.units);
                boundaryData = data.boundaries || [];
                csdData = data.csd || [];
                spectralData = data.psd || [];
                
                document.getElementById('loading-spinner').style.display = 'none';
                document.getElementById('main-ui').style.display = 'grid';
                
                initStaticCsd();
                if (rawData.length > 0) updateCascadingFilters();
            })
            .catch(error => {
                console.error("Error loading data:", error);
                document.getElementById('loading-spinner').innerHTML = "<b>Error: Could not load data payload.</b><br><br>Ensure <code>ecephys-qc-dashboard.json.gz</code> is staged in <code>media/ecephys-qc-dashboard/</code> and served over HTTP.";
                document.getElementById('loading-spinner').style.color = "#d1495b";
            });

        const corticalLayerOrder = ["1", "2", "2/3", "3", "4", "5", "6a", "6b"];
        const preferredDivisionOrder = ["Isocortex", "Hippocampal formation", "Thalamus", "Basal ganglia", "Other / unclassified"];
        const preferredGroupOrder = ["Visual cortex", "Motor cortex", "Medial frontal cortex", "Retrosplenial cortex", "Somatosensory cortex", "Auditory cortex", "Hippocampus", "Dentate gyrus", "Subicular complex", "Visual thalamus", "Striatum", "Other / unclassified"];
        const preferredFamilyOrder = ["VISp", "VISa", "VISrl", "VISl", "MOp", "MOs", "ACA", "PL", "ILA", "RSP", "Hippocampus", "LGd", "CP"];
        const PLOTLY_COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];
        let currentTab = 'tab-yield';

        const numericMetricNames = {
            'amplitude_cutoff': 'Amp Cutoff', 'isi_violations_ratio': 'ISI Violations',
            'presence_ratio': 'Presence Ratio', 'snr': 'SNR', 'firing_rate': 'Firing Rate (Hz)',
            'isolation_distance': 'Isolation Dist', 'd_prime': 'D-Prime', 'silhouette': 'Silhouette',
            'l_ratio': 'L-Ratio', 'amplitude': 'Amplitude (µV)', 'half_width': 'Half Width (ms)',
            'peak_to_valley': 'Peak-to-Valley (ms)', 'repolarization_slope': 'Repol Slope',
            'drift_ptp': 'Drift PtP (µm)', 'drift_std': 'Drift Std (µm)',
            'amplitude_cv_median': 'Amp CV Median',
            'depth_from_cortex_um': 'Depth from Cortical Entry (µm)',
            'depth_from_l1_l23_um': 'Depth from L1/L2/3 (µm)',
            'estimated_y': 'Est Y (µm)'
        };

        function safeLogVal(metric, val) {
            const logSafe = ['isi_violations_ratio', 'amplitude_cutoff', 'drift_ptp', 'drift_std', 'snr', 'firing_rate'];
            if (val === 0 && logSafe.includes(metric)) return 1e-6;
            return val;
        }

        const BASE_PLOTLY_CONFIG = { responsive: true, displayModeBar: true, displaylogo: false };

        function enhancePlotlyTooltips() {
            const tooltipMap = {
                'Zoom': 'Zoom (Click and drag to draw a bounding box)', 'Pan': 'Pan (Click and drag to move the plot)',
                'Zoom in': 'Zoom In (Click to zoom in)', 'Zoom out': 'Zoom Out (Click to zoom out)',
                'Autoscale': 'Autoscale (Double-click plot to reset)', 'Reset axes': 'Reset Axes (Double-click plot to reset)'
            };
            document.querySelectorAll('.modebar-btn').forEach(btn => {
                const title = btn.getAttribute('data-title');
                if (tooltipMap[title]) btn.setAttribute('data-title', tooltipMap[title]);
            });
        }

        const _csdDecodedCache = new Map();
        const _CSD_HEATMAP_DOMAIN_END = 0.70;
        const _CSD_ANATOMY_X0 = 0.715, _CSD_ANATOMY_X1 = 0.815, _CSD_ANATOMY_LABEL_X = 0.765, _CSD_COLORBAR_X = 0.93;
        const _CSD_PLOT_HEIGHT_PX = 580, _CSD_MIN_LABEL_HEIGHT_PX = 17;
        const STATIC_PSD_FMIN = 1.0, STATIC_PSD_FMAX = 200.0;

        const PARULA_COLORSCALE = [
            [0.0000, 'rgb(53,42,135)'], [0.0625, 'rgb(50,67,186)'], [0.1250, 'rgb(3,99,225)'], [0.1875, 'rgb(13,117,220)'], 
            [0.2500, 'rgb(20,133,212)'], [0.3125, 'rgb(9,152,209)'], [0.3750, 'rgb(6,167,198)'], [0.4375, 'rgb(21,177,180)'], 
            [0.5000, 'rgb(56,185,158)'], [0.5625, 'rgb(101,190,134)'], [0.6250, 'rgb(146,191,115)'], [0.6875, 'rgb(183,189,100)'], 
            [0.7500, 'rgb(217,186,86)'], [0.8125, 'rgb(248,187,68)'], [0.8750, 'rgb(252,206,46)'], [0.9375, 'rgb(245,228,29)'], 
            [1.0000, 'rgb(249,251,14)']
        ];

        const _CSD_BLUE_GREY_RED = [
            [0.00, 'rgb(5,48,97)'], [0.12, 'rgb(33,102,172)'], [0.27, 'rgb(103,169,207)'], [0.40, 'rgb(209,229,240)'], 
            [0.47, 'rgb(239,243,245)'], [0.50, 'rgb(250,250,250)'], [0.53, 'rgb(245,239,238)'], [0.60, 'rgb(253,219,199)'], 
            [0.73, 'rgb(239,138,98)'], [0.88, 'rgb(178,24,43)'], [1.00, 'rgb(103,0,31)']
        ];

        const _LFP_BLUE_GREY_RED = [
            [0.00, 'rgb(33,102,172)'], [0.20, 'rgb(103,169,207)'], [0.40, 'rgb(214,230,238)'], [0.50, 'rgb(250,250,250)'], 
            [0.60, 'rgb(242,221,215)'], [0.80, 'rgb(214,96,77)'], [1.00, 'rgb(178,24,43)']
        ];

        function finiteDepthOrNaN(value) {
            if (value === null || value === undefined || value === '') return NaN;
            const n = Number(value);
            return Number.isFinite(n) ? n : NaN;
        }

        function getCorticalBounds() {
            let maxCort = 2000, minL1 = -500, maxL1 = 2000, l1Found = false;
            function check(c, l) {
                if (Number.isFinite(c) && c > maxCort) maxCort = c;
                if (Number.isFinite(l)) {
                    if (!l1Found) { minL1 = l; maxL1 = l; l1Found = true; }
                    else { if (l < minL1) minL1 = l; if (l > maxL1) maxL1 = l; }
                }
            }
            for (let i = 0; i < rawData.length; i++) check(finiteDepthOrNaN(rawData[i].depth_from_cortex_um), finiteDepthOrNaN(rawData[i].depth_from_l1_l23_um));
            boundaryData.forEach(b => check(finiteDepthOrNaN(b.depth_from_cortex_um), finiteDepthOrNaN(b.depth_from_l1_l23_um)));
            return { maxCort, minL1, maxL1 };
        }

        function depthAxisForMode() {
            const bounds = getCorticalBounds(), DEPTH_TICK_UM = 250;
            if (depthAlignmentMode() === 'l1_l23') {
                let min_um = Math.floor(bounds.minL1 / DEPTH_TICK_UM) * DEPTH_TICK_UM;
                let max_um = Math.ceil(bounds.maxL1 / DEPTH_TICK_UM) * DEPTH_TICK_UM;
                if (max_um <= min_um) { min_um = -500; max_um = 2000; }
                return { title: 'Depth from superficial L1 ↔ L2/3 transition (µm; 0 = Boundary)', range: [max_um, min_um], tickmode: 'linear', tick0: 0, dtick: DEPTH_TICK_UM, zeroline: true, zerolinewidth: 2.2, zerolinecolor: '#111111' };
            }
            const c_max = Math.max(DEPTH_TICK_UM, Math.ceil(bounds.maxCort / DEPTH_TICK_UM) * DEPTH_TICK_UM);
            return { title: 'Depth from cortical entry (µm; 0 = Surface)', range: [c_max, 0], tickmode: 'linear', tick0: 0, dtick: DEPTH_TICK_UM, zeroline: true, zerolinewidth: 1.5, zerolinecolor: '#111111' };
        }

        function depthAlignmentMode() { return document.getElementById('depth-alignment').value; }
        function unitDisplayDepth(d) { return depthAlignmentMode() === 'l1_l23' ? finiteDepthOrNaN(d.depth_from_l1_l23_um) : finiteDepthOrNaN(d.depth_from_cortex_um); }
        function boundaryDisplayDepth(b) { return depthAlignmentMode() === 'l1_l23' ? finiteDepthOrNaN(b.depth_from_l1_l23_um) : finiteDepthOrNaN(b.depth_from_cortex_um); }

        let qcRules = [
            { id: 1, metric: 'isi_violations_ratio', op: '<', value: 0.01 }, { id: 2, metric: 'presence_ratio', op: '>', value: 0.90 },
            { id: 3, metric: 'amplitude_cutoff', op: '<', value: 0.10 }, { id: 4, metric: 'snr', op: '>=', value: 3.0 },
            { id: 5, metric: 'depth_from_cortex_um', op: '>=', value: 0.0 }
        ];
        let nextRuleId = 6;

        function renderQCRules() {
            const container = document.getElementById('qc-rules-container');
            container.innerHTML = '';
            qcRules.forEach(rule => {
                const row = document.createElement('div'); row.className = 'qc-dynamic-row';
                const metricSelect = `<select onchange="updateRule(${rule.id}, 'metric', this.value)">${Object.keys(numericMetricNames).map(m => `<option value="${m}" ${m===rule.metric?'selected':''}>${numericMetricNames[m]}</option>`).join('')}</select>`;
                const opSelect = `<select onchange="updateRule(${rule.id}, 'op', this.value)"><option value="<" ${rule.op==='<'?'selected':''}>&lt;</option><option value=">" ${rule.op==='>'?'selected':''}>&gt;</option><option value="<=" ${rule.op==='<='?'selected':''}>&le;</option><option value=">=" ${rule.op==='>='?'selected':''}>&ge;</option></select>`;
                row.innerHTML = `${metricSelect}${opSelect}<input type="number" step="any" value="${rule.value}" onchange="updateRule(${rule.id}, 'value', this.value)"><button title="Remove Filter" onclick="removeRule(${rule.id})">✖</button>`;
                container.appendChild(row);
            });
        }

        window.updateRule = function(id, field, value) { const rule = qcRules.find(r => r.id === id); if (rule) rule[field] = value; renderAll(); };
        window.removeRule = function(id) { qcRules = qcRules.filter(r => r.id !== id); renderQCRules(); renderAll(); };
        window.addRule = function() { qcRules.push({ id: nextRuleId++, metric: 'snr', op: '>', value: 3.0 }); renderQCRules(); renderAll(); };
        window.resetAllFilters = function() {
            qcRules = [
                { id: 1, metric: 'isi_violations_ratio', op: '<', value: 0.01 }, { id: 2, metric: 'presence_ratio', op: '>', value: 0.90 },
                { id: 3, metric: 'amplitude_cutoff', op: '<', value: 0.10 }, { id: 4, metric: 'snr', op: '>=', value: 3.0 },
                { id: 5, metric: 'depth_from_cortex_um', op: '>=', value: 0.0 }
            ];
            nextRuleId = 6; document.getElementById('qc-void').checked = true; renderQCRules();
            const selects = ['global-cohort', 'global-context', 'global-mouse', 'global-probe', 'global-division', 'global-group', 'global-family', 'global-subregion', 'global-layer', 'global-area', 'boundary-overlay', 'depth-alignment', 'color-scale-mode', 'target-metric', 'custom-x'];
            selects.forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    if (id === 'boundary-overlay') el.value = 'area_layers';
                    else if (id === 'depth-alignment') el.value = 'cortex_entry';
                    else if (id === 'color-scale-mode') el.value = 'shared';
                    else if (id === 'target-metric') el.value = 'snr';
                    else if (id === 'custom-x') el.value = 'depth_from_cortex_um';
                    else el.value = 'All';
                }
            });
            const lx = document.getElementById('log-x-axis'); if (lx) lx.checked = false;
            const ly = document.getElementById('log-y-axis'); if (ly) ly.checked = false;
            updateCascadingFilters(); 
        };

        renderQCRules();

        function setSelectOptions(selectId, values, allLabel, preferredOrder=null) {
            const el = document.getElementById(selectId);
            const current = el.value;
            el.innerHTML = `<option value="All">${allLabel}</option>`;
            let arr = [...values].filter(v => v != null && String(v).trim() !== '');
            if (preferredOrder) {
                const rank = new Map(preferredOrder.map((v, i) => [v, i]));
                arr.sort((a,b) => {
                    const ra = rank.has(a) ? rank.get(a) : 999;
                    const rb = rank.has(b) ? rank.get(b) : 999;
                    return ra !== rb ? ra-rb : String(a).localeCompare(String(b));
                });
            } else arr.sort((a,b) => String(a).localeCompare(String(b), undefined, {numeric:true}));
            arr.forEach(v => el.add(new Option(v, v)));
            el.value = arr.includes(current) ? current : 'All';
        }

        function updateCascadingFilters() {
            if (!rawData.length) return;
            const cohort = document.getElementById('global-cohort').value;
            const context = document.getElementById('global-context').value;
            const base = rawData.filter(d => (cohort === 'All' || d.cohort === cohort) && (context === 'All' || d.context === context));
            setSelectOptions('global-mouse', new Set(base.map(d => d.mouse_id)), 'All Mice');
            setSelectOptions('global-division', new Set(base.map(d => d.major_division)), 'All Major Divisions', preferredDivisionOrder);
            const division = document.getElementById('global-division').value;
            const divisionData = base.filter(d => division === 'All' || d.major_division === division);
            setSelectOptions('global-group', new Set(divisionData.map(d => d.region_group)), 'All Region Groups', preferredGroupOrder);
            const group = document.getElementById('global-group').value;
            const groupData = divisionData.filter(d => group === 'All' || d.region_group === group);
            setSelectOptions('global-family', new Set(groupData.map(d => d.area_family)), 'All Areas', preferredFamilyOrder);
            const family = document.getElementById('global-family').value;
            const familyData = groupData.filter(d => family === 'All' || d.area_family === family);
            setSelectOptions('global-subregion', new Set(familyData.map(d => d.subarea)), 'All Subareas / Subfields');
            const subregion = document.getElementById('global-subregion').value;
            const subData = familyData.filter(d => subregion === 'All' || d.subarea === subregion);
            setSelectOptions('global-layer', new Set(subData.map(d => d.layer_or_compartment)), 'All Layers / Compartments', corticalLayerOrder);
            const layer = document.getElementById('global-layer').value;
            const layerData = subData.filter(d => layer === 'All' || d.layer_or_compartment === layer);
            setSelectOptions('global-area', new Set(layerData.map(d => d.ccf_acronym || d.area)), 'All Exact CCF Acronyms');
            renderAll();
        }

        function getFilteredData(options = {}) {
            const ignoreContext = Boolean(options.ignoreContext);
            const mouse = document.getElementById('global-mouse').value;
            const cohort = document.getElementById('global-cohort').value;
            const context = document.getElementById('global-context').value;
            const probe = document.getElementById('global-probe').value;
            const division = document.getElementById('global-division').value;
            const group = document.getElementById('global-group').value;
            const family = document.getElementById('global-family').value;
            const subregion = document.getElementById('global-subregion').value;
            const layer = document.getElementById('global-layer').value;
            const area = document.getElementById('global-area').value;
            const excludeVoid = document.getElementById('qc-void').checked;

            return rawData.filter(d => {
                for(let rule of qcRules) {
                    const val = d[rule.metric];
                    if (val == null) return false;
                    const num = parseFloat(rule.value);
                    if (isNaN(num)) continue;
                    if (rule.op === '<' && !(val < num)) return false;
                    if (rule.op === '>' && !(val > num)) return false;
                    if (rule.op === '<=' && !(val <= num)) return false;
                    if (rule.op === '>=' && !(val >= num)) return false;
                }
                if (excludeVoid && d.area === 'void') return false;
                const cleanProbe = probe === 'All' ? 'All' : probe.split(' ')[0];
                return (mouse === 'All' || d.mouse_id === mouse) &&
                       (cohort === 'All' || d.cohort === cohort) &&
                       (ignoreContext || context === 'All' || d.context === context) &&
                       (cleanProbe === 'All' || d.probe === cleanProbe) &&
                       (division === 'All' || d.major_division === division) &&
                       (group === 'All' || d.region_group === group) &&
                       (family === 'All' || d.area_family === family) &&
                       (subregion === 'All' || d.subarea === subregion) &&
                       (layer === 'All' || d.layer_or_compartment === layer) &&
                       (area === 'All' || (d.ccf_acronym || d.area) === area);
            });
        }

        function median(values) {
            if (!values.length) return null;
            const x = [...values].sort((a,b)=>a-b);
            const mid = Math.floor(x.length/2);
            return x.length % 2 ? x[mid] : (x[mid-1] + x[mid]) / 2;
        }

        function robustPercentile(values, q=0.99) {
            const clean = values.map(Number).filter(Number.isFinite).sort((a,b)=>a-b);
            if (!clean.length) return 1;
            const idx = Math.min(clean.length - 1, Math.max(0, Math.floor((clean.length - 1) * q)));
            return (Number.isFinite(clean[idx]) && clean[idx] > 0) ? clean[idx] : 1;
        }

        function getColorScaleMode() { return document.getElementById('color-scale-mode').value; }
        function scaleModeLabel() { return getColorScaleMode() === 'shared' ? 'shared across contexts' : 'autoscaled to context'; }

        function sharedScalarMetricVmax(metric, fallbackValues=[]) {
            if (getColorScaleMode() !== 'shared') return robustPercentile(fallbackValues, 0.99);
            const reference = getFilteredData({ignoreContext: true});
            const vals = reference.map(d => Number(d[metric])).filter(Number.isFinite);
            return robustPercentile(vals.length ? vals : fallbackValues, 0.99);
        }

        function sharedTimeSeriesVmax(fallbackValues=[]) {
            if (getColorScaleMode() !== 'shared') return robustPercentile(fallbackValues, 0.98);
            const reference = getFilteredData({ignoreContext: true});
            const vals = [];
            reference.forEach(d => {
                if (Array.isArray(d.fr_time_series)) d.fr_time_series.forEach(v => { const n = Number(v); if (Number.isFinite(n)) vals.push(n); });
            });
            return robustPercentile(vals.length ? vals : fallbackValues, 0.98);
        }

        function anatomyOverlayMode() { return document.getElementById('boundary-overlay').value; }
        function isLayerBoundary(b) { return String(b.boundary_type || '').toLowerCase() === 'layer'; }
        function boundariesForDisplay(bounds, multiMouse=false) {
            const mode = anatomyOverlayMode();
            if (mode === 'off') return [];
            if (mode === 'area_only' || multiMouse) return bounds.filter(b => !isLayerBoundary(b));
            return bounds;
        }

        function anatomyBoundaryLineStyle(b) {
            const layer = isLayerBoundary(b);
            return layer ? { color: 'rgba(115,115,115,0.42)', width: 1.0, dash: 'dash' } : { color: 'rgba(75,75,75,0.68)', width: 1.8, dash: 'dash' };
        }

        function relevantBoundaries(mouse=null) {
            if (anatomyOverlayMode() === 'off') return [];
            const probe = document.getElementById('global-probe').value;
            if (probe === 'All') return [];
            const cohort = document.getElementById('global-cohort').value;
            const context = document.getElementById('global-context').value;
            return boundaryData.filter(b => b.probe === probe && (mouse == null || b.mouse_id === mouse) && (cohort === 'All' || b.cohort === cohort) && (context === 'All' || b.context === context));
        }

        function aggregateBoundaryRecords(records) {
            const groups = new Map();
            records.forEach(b => {
                const key = `${b.boundary_type}|${b.boundary_label}|${b.from_area}|${b.to_area}`;
                if (!groups.has(key)) groups.set(key, []);
                groups.get(key).push(b);
            });
            return [...groups.entries()].map(([key, rows]) => {
                const r0 = rows[0];
                return {
                    depth_from_cortex_um: median(rows.map(r => Number(r.depth_from_cortex_um)).filter(Number.isFinite)),
                    depth_from_l1_l23_um: median(rows.map(r => Number(r.depth_from_l1_l23_um)).filter(Number.isFinite)),
                    boundary_type: r0.boundary_type, boundary_label: r0.boundary_label, from_area: r0.from_area, to_area: r0.to_area,
                    n_sessions: new Set(rows.map(r => r.session_key)).size,
                    state_from: { major_division: r0.from_major_division, region_group: r0.from_region_group, area_family: r0.from_area_family, subarea: r0.from_subarea, layer: r0.from_layer, compartment: r0.from_compartment },
                    state_to: { major_division: r0.to_major_division, region_group: r0.to_region_group, area_family: r0.to_area_family, subarea: r0.to_subarea, layer: r0.to_layer, compartment: r0.to_compartment }
                };
            }).filter(b => (depthAlignmentMode() === 'l1_l23' ? b.depth_from_l1_l23_um : b.depth_from_cortex_um) != null).sort((a,b) => (depthAlignmentMode() === 'l1_l23' ? a.depth_from_l1_l23_um - b.depth_from_l1_l23_um : a.depth_from_cortex_um - b.depth_from_cortex_um));
        }

        function compactAreaName(state) {
            if (!state) return '';
            const all = `${state.major_division || ''} ${state.region_group || ''} ${state.area_family || ''} ${state.subarea || ''}`.toLowerCase();
            if (all.includes('hippocamp') || all.includes('dentate') || all.includes('subiculum')) return 'Hippocampus';
            if (all.includes('thalam') || all.includes('lgd')) return 'Thalamus';
            if (all.includes('striat') || all.includes('caudoputamen') || /(^|\s)cp($|\s)/.test(all)) return 'Striatum';
            if (all.includes('isocortex') || all.includes('visual cortex') || all.includes('motor cortex') || all.includes('retrosplenial')) return 'Cortex';
            if (all.includes('midbrain') || all.includes('superior colliculus')) return 'Midbrain';
            if (all.includes('white matter') || all.includes('fiber tract')) return 'White matter';
            return '';
        }

        function compactLayerName(state) {
            if (!state) return '';
            if (state.layer) return `L${String(state.layer).trim()}`;
            return state.compartment ? String(state.compartment).trim() : '';
        }

        function mergeAdjacentSegments(segments, labelFn) {
            const out = [];
            segments.forEach(seg => {
                const label = labelFn(seg.state);
                if (!label) return;
                const prev = out[out.length - 1];
                if (prev && prev.label === label && Math.abs(prev.high - seg.low) < 1e-6) prev.high = seg.high;
                else out.push({low: seg.low, high: seg.high, label});
            });
            return out;
        }

        function boundsForCurrentDepthMode(bounds) {
            return bounds.map(b => ({...b, display_depth: boundaryDisplayDepth(b)})).filter(b => Number.isFinite(Number(b.display_depth))).sort((a,b) => a.display_depth - b.display_depth);
        }

        function anatomySegmentsFromBounds(bounds, yMin, yMax) {
            if (!bounds.length) return {areaSegments: [], layerSegments: []};
            const sorted = bounds, segments = [];
            let low = yMin, state = sorted[0].state_from;
            sorted.forEach(b => {
                const high = Math.max(yMin, Math.min(yMax, Number(b.display_depth)));
                if (high > low) segments.push({low, high, state});
                low = high; state = b.state_to;
            });
            if (low < yMax) segments.push({low, high: yMax, state});
            return { areaSegments: mergeAdjacentSegments(segments, compactAreaName), layerSegments: mergeAdjacentSegments(segments, compactLayerName) };
        }

        function applyPreservedZoom(graphId, layout, currentXKey, currentYKey) {
            const graphDiv = document.getElementById(graphId);
            if (graphDiv && graphDiv.layout && graphDiv.dataset.xKey === currentXKey && graphDiv.dataset.yKey === currentYKey) {
                if (graphDiv.layout.xaxis && graphDiv.layout.xaxis.autorange === false && graphDiv.layout.xaxis.range) {
                    if(!layout.xaxis) layout.xaxis = {};
                    layout.xaxis.range = graphDiv.layout.xaxis.range; layout.xaxis.autorange = false;
                }
                if (graphDiv.layout.yaxis && graphDiv.layout.yaxis.autorange === false && graphDiv.layout.yaxis.range) {
                    if(!layout.yaxis) layout.yaxis = {};
                    layout.yaxis.range = graphDiv.layout.yaxis.range; layout.yaxis.autorange = false;
                }
            }
            if (graphDiv) { graphDiv.dataset.xKey = currentXKey; graphDiv.dataset.yKey = currentYKey; }
        }

        function renderYield() {
            document.getElementById('context-group').style.display = 'flex';
            const data = getFilteredData();
            document.getElementById('unit-count').textContent = `Total Units Displayed: ${data.length.toLocaleString()}`;
            if(data.length === 0) { Plotly.react('plot-yield', [], {title: 'No Data Available'}, BASE_PLOTLY_CONFIG); return; }

            const mice = [...new Set(data.map(d => d.mouse_id))].sort();
            const probes = ["ProbeA", "ProbeB", "ProbeC", "ProbeD", "ProbeE", "ProbeF"];
            const colors = ['#0072B2', '#E69F00', '#009E73', '#CC79A7', '#56B4E9', '#D55E00'];
            const traces = probes.map((probe, i) => {
                const counts = mice.map(mouse => data.filter(d => d.mouse_id === mouse && d.probe === probe).length);
                return { x: mice, y: counts, name: probe, type: 'bar', marker: { color: colors[i] } };
            });
            const layout = { title: 'QC-Passed Unit Yield by Mouse and Probe', barmode: 'stack', xaxis: { title: 'Mouse ID', type: 'category' }, yaxis: { title: 'Number of Units' } };
            applyPreservedZoom('plot-yield', layout, 'yield', 'yield');
            Plotly.react('plot-yield', traces, layout, BASE_PLOTLY_CONFIG).then(() => enhancePlotlyTooltips());
        }

        function renderECDF() {
            document.getElementById('context-group').style.display = 'none';
            document.getElementById('global-context').value = 'All';

            const data = getFilteredData();
            const metric = document.getElementById('target-metric').value;
            const firstData = data.filter(d => d.session_stage === 'First' && d[metric] != null).map(d => safeLogVal(metric, d[metric])).sort((a,b)=>a-b);
            const lastData = data.filter(d => d.session_stage === 'Last' && d[metric] != null).map(d => safeLogVal(metric, d[metric])).sort((a,b)=>a-b);
            const buildCumulative = arr => ({ x: arr, y: arr.map((_, i) => (i + 1) / arr.length * 100) });
            const trFirst = buildCumulative(firstData), trLast = buildCumulative(lastData);

            const traces = [
                { x: trFirst.x, y: trFirst.y, mode: 'lines', line: {shape: 'hv', width: 3, color: '#0072B2'}, name: 'First Session' },
                { x: trLast.x, y: trLast.y, mode: 'lines', line: {shape: 'hv', width: 3, color: '#D55E00'}, name: 'Last Session' }
            ];
            const useLogX = document.getElementById('log-x-axis') && document.getElementById('log-x-axis').checked;
            const layout = { title: `Degradation Analysis: ${numericMetricNames[metric]||metric}`, xaxis: { title: numericMetricNames[metric]||metric, type: useLogX ? 'log' : 'linear' }, yaxis: { title: 'Cumulative % of Units', range: [0, 100] } };
            
            applyPreservedZoom('plot-ecdf', layout, metric, 'cumulative');
            Plotly.react('plot-ecdf', traces, layout, BASE_PLOTLY_CONFIG).then(() => enhancePlotlyTooltips());
            document.getElementById('unit-count').textContent = `Total Units Displayed: ${(firstData.length + lastData.length).toLocaleString()} (First/Last stages only)`;
        }

        function renderDepth() {
            document.getElementById('context-group').style.display = 'flex';
            let spatialMetric = 'depth_from_cortex_um';
            const targetMet = document.getElementById('target-metric').value;
            if (targetMet === 'estimated_y' || targetMet === 'depth_from_cortex_um' || targetMet === 'depth_from_l1_l23_um') spatialMetric = targetMet;
            const isDepthMode = (spatialMetric === 'depth_from_cortex_um' || spatialMetric === 'depth_from_l1_l23_um');

            let data = getFilteredData();
            if (isDepthMode) data = data.map(d => ({...d, _display_depth: unitDisplayDepth(d)})).filter(d => Number.isFinite(d._display_depth));
            else data = data.filter(d => d[spatialMetric] != null);
            
            document.getElementById('unit-count').textContent = `Total Units Displayed: ${data.length.toLocaleString()}`;
            if(data.length === 0) {
                const msg = (isDepthMode && depthAlignmentMode() === 'l1_l23') ? 'No valid L1 ↔ L2/3 reference for these filters' : `No ${numericMetricNames[spatialMetric]||spatialMetric} Data Available`;
                Plotly.react('plot-depth', [], {title: msg}, BASE_PLOTLY_CONFIG); return;
            }

            const metric = document.getElementById('target-metric').value, binSize = 50;
            let minDepth, maxDepth;
            if (isDepthMode) {
                if (depthAlignmentMode() === 'l1_l23') { minDepth = -500; maxDepth = 2000; }
                else { minDepth = 0; maxDepth = 4000; }
            } else {
                let minVal = Infinity, maxVal = -Infinity;
                for(let i=0; i<data.length; i++) {
                    const v = Number(data[i][spatialMetric]);
                    if(Number.isFinite(v)) { if(v < minVal) minVal = v; if(v > maxVal) maxVal = v; }
                }
                minDepth = Math.floor(minVal / binSize) * binSize; maxDepth = Math.ceil(maxVal / binSize) * binSize;
            }

            const yBins = [];
            for(let d = minDepth; d <= maxDepth; d += binSize) yBins.push(d);
            if (yBins.length < 2) { Plotly.react('plot-depth', [], {title: 'Not enough spatial variation'}, BASE_PLOTLY_CONFIG); return; }

            const mice = [...new Set(data.map(d => d.mouse_id))].sort();
            const zMatrix = Array(yBins.length - 1).fill(0).map(() => Array(mice.length).fill(null));

            mice.forEach((mouse, m_idx) => {
                const mouseData = data.filter(d => d.mouse_id === mouse && d[metric] != null);
                for(let b_idx = 0; b_idx < yBins.length - 1; b_idx++) {
                    const binData = mouseData.filter(d => (isDepthMode ? d._display_depth : d[spatialMetric]) >= yBins[b_idx] && (isDepthMode ? d._display_depth : d[spatialMetric]) < yBins[b_idx+1]);
                    if(binData.length > 0) zMatrix[b_idx][m_idx] = binData.reduce((sum, d) => sum + d[metric], 0) / binData.length;
                }
            });

            const hoverText = zMatrix.map((row, b_idx) => {
                return row.map((val, m_idx) => {
                    const v = val !== null ? val.toFixed(3) : 'No Data';
                    return `Mouse: ${mice[m_idx]}<br>${isDepthMode ? (depthAlignmentMode() === 'l1_l23' ? 'Depth from L1/L2/3' : 'Depth from Surface') : (numericMetricNames[spatialMetric]||spatialMetric)}: ${yBins[b_idx]}–${yBins[b_idx+1]} µm<br>Mean ${numericMetricNames[metric]||metric}: ${v}`;
                });
            });

            const flatZ = [];
            for(let i=0; i<zMatrix.length; i++) { for(let j=0; j<zMatrix[i].length; j++) { if(zMatrix[i][j] !== null) flatZ.push(zMatrix[i][j]); } }
            const vmax = sharedScalarMetricVmax(metric, flatZ);
            const trace = {
                z: zMatrix, x: mice, y: yBins.slice(0, -1).map(y => y + binSize/2), type: 'heatmap', colorscale: PARULA_COLORSCALE, zmin: 0, zmax: vmax, hoverongaps: false,
                text: hoverText, hoverinfo: 'text', colorbar: { title: {text: `Mean ${numericMetricNames[metric]||metric} · ${scaleModeLabel()}`, side: 'bottom'}, orientation: 'h', x: 0.5, y: -0.18, yanchor: 'top', len: 0.62, thickness: 14 }
            };

            const layout = { title: `Depth Profile Heatmap: ${numericMetricNames[metric]||metric}`, xaxis: { title: 'Mouse ID', type: 'category' }, yaxis: isDepthMode ? depthAxisForMode() : { title: numericMetricNames[spatialMetric]||spatialMetric, autorange: 'reversed' }};

            if (isDepthMode && document.getElementById('global-probe').value !== 'All') {
                layout.shapes = []; layout.annotations = [];
                mice.forEach(mouse => {
                    const allBoundsRaw = aggregateBoundaryRecords(relevantBoundaries(mouse));
                    const allBounds = boundsForCurrentDepthMode(allBoundsRaw);
                    const bounds = boundariesForDisplay(allBounds, mice.length > 1);
                    if (!bounds.length) return;
                    if (mice.length === 1) {
                        bounds.forEach(b => layout.shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: b.display_depth, y1: b.display_depth, line: anatomyBoundaryLineStyle(b), layer: 'above' }));
                        const anatomy = anatomySegmentsFromBounds(allBounds, minDepth, maxDepth);
                        layout.annotations.push({ xref: 'paper', x: 1.025, yref: 'paper', y: 1.02, text: '<b>Area</b>', showarrow: false, xanchor: 'left', font: {size: 11, color: '#555'} });
                        if (anatomyOverlayMode() === 'area_layers') layout.annotations.push({ xref: 'paper', x: 1.145, yref: 'paper', y: 1.02, text: '<b>Layer</b>', showarrow: false, xanchor: 'left', font: {size: 11, color: '#555'} });
                        anatomy.areaSegments.forEach(seg => {
                            if ((seg.high - seg.low) < 35) return;
                            layout.annotations.push({ xref: 'paper', x: 1.025, yref: 'y', y: (seg.low + seg.high)/2, text: `<b>${seg.label}</b>`, showarrow: false, xanchor: 'left', yanchor: 'middle', font: {size: 11, color: '#444'}, bgcolor: 'rgba(255,255,255,0.92)', bordercolor: '#ddd', borderwidth: 0.5 });
                        });
                        if (anatomyOverlayMode() === 'area_layers') {
                            anatomy.layerSegments.forEach(seg => {
                                if ((seg.high - seg.low) < 35) return;
                                layout.annotations.push({ xref: 'paper', x: 1.145, yref: 'y', y: (seg.low + seg.high)/2, text: seg.label, showarrow: false, xanchor: 'left', yanchor: 'middle', font: {size: 10, color: '#666'}, bgcolor: 'rgba(255,255,255,0.90)', bordercolor: '#e3e3e3', borderwidth: 0.5 });
                            });
                        }
                    }
                });
                layout.margin = layout.annotations.length ? { l: 75, r: anatomyOverlayMode() === 'area_layers' ? 190 : 120, t: 85, b: 115 } : { l: 75, r: 40, t: 85, b: 115 };
            } else layout.margin = { l: 75, r: 40, t: 85, b: 115 };

            applyPreservedZoom('plot-depth', layout, 'mouse', spatialMetric);
            Plotly.react('plot-depth', [trace], layout, BASE_PLOTLY_CONFIG).then(() => enhancePlotlyTooltips());
        }

        function renderLayerProfile() {
            document.getElementById('context-group').style.display = 'flex';
            const family = document.getElementById('global-family').value, metric = document.getElementById('target-metric').value, plotDiv = document.getElementById('plot-layers');
            if (family === 'All') {
                Plotly.purge(plotDiv);
                plotDiv.innerHTML = '<div class="warning-box"><b>Select an Area.</b><br><br>Use the biological hierarchy in the sidebar (e.g. Isocortex → Visual cortex → VISp).</div>';
                document.getElementById('unit-count').textContent = 'Total Units Displayed: 0'; return;
            }
            if (plotDiv.querySelector('.warning-box')) plotDiv.innerHTML = '';

            const data = getFilteredData().filter(d => d[metric] != null);
            document.getElementById('unit-count').textContent = `Total Units Displayed: ${data.length.toLocaleString()}`;
            if (!data.length) { Plotly.react('plot-layers', [], {title: 'No data for selected anatomy'}, BASE_PLOTLY_CONFIG); return; }

            const isHippo = family === 'Hippocampus', isLGd = family === 'LGd', hasCorticalLayers = data.some(d => d.anatomy_class === 'cortical' && d.layer != null && String(d.layer).trim() !== '');
            let xOrder = [], xField = 'layer', xTitle = 'Cortical layer', xFormatter = x => `L${x}`;

            if (isHippo) {
                xField = 'subarea'; xTitle = 'Hippocampal CA subfield'; xFormatter = x => x;
                const present = [...new Set(data.map(d => d.subarea).filter(x => x != null))], hipOrder = ['CA1','CA2','CA3'];
                xOrder = hipOrder.filter(x => present.includes(x)).concat(present.filter(x => !hipOrder.includes(x)).sort());
            } else if (hasCorticalLayers) {
                const present = new Set(data.map(d => d.layer).filter(x => x != null));
                xOrder = corticalLayerOrder.filter(x => present.has(x));
            } else {
                xField = 'subarea'; xTitle = isLGd ? 'LGd subdivision' : 'Subarea / subfield'; xFormatter = x => x;
                const present = [...new Set(data.map(d => d.subarea).filter(x => x != null))];
                xOrder = present.sort((a,b)=>String(a).localeCompare(String(b), undefined, {numeric:true}));
            }

            const subareas = [...new Set(data.map(d => d.subarea).filter(x => x != null))].sort(), traces = [], grouped = (hasCorticalLayers && subareas.length > 1 && !isHippo) ? subareas : [null];

            grouped.forEach(sub => {
                const subData = sub == null ? data : data.filter(d => d.subarea === sub), means = [], counts = [];
                xOrder.forEach(x => {
                    const rows = subData.filter(d => d[xField] === x && d[metric] != null);
                    counts.push(rows.length);
                    means.push(rows.length ? rows.reduce((acc,d)=>acc + Number(d[metric]),0)/rows.length : null);
                });
                traces.push({
                    x: xOrder.map(xFormatter), y: means, type: 'bar', name: sub == null ? family : sub, text: counts.map(n => `n=${n}`),
                    hovertemplate: `%{x}<br>Mean ${numericMetricNames[metric]||metric}: %{y:.3f}<br>%{text}<extra>${sub == null ? family : sub}</extra>`
                });
            });

            const selectedGroup = document.getElementById('global-group').value, hierarchyPrefix = selectedGroup === 'All' ? family : `${selectedGroup} → ${family}`, profileLevel = isHippo ? 'CA subfield' : (hasCorticalLayers ? 'cortical layer' : 'subarea'), layerShapes = [];
            for (let i = 0; i < xOrder.length; i++) {
                if (i % 2 === 0) layerShapes.push({ type: 'rect', xref: 'paper', x0: i / xOrder.length, x1: (i + 1) / xOrder.length, yref: 'paper', y0: 0, y1: 1, fillcolor: 'rgba(0,0,0,0.025)', line: { width: 0 }, layer: 'below' });
                if (i > 0) layerShapes.push({ type: 'line', xref: 'paper', x0: i / xOrder.length, x1: i / xOrder.length, yref: 'paper', y0: 0, y1: 1, line: { color: '#000000', width: 1.5, dash: 'dash' }, layer: 'above' });
            }

            const layerAnnotations = [], selectedMouse = document.getElementById('global-mouse').value, selectedProbe = document.getElementById('global-probe').value;
            if (hasCorticalLayers && selectedMouse !== 'All' && selectedProbe !== 'All') {
                const physicalLayerBounds = aggregateBoundaryRecords(relevantBoundaries(selectedMouse)).filter(b => b.boundary_type === 'layer').sort((a,b) => (depthAlignmentMode() === 'l1_l23' ? a.depth_from_l1_l23_um - b.depth_from_l1_l23_um : a.depth_from_cortex_um - b.depth_from_cortex_um));
                if (physicalLayerBounds.length) {
                    const boundaryText = physicalLayerBounds.slice(0, 10).map(b => `${b.boundary_label} @ ${(depthAlignmentMode() === 'l1_l23' ? b.depth_from_l1_l23_um : b.depth_from_cortex_um).toFixed(0)} µm`).join(' &nbsp;•&nbsp; ');
                    layerAnnotations.push({ xref: 'paper', x: 0, yref: 'paper', y: 1.16, text: `<b>Probe-specific CCF layer boundaries:</b> ${boundaryText}`, showarrow: false, xanchor: 'left', align: 'left', bgcolor: '#ffffff', bordercolor: '#000000', borderwidth: 1, borderpad: 4, opacity: 1, font: { size: 10, color: '#000000', family: 'Arial, sans-serif' } });
                }
            }

            const layout = { title: `${hierarchyPrefix}: ${numericMetricNames[metric]||metric} by ${profileLevel}`, xaxis: { title: xTitle, categoryorder: 'array', categoryarray: xOrder.map(xFormatter) }, yaxis: { title: `Mean ${numericMetricNames[metric]||metric}` }, barmode: grouped.length > 1 ? 'group' : 'relative', shapes: layerShapes, annotations: layerAnnotations, margin: layerAnnotations.length ? { l: 60, r: 35, t: 125, b: 60 } : { l: 60, r: 35, t: 80, b: 60 } };
            applyPreservedZoom('plot-layers', layout, 'layers', metric);
            Plotly.react('plot-layers', traces, layout, BASE_PLOTLY_CONFIG).then(() => enhancePlotlyTooltips());
        }

        function renderTimeSeries() {
            document.getElementById('context-group').style.display = 'flex';
            const mouse = document.getElementById('global-mouse').value, context = document.getElementById('global-context').value, plotDiv = document.getElementById('plot-timeseries');
            if (mouse === 'All' || context === 'All') {
                Plotly.purge(plotDiv);
                plotDiv.innerHTML = '<div class="warning-box"><b>Please select a specific Mouse ID and Context.</b></div>';
                document.getElementById('unit-count').textContent = 'Total Units Displayed: 0'; return;
            }
            if (plotDiv.querySelector('.warning-box')) plotDiv.innerHTML = '';

            let spatialMetric = 'depth_from_cortex_um';
            const targetMet = document.getElementById('target-metric').value;
            if (targetMet === 'estimated_y' || targetMet === 'depth_from_cortex_um' || targetMet === 'depth_from_l1_l23_um') spatialMetric = targetMet;
            const isDepthMode = (spatialMetric === 'depth_from_cortex_um' || spatialMetric === 'depth_from_l1_l23_um');

            let data = getFilteredData().filter(d => d.fr_time_series && d.fr_time_series.length > 0);
            if (isDepthMode) data = data.map(d => ({...d, _display_depth: unitDisplayDepth(d)})).filter(d => Number.isFinite(d._display_depth));
            else data = data.filter(d => d[spatialMetric] != null);
            document.getElementById('unit-count').textContent = `Total Units Displayed: ${data.length.toLocaleString()}`;
            if (data.length === 0) { Plotly.react('plot-timeseries', [], {title: 'No Time-Series Data Available'}, BASE_PLOTLY_CONFIG); return; }

            const binSize = 50;
            let minDepth, maxDepth;
            if (isDepthMode) {
                if (depthAlignmentMode() === 'l1_l23') { minDepth = -500; maxDepth = 2000; }
                else { minDepth = 0; maxDepth = 4000; }
            } else {
                let minVal = Infinity, maxVal = -Infinity;
                for(let i=0; i<data.length; i++) {
                    const v = Number(data[i][spatialMetric]);
                    if(Number.isFinite(v)) { if(v < minVal) minVal = v; if(v > maxVal) maxVal = v; }
                }
                minDepth = Math.floor(minVal / binSize) * binSize; maxDepth = Math.ceil(maxVal / binSize) * binSize;
            }

            const yBins = [];
            for(let d = minDepth; d <= maxDepth; d += binSize) yBins.push(d);

            let maxBins = 0;
            for(let i=0; i<data.length; i++) { if(data[i].fr_time_series.length > maxBins) maxBins = data[i].fr_time_series.length; }

            const xBins = Array.from({length: maxBins}, (_, i) => i + 0.5), zMatrix = Array(yBins.length - 1).fill(0).map(() => Array(maxBins).fill(null));
            for(let b_idx = 0; b_idx < yBins.length - 1; b_idx++) {
                const binData = data.filter(d => (isDepthMode ? d._display_depth : d[spatialMetric]) >= yBins[b_idx] && (isDepthMode ? d._display_depth : d[spatialMetric]) < yBins[b_idx+1]);
                if(binData.length > 0) {
                    for(let t = 0; t < maxBins; t++) {
                        let sum = 0, count = 0;
                        binData.forEach(d => { if(t < d.fr_time_series.length) { sum += d.fr_time_series[t]; count++; } });
                        zMatrix[b_idx][t] = count > 0 ? sum / count : null;
                    }
                }
            }

            const vmax = sharedTimeSeriesVmax(zMatrix.flat());
            const trace = { z: zMatrix, x: xBins, y: yBins.slice(0, -1).map(y => y + binSize/2), type: 'heatmap', colorscale: PARULA_COLORSCALE, zmin: 0, zmax: vmax, colorbar: { title: 'Mean Firing Rate (Hz)' } };
            const layout = { title: `Within-Session Firing Rate: Mouse ${mouse} | ${context}`, xaxis: { title: 'Time (Minutes)', range: [0, maxBins] }, yaxis: isDepthMode ? depthAxisForMode() : { title: numericMetricNames[spatialMetric]||spatialMetric, autorange: 'reversed' }, margin: { l: 60 } };

            if (isDepthMode && document.getElementById('global-probe').value !== 'All') {
                layout.shapes = []; layout.annotations = [];
                const allBoundsRaw = aggregateBoundaryRecords(relevantBoundaries(mouse)), allBounds = boundsForCurrentDepthMode(allBoundsRaw), bounds = boundariesForDisplay(allBounds, false);
                bounds.forEach(b => layout.shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: b.display_depth, y1: b.display_depth, line: anatomyBoundaryLineStyle(b), layer: 'above' }));
                const anatomy = anatomySegmentsFromBounds(allBounds, minDepth, maxDepth);
                layout.annotations.push({ xref: 'paper', x: 1.015, yref: 'paper', y: 1.02, text: '<b>Area</b>', showarrow: false, xanchor: 'left', font: {size: 11, color: '#555'} });
                anatomy.areaSegments.forEach(seg => {
                    if ((seg.high - seg.low) < 35) return;
                    layout.annotations.push({ xref: 'paper', x: 1.015, yref: 'y', y: (seg.low + seg.high)/2, text: `<b>${seg.label}</b>`, showarrow: false, xanchor: 'left', yanchor: 'middle', font: {size: 10, color: '#444'}, bgcolor: 'rgba(255,255,255,0.92)', bordercolor: '#ddd', borderwidth: 0.5 });
                });
                if (anatomyOverlayMode() === 'area_layers') {
                    layout.annotations.push({ xref: 'paper', x: 1.115, yref: 'paper', y: 1.02, text: '<b>Layer</b>', showarrow: false, xanchor: 'left', font: {size: 11, color: '#555'} });
                    anatomy.layerSegments.forEach(seg => {
                        if ((seg.high - seg.low) < 35) return;
                        layout.annotations.push({ xref: 'paper', x: 1.115, yref: 'y', y: (seg.low + seg.high)/2, text: seg.label, showarrow: false, xanchor: 'left', yanchor: 'middle', font: {size: 10, color: '#666'}, bgcolor: 'rgba(255,255,255,0.90)', bordercolor: '#e3e3e3', borderwidth: 0.5 });
                    });
                }
                layout.margin = { l: 60, r: anatomyOverlayMode() === 'area_layers' ? 180 : 120, t: 80 };
            }

            applyPreservedZoom('plot-timeseries', layout, 'time', spatialMetric);
            Plotly.react('plot-timeseries', [trace], layout, BASE_PLOTLY_CONFIG).then(() => enhancePlotlyTooltips());
        }

        function renderCustom() {
            document.getElementById('context-group').style.display = 'flex';
            const xMet = document.getElementById('custom-x').value, yMet = document.getElementById('target-metric').value;
            const data = getFilteredData().filter(d => d[xMet] != null && d[yMet] != null);
            document.getElementById('unit-count').textContent = `Total Units Displayed: ${data.length.toLocaleString()}`;

            const buildTrace = (dGroup, name, color) => ({
                x: dGroup.map(d => safeLogVal(xMet, d[xMet])), y: dGroup.map(d => safeLogVal(yMet, d[yMet])),
                mode: 'markers', type: 'scattergl', name: name, marker: { color: color, size: 4, opacity: 0.5 },
                text: dGroup.map(d => `Mouse: ${d.mouse_id}<br>Probe: ${d.probe}<br>Area: ${d.ccf_acronym || d.area}`), hoverinfo: 'x+y+text'
            });

            const traces = [buildTrace(data.filter(d => d.cohort === 'Motor'), 'Motor', '#0072B2'), buildTrace(data.filter(d => d.cohort === 'Sequence'), 'Sequence', '#D55E00')].filter(t => t.x.length > 0);
            const useLogX = document.getElementById('log-x-axis') && document.getElementById('log-x-axis').checked, useLogY = document.getElementById('log-y-axis') && document.getElementById('log-y-axis').checked;
            const layout = { title: `${numericMetricNames[yMet]||yMet} vs ${numericMetricNames[xMet]||xMet}`, xaxis: { title: numericMetricNames[xMet]||xMet, type: useLogX ? 'log' : 'linear' }, yaxis: { title: numericMetricNames[yMet]||yMet, type: useLogY ? 'log' : 'linear' } };
            
            if (yMet === 'depth_from_cortex_um' || yMet === 'depth_from_l1_l23_um') layout.yaxis.autorange = 'reversed';
            if (xMet === 'depth_from_cortex_um' || xMet === 'depth_from_l1_l23_um') layout.xaxis.autorange = 'reversed';

            applyPreservedZoom('plot-custom', layout, xMet, yMet);
            Plotly.react('plot-custom', traces, layout, BASE_PLOTLY_CONFIG).then(() => enhancePlotlyTooltips());
        }

        function _csdUnique(values) { return [...new Set(values.filter(v => v !== null && v !== undefined && String(v) !== ''))].sort((a,b)=>String(a).localeCompare(String(b))); }
        function _csdSetOptions(id, values, labels=null) {
            const el=document.getElementById(id); if (!el) return;
            const old=el.value; el.innerHTML='';
            values.forEach((v,i)=>{ const o=document.createElement('option'); o.value=String(v); o.textContent=labels?labels[i]:String(v); el.appendChild(o); });
            if(values.map(String).includes(old)) el.value=old;
        }

        function _decodeInt16Matrix(rec, kind) {
            const key=[rec.session_key,rec.probe,rec.stim_table,rec.condition,kind].join('|');
            if(_csdDecodedCache.has(key)) return _csdDecodedCache.get(key);
            const b64 = kind==='lfp' ? rec.lfp_b64 : rec.csd_b64, scale = Number(kind==='lfp' ? rec.lfp_scale : rec.csd_scale), binary=atob(b64), bytes=new Uint8Array(binary.length);
            for(let i=0;i<binary.length;i++) bytes[i]=binary.charCodeAt(i);
            const view=new DataView(bytes.buffer), nrow=rec.shape[0], ncol=rec.shape[1], out=[];
            let k=0;
            for(let r=0;r<nrow;r++) {
                const row=new Array(ncol);
                for(let c=0;c<ncol;c++,k++) { const q=view.getInt16(k*2,true); row[c]=(q===-32768)?null:q*scale; }
                out.push(row);
            }
            _csdDecodedCache.set(key,out); return out;
        }

        function _csdFiniteAbs(z) { const a=[]; z.forEach(row=>row.forEach(v=>{ if(v!==null && Number.isFinite(Number(v))) a.push(Math.abs(Number(v))); })); return a; }
        function _csdRobustLimit(z) { const a=_csdFiniteAbs(z).sort((x,y)=>x-y); if(!a.length) return 1; return a[Math.min(a.length-1,Math.floor(0.99*(a.length-1)))] || 1; }
        function _csdMedian(a) { const x=a.filter(Number.isFinite).slice().sort((u,v)=>u-v); if(!x.length) return NaN; const m=Math.floor(x.length/2); return x.length%2 ? x[m] : 0.5*(x[m-1]+x[m]); }
        function _csdMad(a) { const med=_csdMedian(a); if(!Number.isFinite(med)) return NaN; return _csdMedian(a.filter(Number.isFinite).map(v=>Math.abs(v-med))); }

        function _csdSessionRecords() { const s=document.getElementById('csd-session').value; return csdData.filter(d=>String(d.session_key)===String(s)); }
        function _csdProbeRecords() { const p=document.getElementById('csd-probe').value; return _csdSessionRecords().filter(d=>String(d.probe)===String(p)); }
        function _csdStimRecords() { const st=document.getElementById('csd-stim').value; return _csdProbeRecords().filter(d=>String(d.stim_table)===String(st)); }
        function _csdCurrentRecord() { const cond=document.getElementById('csd-condition').value; return _csdStimRecords().find(d=>String(d.condition)===String(cond)); }
        function _csdRefreshProbe() { const r=_csdSessionRecords(); _csdSetOptions('csd-probe',_csdUnique(r.map(d=>d.probe))); _csdRefreshStim(); }
        function _csdRefreshStim() { const r=_csdProbeRecords(); _csdSetOptions('csd-stim',_csdUnique(r.map(d=>d.stim_table))); _csdRefreshCondition(); }
        function _csdRefreshCondition() { const r=_csdStimRecords(); const vals=_csdUnique(r.map(d=>d.condition)); vals.sort((a,b)=>a==='All'?-1:b==='All'?1:String(a).localeCompare(String(b))); _csdSetOptions('csd-condition',vals); renderStaticCsd(); }

        function _csdAlignedDepth(rec) {
            let offset=0, note=''; const mode=document.getElementById('csd-align').value;
            if(mode==='cortex') {
                if(rec.cortex_entry_probe_depth_um===null || !Number.isFinite(Number(rec.cortex_entry_probe_depth_um))) note='Cortical-entry landmark unavailable for this probe; showing probe-top coordinates.';
                else offset=Number(rec.cortex_entry_probe_depth_um);
            } else if(mode==='l1') {
                if(rec.l1_l23_probe_depth_um===null || !Number.isFinite(Number(rec.l1_l23_probe_depth_um))) note='L1↔L2/3 landmark unavailable for this probe; showing probe-top coordinates.';
                else offset=Number(rec.l1_l23_probe_depth_um);
            }
            return {y:rec.depth_probe_um.map(v=>Number(v)-offset),offset,note};
        }

        function _csdNormLabel(label) { return String(label || '').trim().toLowerCase().replace(/\s+/g,''); }
        function _csdCorticalLayer(label) {
            const s=_csdNormLabel(label).replace(/layer/g,'').replace(/2-3/g,'2/3').replace(/2_3/g,'2/3');
            if(/2\/3$/.test(s)) return '2/3'; if(/6a$/.test(s)) return '6a'; if(/6b$/.test(s)) return '6b';
            if(/4$/.test(s)) return '4'; if(/5$/.test(s)) return '5'; if(/6$/.test(s)) return '6'; if(/1$/.test(s)) return '1';
            return null;
        }
        function _csdCorticalArea(label) { return _csdNormLabel(label).replace(/layer/g,'').replace(/2-3/g,'2/3').replace(/2_3/g,'2/3').replace(/(2\/3|6a|6b|1|4|5|6)$/,''); }
        function _csdHippInfo(label) {
            const s=_csdNormLabel(label).replace(/_/g,'-'); let m=s.match(/^(ca[123])[-]?(so|sp|sr|slm)$/);
            if(m) { const names={so:'oriens',sp:'pyramidal',sr:'radiatum',slm:'lacunosum-moleculare'}; return {region:m[1].toUpperCase(),stratum:m[2],display:m[1].toUpperCase()+' '+names[m[2]]}; }
            if(s.includes('stratumoriens')) return {region:'CA',stratum:'so',display:'CA stratum oriens'};
            if(s.includes('stratumpyramidale') || s.includes('pyramidallayer')) return {region:'CA',stratum:'sp',display:'CA pyramidal layer'};
            if(s.includes('stratumradiatum')) return {region:'CA',stratum:'sr',display:'CA stratum radiatum'};
            if(s.includes('lacunosum') || s.includes('slm')) return {region:'CA',stratum:'slm',display:'CA lacunosum-moleculare'};
            if(/^dg[-]?(mo|mol)$/.test(s)) return {region:'DG',stratum:'mo',display:'DG molecular'};
            if(/^dg[-]?(sg|sgz)$/.test(s)) return {region:'DG',stratum:'sg',display:'DG granule'};
            if(/^dg[-]?(po|pol)$/.test(s)) return {region:'DG',stratum:'po',display:'DG polymorphic'};
            return null;
        }

        function _csdIsVisualSpan(sp) { const rg=String(sp.region_group || '').trim().toLowerCase(), lab=String(sp.label || '').trim().toLowerCase(); return rg==='visual cortex' || /^vis/.test(lab) || lab.includes('visual'); }
        function _csdIsHippSpan(sp) { const md=String(sp.major_division || '').trim().toLowerCase(), lab=String(sp.label || '').trim().toLowerCase(); return md.includes('hippocamp') || /^ca[123]/.test(lab) || /^dg/.test(lab) || _csdHippInfo(lab)!==null; }

        function _csdBoundaryClass(prev,curr) {
            const prevCtx=String(prev.anatomy_class || '').toLowerCase()==='cortical', currCtx=String(curr.anatomy_class || '').toLowerCase()==='cortical';
            if(prevCtx && currCtx) {
                const l0=_csdCorticalLayer(prev.label), l1=_csdCorticalLayer(curr.label), a0=_csdCorticalArea(prev.label), a1=_csdCorticalArea(curr.label);
                if(l0 && l1 && a0 && a0===a1) { if((l0==='2/3' && l1==='4') || (l0==='4' && l1==='2/3')) return 'l23-l4'; if((l0==='4' && l1==='5') || (l0==='5' && l1==='4')) return 'l4-l5'; }
            }
            const h0=_csdHippInfo(prev.label), h1=_csdHippInfo(curr.label);
            if(h0 && h1 && h0.stratum!==h1.stratum) { if(h0.region===h1.region || h0.region==='CA' || h1.region==='CA') return 'hipp-stratum'; }
            return 'generic';
        }

        function _csdDepthInSpans(depth,spans) { return spans.some(sp=>{ const lo=Math.min(Number(sp.z0),Number(sp.z1)), hi=Math.max(Number(sp.z0),Number(sp.z1)); return depth>=lo && depth<=hi; }); }

        function _csdEarlyVisualSink(rec,csd,x,y,offset,ymin,ymax) {
            const vis=(rec.anatomy_spans||[]).filter(_csdIsVisualSpan).map(sp=>({z0:Number(sp.z0)-offset,z1:Number(sp.z1)-offset,label:sp.label}));
            if(!vis.length) return null;
            const rows=[];
            for(let r=0;r<y.length;r++) { const yy=Number(y[r]); if(yy>=ymin && yy<=ymax && _csdDepthInSpans(yy,vis)) rows.push(r); }
            if(rows.length<2) return null;
            const rowSet=new Set(rows), early=[], base=[];
            for(let c=0;c<x.length;c++) { const t=Number(x[c]); if(t>=20 && t<=120) early.push(c); if(t>=-100 && t<0) base.push(c); }
            if(!early.length) return null;
            const baseline=[];
            rows.forEach(r=>base.forEach(c=>{ const v=csd[r][c]; if(v!==null && Number.isFinite(Number(v))) baseline.push(Number(v)); }));
            const bm=_csdMedian(baseline), bmed=Number.isFinite(bm)?bm:0, mad=_csdMad(baseline), sigma=Number.isFinite(mad) && mad>0 ? 1.4826*mad : NaN;
            const minima=early.map(c=>{ let best=Infinity,bestRow=-1; rows.forEach(r=>{ const v=csd[r][c]; if(v!==null && Number.isFinite(Number(v)) && Number(v)<best) {best=Number(v);bestRow=r;} }); return {c,best,bestRow}; }).filter(d=>d.bestRow>=0 && Number.isFinite(d.best));
            if(!minima.length) return null;
            let onset=null;
            if(Number.isFinite(sigma) && sigma>0) { const threshold=bmed-4.0*sigma; onset=minima.find(d=>d.best<=threshold)||null; }
            let candidates=minima, confidence='exploratory';
            if(onset) { const t0=Number(x[onset.c]); candidates=minima.filter(d=>Number(x[d.c])>=t0 && Number(x[d.c])<=t0+35); confidence='thresholded'; }
            const peak=candidates.reduce((a,b)=>b.best<a.best?b:a,candidates[0]);
            if(!peak || peak.best>=0) return null;
            const snr=(Number.isFinite(sigma) && sigma>0)?Math.abs(peak.best-bmed)/sigma:NaN;
            if(Number.isFinite(snr) && snr<3.0) return null;
            const peakRow=peak.bestRow, peakCol=peak.c, peakY=Number(y[peakRow]), peakT=Number(x[peakCol]), peakVal=Number(peak.best), halfLevel=0.5*peakVal;
            let lo=peakRow, hi=peakRow;
            while(lo-1>=0 && rowSet.has(lo-1)) { const v=csd[lo-1][peakCol]; if(v===null || !Number.isFinite(Number(v)) || Number(v)>halfLevel) break; lo--; }
            while(hi+1<y.length && rowSet.has(hi+1)) { const v=csd[hi+1][peakCol]; if(v===null || !Number.isFinite(Number(v)) || Number(v)>halfLevel) break; hi++; }
            let bandTop=Number(y[lo]), bandBottom=Number(y[hi]);
            if(lo>0) bandTop=0.5*(Number(y[lo-1])+Number(y[lo]));
            if(hi<y.length-1) bandBottom=0.5*(Number(y[hi])+Number(y[hi+1]));
            if(bandTop>bandBottom) [bandTop,bandBottom]=[bandBottom,bandTop];
            const width=bandBottom-bandTop, bandValid=Number.isFinite(width) && width>=20 && width<=400;
            const l4Spans=(rec.anatomy_spans||[]).filter(sp=>_csdIsVisualSpan(sp) && _csdCorticalLayer(sp.label)==='4').map(sp=>({z0:Number(sp.z0)-offset,z1:Number(sp.z1)-offset,label:String(sp.label||'L4')}));
            let ccfL4=null;
            if(l4Spans.length) { const containing=l4Spans.find(sp=>peakY>=Math.min(sp.z0,sp.z1) && peakY<=Math.max(sp.z0,sp.z1)); ccfL4=containing || l4Spans.slice().sort((a,b)=>Math.abs(peakY-0.5*(a.z0+a.z1))-Math.abs(peakY-0.5*(b.z0+b.z1)))[0]; }
            let deltaToCcfL4Center=NaN;
            if(ccfL4) deltaToCcfL4Center=peakY-0.5*(ccfL4.z0+ccfL4.z1);
            return { peakY,peakT,peakVal,snr,confidence, bandTop:bandValid?bandTop:null, bandBottom:bandValid?bandBottom:null, ccfL4,deltaToCcfL4Center };
        }

        function _csdBuildOverlay(rec,offset,ymin,ymax,physiology=null) {
            const shapes=[], annotations=[], spans=(rec.anatomy_spans||[]).slice().sort((a,b)=>Number(a.z0)-Number(b.z0)), visibleSpan=Math.max(1,Math.abs(ymax-ymin)), minLabelHeightUm=visibleSpan * (_CSD_MIN_LABEL_HEIGHT_PX / _CSD_PLOT_HEIGHT_PX);
            let labelsShown=0, labelsTotal=0;
            spans.forEach((sp,i)=>{
                const z0=Number(sp.z0)-offset, z1=Number(sp.z1)-offset, lo=Math.min(z0,z1), hi=Math.max(z0,z1);
                if(hi<ymin || lo>ymax) return;
                const clippedLo=Math.max(lo,ymin), clippedHi=Math.min(hi,ymax), mid=0.5*(clippedLo+clippedHi), spanHeight=Math.max(0,clippedHi-clippedLo), fill=(i%2===0) ? 'rgba(247,247,247,0.98)' : 'rgba(235,235,235,0.98)';
                shapes.push({ type:'rect', xref:'paper', x0:_CSD_ANATOMY_X0, x1:_CSD_ANATOMY_X1, yref:'y', y0:clippedLo, y1:clippedHi, fillcolor:fill, line:{ color:'rgba(120,120,120,0.34)', width:0.7 }, layer:'above' });
                if(i>0) {
                    const boundary=lo;
                    if(boundary>=ymin && boundary<=ymax) {
                        const cls=_csdBoundaryClass(spans[i-1],sp);
                        let line={ color:'rgba(90,90,90,0.30)', width:0.9, dash:'solid' };
                        if(cls==='l23-l4' || cls==='l4-l5') line={ color:'rgba(15,15,15,0.95)', width:2.6, dash:'solid' };
                        else if(cls==='hipp-stratum') line={ color:'rgba(25,25,25,0.86)', width:2.0, dash:'dash' };
                        shapes.push({ type:'line', xref:'paper', x0:0, x1:_CSD_ANATOMY_X1, yref:'y', y0:boundary, y1:boundary, line:line, layer:'above' });
                    }
                }
                labelsTotal += 1;
                if(spanHeight>=minLabelHeightUm) { annotations.push({ xref:'paper', x:_CSD_ANATOMY_LABEL_X, yref:'y', y:mid, text:String(sp.label||''), showarrow:false, xanchor:'center', yanchor:'middle', align:'center', bgcolor:'rgba(255,255,255,0)', borderwidth:0, font:{ size:9, color:'#3f3f3f' } }); labelsShown += 1; }
            });
            annotations.push({ xref:'paper', x:0.5*(_CSD_ANATOMY_X0+_CSD_ANATOMY_X1), yref:'paper', y:1.035, text:'<b>CCF anatomy</b>', showarrow:false, xanchor:'center', yanchor:'bottom', font:{size:10,color:'#444'} });
            if(physiology) {
                if(physiology.bandTop!==null && physiology.bandBottom!==null) {
                    shapes.push({ type:'rect', xref:'paper', x0:0, x1:_CSD_HEATMAP_DOMAIN_END, yref:'y', y0:physiology.bandTop, y1:physiology.bandBottom, fillcolor:'rgba(33,102,172,0.10)', line:{width:0}, layer:'below' });
                    [physiology.bandTop,physiology.bandBottom].forEach(z=>{ shapes.push({ type:'line', xref:'paper', x0:0, x1:_CSD_HEATMAP_DOMAIN_END, yref:'y', y0:z, y1:z, line:{ color:'rgba(33,102,172,0.78)', width:1.4, dash:'dot' }, layer:'above' }); });
                    shapes.push({ type:'rect', xref:'paper', x0:_CSD_ANATOMY_X0, x1:_CSD_ANATOMY_X1, yref:'y', y0:physiology.bandTop, y1:physiology.bandBottom, fillcolor:'rgba(33,102,172,0.06)', line:{ color:'rgba(33,102,172,0.82)', width:1.4, dash:'dot' }, layer:'above' });
                }
                shapes.push({ type:'line', xref:'paper', x0:0, x1:_CSD_HEATMAP_DOMAIN_END, yref:'y', y0:physiology.peakY, y1:physiology.peakY, line:{ color:'rgba(33,102,172,0.98)', width:2.7, dash:'dashdot' }, layer:'above' });
                shapes.push({ type:'line', xref:'paper', x0:_CSD_ANATOMY_X0, x1:_CSD_ANATOMY_X1, yref:'y', y0:physiology.peakY, y1:physiology.peakY, line:{ color:'rgba(33,102,172,1.0)', width:2.7, dash:'dashdot' }, layer:'above' });
            }
            return { shapes, annotations, labelsShown, labelsTotal };
        }

        function _csdVisibleRange(rec,offset,y) {
            let ymin=Math.min(...y),ymax=Math.max(...y),note='';
            const view=document.getElementById('csd-view').value;
            if(view==='visual') {
                const vis=(rec.anatomy_spans||[]).filter(_csdIsVisualSpan);
                if(vis.length) { ymin=Math.min(...vis.map(sp=>Math.min(Number(sp.z0)-offset,Number(sp.z1)-offset))); ymax=Math.max(...vis.map(sp=>Math.max(Number(sp.z0)-offset,Number(sp.z1)-offset))); }
                else note=' No visual-cortex CCF span on this probe; full depth shown.';
            }
            if(view==='hipp') {
                const hip=(rec.anatomy_spans||[]).filter(_csdIsHippSpan);
                if(hip.length) { ymin=Math.min(...hip.map(sp=>Math.min(Number(sp.z0)-offset,Number(sp.z1)-offset))); ymax=Math.max(...hip.map(sp=>Math.max(Number(sp.z0)-offset,Number(sp.z1)-offset))); }
                else note=' No recognised hippocampal CCF span on this probe; full depth shown.';
            }
            return {ymin,ymax,note};
        }

        function _spectralCurrentRecord() { const s=document.getElementById('csd-session').value, p=document.getElementById('csd-probe').value; return spectralData.find( d => String(d.session_key)===String(s) && String(d.probe)===String(p) ); }
        function _spectralBandNames(rec) { if(!rec || !rec.band_profiles) return []; return Object.keys(rec.band_profiles); }
        function _spectralEnsureBandOptions() {
            const rec = _spectralCurrentRecord(), el = document.getElementById('csd-band'), cbList = document.getElementById('band-checkbox-list');
            if (!el || !cbList) return;
            if (!rec) { el.innerHTML = ''; const o = document.createElement('option'); o.value = ''; o.textContent = 'No spectral record'; el.appendChild(o); cbList.innerHTML = '<div>No spectral record</div>'; return; }
            const names = _spectralBandNames(rec), old = el.value, current = [...el.options].map(o => o.value), same = current.length === names.length && current.every((v, i) => v === names[i]);
            if (!same) {
                el.innerHTML = '';
                names.forEach(name => { const o = document.createElement('option'); o.value = name; o.textContent = name; el.appendChild(o); });
                if (names.includes(old)) el.value = old; else if (names.includes('Hipp theta 6–10 Hz')) el.value = 'Hipp theta 6–10 Hz'; else if (names.length) el.value = names[0];
                const oldChecked = Array.from(cbList.querySelectorAll('.band-cb:checked')).map(cb => cb.value);
                cbList.innerHTML = '';
                names.forEach((name, i) => {
                    const color = PLOTLY_COLORS[i % PLOTLY_COLORS.length], div = document.createElement('div');
                    div.style.display = 'flex'; div.style.alignItems = 'center'; div.style.gap = '8px';
                    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.className = 'band-cb'; cb.value = name; cb.dataset.color = color; cb.id = 'cb-band-' + i;
                    if (oldChecked.length > 0) cb.checked = oldChecked.includes(name); else cb.checked = (name === el.value);
                    cb.addEventListener('change', renderStaticSpectral);
                    const colorBox = document.createElement('div'); colorBox.style.width = '12px'; colorBox.style.height = '12px'; colorBox.style.flexShrink = '0'; colorBox.style.backgroundColor = color; colorBox.style.borderRadius = '2px';
                    const lbl = document.createElement('label'); lbl.htmlFor = cb.id; lbl.textContent = name; lbl.style.fontSize = '0.8rem'; lbl.style.cursor = 'pointer'; lbl.style.userSelect = 'none'; lbl.style.lineHeight = '1.2'; lbl.style.whiteSpace = 'normal';
                    div.appendChild(cb); div.appendChild(colorBox); div.appendChild(lbl); cbList.appendChild(div);
                });
            }
        }

        function _spectralFiniteValues(z) { const out=[]; (z||[]).forEach(row=>{ (row||[]).forEach(v=>{ const x=Number(v); if(Number.isFinite(x)) out.push(x); }); }); return out; }
        function _spectralQuantile(a,q) { const x=(a||[]).filter(Number.isFinite).slice().sort((u,v)=>u-v); if(!x.length) return NaN; const pos=(x.length-1)*q, lo=Math.floor(pos), hi=Math.ceil(pos); if(lo===hi) return x[lo]; return x[lo]*(hi-pos)+x[hi]*(pos-lo); }
        function _spectralBandRangeShape(profile,ymin,ymax) { if(!profile) return null; if(!Number.isFinite(Number(profile.f0)) || !Number.isFinite(Number(profile.f1))) return null; return { type:'rect', xref:'x', x0:Number(profile.f0), x1:Number(profile.f1), yref:'y', y0:ymin, y1:ymax, fillcolor:'rgba(60,60,60,0.07)', line:{ color:'rgba(60,60,60,0.35)', width:1, dash:'dot' }, layer:'above' }; }

        function renderStaticSpectral() {
            if(currentTab!=='tab-csd') return;
            const rec=_spectralCurrentRecord(), status=document.getElementById('spectral-status');
            if(!rec) { if(status) status.textContent='No cached long-window spectral record for this session/probe.'; Plotly.purge('plot-static-psd'); Plotly.purge('plot-static-band'); return; }
            _spectralEnsureBandOptions();
            const al=_csdAlignedDepth(rec), y=al.y, vr=_csdVisibleRange(rec,al.offset,y), ymin=vr.ymin, ymax=vr.ymax, anatomy=_csdBuildOverlay(rec,al.offset,ymin,ymax,null), freq=(rec.freq_hz||[]).map(Number), psd=rec.psd_db||[], allVals=_spectralFiniteValues(psd);
            let zmin=_spectralQuantile(allVals,0.03), zmax=_spectralQuantile(allVals,0.97);
            if(!Number.isFinite(zmin)) zmin=-100; if(!Number.isFinite(zmax)) zmax=-20; if(zmax<=zmin) zmax=zmin+1;
            const bandName=document.getElementById('csd-band').value, profile=rec.band_profiles ? rec.band_profiles[bandName] : null, bandShape=_spectralBandRangeShape(profile,ymin,ymax);
            if(status) { const bandTxt=bandName ? ` · selected ${bandName}` : ''; status.innerHTML= `<b>${rec.session_key} · ${rec.probe}</b> · ${rec.n_windows} × ${Number(rec.window_seconds).toFixed(1)} s windows · ${rec.source_mode} · source LFP ${Number(rec.sampling_rate_hz).toFixed(1)} Hz${bandTxt}${al.note?' · <b>'+al.note+'</b>':''}${vr.note||''}`; }
            const common={ yaxis:{ title:document.getElementById('csd-align').selectedOptions[0].text, range:[ymax,ymin], automargin:true }, margin:{l:82,r:52,t:48,b:60}, hovermode:'closest' }, psdShapes=[...anatomy.shapes];
            if(bandShape) psdShapes.push(bandShape);
            Plotly.react('plot-static-psd', [{ type:'heatmap', x:freq, y:y, z:psd, colorscale:'Viridis', zmin:zmin, zmax:zmax, colorbar:{ title:{text:'dB/Hz',side:'right'}, x:_CSD_COLORBAR_X, xanchor:'center', len:0.88, thickness:15 }, hovertemplate:'f=%{x:.1f} Hz<br>depth=%{y:.0f} µm<br>PSD=%{z:.2f} dB/Hz<extra></extra>' }], { ...common, xaxis:{ title:'Frequency (Hz)', domain:[0,_CSD_HEATMAP_DOMAIN_END], range:[STATIC_PSD_FMIN,STATIC_PSD_FMAX] }, shapes:psdShapes, annotations:anatomy.annotations, title:{ text:'LFP power spectrum by depth', font:{size:16} } }, BASE_PLOTLY_CONFIG).then(() => enhancePlotlyTooltips());
            
            const checkedCbs = Array.from(document.querySelectorAll('.band-cb:checked'));
            if(checkedCbs.length === 0) { Plotly.purge('plot-static-band'); return; }
            const metricEl = document.getElementById('csd-band-metric'), metric = (metricEl && metricEl.value === 'absolute') ? 'absolute' : 'relative';
            const traces = []; let allRatios = true, anyRatios = false;
            checkedCbs.forEach(cb => {
                const bName = cb.value, color = cb.dataset.color, p = rec.band_profiles[bName];
                if(!p) return;
                const isRatio = String(p.unit) === 'ratio';
                if(isRatio) anyRatios = true; else allRatios = false;
                const valueArray = isRatio ? p.values : (metric === 'absolute' ? (p.values_absolute_db || p.values) : (p.values_relative || p.values));
                if(!Array.isArray(valueArray)) return;
                const vals = valueArray.map(v => { const x = Number(v); return Number.isFinite(x) ? x : null; });
                traces.push({ type: 'scatter', mode: 'lines+markers', x: vals, y: y, name: bName, line: { color: color, width: 2 }, marker: { color: color, size: 5 }, hovertemplate: `${bName}<br>depth=%{y:.0f} µm<br>` + (isRatio ? 'ratio=%{x:.3f}' : (metric === 'absolute' ? 'absolute power=%{x:.2f} dB mV²' : 'relative power=%{x:.2f}%')) + '<extra></extra>' });
            });
            if(traces.length === 0) { Plotly.purge('plot-static-band'); return; }
            let xTitle = 'Power';
            if(allRatios) xTitle = 'Power ratio'; else if(anyRatios) xTitle = 'Power / Ratio'; else xTitle = (metric === 'absolute' ? 'Absolute band power (dB mV²)' : 'Relative band power (% of 1–200 Hz)');
            Plotly.react('plot-static-band', traces, { ...common, xaxis: { title: xTitle, domain: [0, _CSD_HEATMAP_DOMAIN_END], rangemode: 'tozero', zeroline: true, zerolinecolor: '#bbb' }, shapes: anatomy.shapes, annotations: anatomy.annotations, title: { text: traces.length === 1 ? traces[0].name : 'Selected spectral bands', font: { size: 16 } }, showlegend: false }, BASE_PLOTLY_CONFIG).then(() => enhancePlotlyTooltips());
        }

        function renderStaticCsd() {
            if(currentTab!=='tab-csd') return;
            const rec=_csdCurrentRecord(), status=document.getElementById('csd-status');
            if(!rec) { status.textContent='No embedded LFP/CSD record matches these selectors.'; Plotly.purge('plot-static-lfp'); Plotly.purge('plot-static-csd'); Plotly.purge('plot-static-psd'); Plotly.purge('plot-static-band'); return; }
            const lfp=_decodeInt16Matrix(rec,'lfp'), csd=_decodeInt16Matrix(rec,'csd'), al=_csdAlignedDepth(rec), y=al.y, x=rec.time_ms.map(Number), vr=_csdVisibleRange(rec,al.offset,y), ymin=vr.ymin, ymax=vr.ymax, physiology=_csdEarlyVisualSink(rec,csd,x,y,al.offset,ymin,ymax), anatomyOverlay=_csdBuildOverlay(rec,al.offset,ymin,ymax,null), csdOverlay=_csdBuildOverlay(rec,al.offset,ymin,ymax,physiology), finitePct=(100*Number(rec.csd_finite_fraction||0)).toFixed(1);
            let physText='';
            if(physiology) {
                const snrTxt=Number.isFinite(physiology.snr)?` · baseline SNR≈${physiology.snr.toFixed(1)}`:'', bandTxt=(physiology.bandTop!==null && physiology.bandBottom!==null)?` · half-peak band ${physiology.bandTop.toFixed(0)}–${physiology.bandBottom.toFixed(0)} µm`:'', deltaTxt=Number.isFinite(physiology.deltaToCcfL4Center)?` · Δ vs CCF L4 centre ${physiology.deltaToCcfL4Center>=0?'+':''}${physiology.deltaToCcfL4Center.toFixed(0)} µm`:'';
                physText=`<br><b>Physiology:</b> early visual sink at ${physiology.peakT.toFixed(1)} ms, depth ${physiology.peakY.toFixed(0)} µm${snrTxt}${bandTxt}${deltaTxt}. Sink centre is an L4 landmark; band edges are heuristic.`;
            }
            const labelTxt=csdOverlay.labelsShown<csdOverlay.labelsTotal ? ` · CCF anatomy track ${csdOverlay.labelsShown}/${csdOverlay.labelsTotal} labels shown (thin spans remain visible but text is suppressed)` : ` · CCF anatomy track ${csdOverlay.labelsShown} labels`;
            status.innerHTML=`<b>${rec.session_key} · ${rec.probe}</b> &nbsp; ${rec.stim_table} &nbsp; ${rec.group_by?rec.group_by+': ':''}${rec.condition}<br>${rec.n_trials} trials · source LFP ${Number(rec.sampling_rate_hz).toFixed(1)} Hz · displayed ${rec.shape[0]} depth × ${rec.shape[1]} time bins · CSD: ${rec.csd_mode} · finite ${finitePct}%${labelTxt}${al.note?' · <b>'+al.note+'</b>':''}${vr.note}${physText}`;
            const common={ xaxis:{title:'Time from stimulus onset (ms)',zeroline:true,zerolinewidth:1.5,zerolinecolor:'#111',domain:[0,_CSD_HEATMAP_DOMAIN_END]}, yaxis:{title:document.getElementById('csd-align').selectedOptions[0].text,range:[ymax,ymin],automargin:true}, margin:{l:82,r:52,t:48,b:58}, hovermode:'closest' }, onsetLine={type:'line',xref:'x',x0:0,x1:0,yref:'y',y0:ymin,y1:ymax,line:{color:'#111',width:1.3}}, llim=_csdRobustLimit(lfp), clim=_csdRobustLimit(csd);
            Plotly.react('plot-static-lfp',[{type:'heatmap',x:x,y:y,z:lfp,colorscale:_LFP_BLUE_GREY_RED,reversescale:false,zmid:0,zmin:-llim,zmax:llim,colorbar:{title:{text:'mV',side:'right'},x:_CSD_COLORBAR_X,xanchor:'center',len:0.88,thickness:15},hovertemplate:'t=%{x:.1f} ms<br>depth=%{y:.0f} µm<br>LFP=%{z:.4g} mV<extra></extra>'}],{...common,shapes:[...anatomyOverlay.shapes,onsetLine],annotations:anatomyOverlay.annotations,title:{text:'Stimulus-triggered LFP',font:{size:16}}},BASE_PLOTLY_CONFIG).then(() => enhancePlotlyTooltips());
            Plotly.react('plot-static-csd',[{type:'heatmap',x:x,y:y,z:csd,colorscale:_CSD_BLUE_GREY_RED,reversescale:false,zmid:0,zmin:-clim,zmax:clim,colorbar:{title:{text:'CSD',side:'right'},x:_CSD_COLORBAR_X,xanchor:'center',len:0.88,thickness:15},hovertemplate:'t=%{x:.1f} ms<br>depth=%{y:.0f} µm<br>CSD=%{z:.4g}<extra></extra>'}],{...common,shapes:[...csdOverlay.shapes,onsetLine],annotations:csdOverlay.annotations,title:{text:'CSD · blue = sink · red = source',font:{size:16}}},BASE_PLOTLY_CONFIG).then(() => enhancePlotlyTooltips());
            renderStaticSpectral();
        }

        function initStaticCsd() {
            if(!csdData.length) return;
            const sessions=_csdUnique(csdData.map(d=>d.session_key)), labels=sessions.map(s=>{const r=csdData.find(d=>String(d.session_key)===String(s));return r?r.session_label:s;});
            _csdSetOptions('csd-session',sessions,labels);
            document.getElementById('csd-session').addEventListener('change',_csdRefreshProbe); document.getElementById('csd-probe').addEventListener('change',_csdRefreshStim); document.getElementById('csd-stim').addEventListener('change',_csdRefreshCondition); document.getElementById('csd-condition').addEventListener('change',renderStaticCsd); document.getElementById('csd-align').addEventListener('change',renderStaticCsd); document.getElementById('csd-view').addEventListener('change',renderStaticCsd); document.getElementById('csd-band').addEventListener('change',renderStaticSpectral); document.getElementById('csd-band-metric').addEventListener('change',renderStaticSpectral);
            _spectralEnsureBandOptions(); _csdRefreshProbe();
        }

        document.getElementById('global-mouse').addEventListener('change', renderAll); document.getElementById('global-probe').addEventListener('change', renderAll); document.getElementById('global-division').addEventListener('change', updateCascadingFilters); document.getElementById('global-group').addEventListener('change', updateCascadingFilters); document.getElementById('global-family').addEventListener('change', updateCascadingFilters); document.getElementById('global-subregion').addEventListener('change', updateCascadingFilters); document.getElementById('global-layer').addEventListener('change', updateCascadingFilters); document.getElementById('global-area').addEventListener('change', renderAll); document.getElementById('boundary-overlay').addEventListener('change', renderAll); document.getElementById('depth-alignment').addEventListener('change', renderAll); document.getElementById('color-scale-mode').addEventListener('change', renderAll); document.getElementById('target-metric').addEventListener('change', renderAll); document.getElementById('custom-x').addEventListener('change', renderAll);

        function renderAll() {
            const targetMetGroup = document.getElementById('y-axis-group'), xAxisGroup = document.getElementById('x-axis-group'), sidebar = document.querySelector('.sidebar'), grid = document.querySelector('.layout-grid'), countBox = document.getElementById('unit-count');
            if (currentTab === 'tab-timeseries' || currentTab === 'tab-yield' || currentTab === 'tab-csd') { targetMetGroup.style.display = 'none'; document.getElementById('log-toggles-container').style.display = 'none'; } else { targetMetGroup.style.display = 'flex'; if (currentTab === 'tab-ecdf' || currentTab === 'tab-custom') { document.getElementById('log-toggles-container').style.display = 'block'; if (currentTab === 'tab-ecdf') { document.getElementById('log-y-axis-container').style.display = 'none'; } else { document.getElementById('log-y-axis-container').style.display = 'inline-block'; } } else { document.getElementById('log-toggles-container').style.display = 'none'; } }
            if (xAxisGroup) xAxisGroup.style.display = (currentTab === 'tab-custom') ? 'flex' : 'none';
            if (sidebar) sidebar.style.display = (currentTab === 'tab-csd') ? 'none' : 'block';
            if (grid) grid.classList.toggle('csd-mode', currentTab === 'tab-csd');
            if (countBox) countBox.style.display = (currentTab === 'tab-csd') ? 'none' : 'block';
            if(currentTab === 'tab-yield') renderYield(); else if(currentTab === 'tab-ecdf') renderECDF(); else if(currentTab === 'tab-depth') renderDepth(); else if(currentTab === 'tab-layers') renderLayerProfile(); else if(currentTab === 'tab-timeseries') renderTimeSeries(); else if(currentTab === 'tab-custom') renderCustom(); else if(currentTab === 'tab-csd') renderStaticCsd();
        }

        window.switchTab = function(evt, tabName) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            const target = document.getElementById(tabName);
            if (target) target.classList.add('active');
            if (evt && evt.currentTarget && evt.currentTarget.classList) {
                evt.currentTarget.classList.add('active');
            } else {
                const btn = document.querySelector(`.tab-btn[onclick*="${tabName}"]`);
                if (btn) btn.classList.add('active');
            }
            currentTab = tabName;
            renderAll();
            setTimeout(() => {
                window.dispatchEvent(new Event('resize'));
                if (typeof Plotly !== 'undefined') {
                    document.querySelectorAll('.tab-content.active .plot-area').forEach(p => {
                        if (p && p.data) Plotly.Plots.resize(p);
                    });
                }
            }, 60);
        };
