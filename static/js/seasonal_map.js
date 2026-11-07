// Interactive Zambia seasonal rainfall map, rendered by templates/weather/_seasonal_map.html.
// Other pages can drive the layer with:
//   document.dispatchEvent(new CustomEvent('seasonal-map:set-layer', {detail: 'seas5'}))
// and follow it through the 'seasonal-map:layer-changed' event. Districts work
// the same way: 'seasonal-map:select-district' (detail: name) selects one and
// 'seasonal-map:district-selected' reports every selection.
(() => {
    const mapElement = document.getElementById('zambia-map');
    if (!mapElement) return;
    const data = JSON.parse(document.getElementById('seasonal-map-data').textContent);
    const initialDistrict = JSON.parse(document.getElementById('selected-district').textContent);
    const SEAS5_ORDER = ['below', 'normal_below', 'normal', 'normal_above', 'above'];
    const ZMD_ORDER = ['below', 'normal_below', 'normal_above', 'above'];
    let totalDistricts = 0;  // set from the boundary file once it loads

    const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => (
        {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]
    ));
    const signed = (value, digits = 1) => `${value > 0 ? '+' : ''}${value.toFixed(digits)}`;
    const findBy = (collection, name) => {
        const key = Object.keys(collection).find((k) => k.toLowerCase() === String(name).toLowerCase());
        return key ? collection[key] : null;
    };
    const layerSelect = document.getElementById('map-layer');
    let currentLayer = layerSelect.value;
    let selectedName = null;

    const periodOf = (layer) => layer.split(':')[1];
    // SEAS5 uses ZEWCO's seasonal-model palette; each ZMD period keeps the
    // colours of its official forecast map.
    const paletteFor = (layer) => (layer === 'seas5' ? data.colors.seas5 : data.colors.zmd[periodOf(layer)]);

    function categoryFor(name) {
        if (currentLayer === 'seas5') {
            const record = findBy(data.seas5, name);
            return record ? record.category : null;
        }
        const record = findBy(data.zmd, name);
        const period = periodOf(currentLayer);
        return record && record[period] ? record[period].category : null;
    }

    function tooltipHtml(properties) {
        const name = properties.name;
        let detail;
        if (currentLayer === 'seas5') {
            const record = findBy(data.seas5, name);
            detail = record && record.departure_percent !== null
                ? `SEAS5 Oct–Mar: <strong>${signed(record.departure_percent)}%</strong> vs model normal<br>${escapeHtml(data.labels[record.category])}`
                : 'No SEAS5 outlook cached';
        } else {
            const period = periodOf(currentLayer);
            const record = findBy(data.zmd, name);
            detail = record && record[period]
                ? `ZMD ${period}: <strong>${escapeHtml(data.labels[record[period].category])}</strong><br>Confidence: ${escapeHtml(record[period].confidence || 'n/a')}`
                : `No ZMD ${period} category`;
        }
        return `<strong>${escapeHtml(name)}</strong> · ${escapeHtml(properties.province)}<br>${detail}`;
    }

    // Drawn the way ZEWCO draws its forecasts: the forecast is a smooth field
    // (pre-rendered tiles), and district, province and country outlines sit over
    // it as reference geometry. Districts are click targets, not colour units.
    const map = L.map(mapElement, {scrollWheelZoom: false, zoomSnap: 0.25, maxZoom: 10}).setView([-13.3, 27.8], 6);
    // No basemap: free tile servers need API keys or block apps that don't meet
    // their usage policy, and ZEWCO's map is basemap-free too.
    map.attributionControl.addAttribution('Boundaries: OCHA / HDX');
    map.createPane('outlines').style.zIndex = 450;
    map.getPane('outlines').style.pointerEvents = 'none';
    map.createPane('selection').style.zIndex = 460;
    map.getPane('selection').style.pointerEvents = 'none';

    const fields = data.fields;
    const fieldBounds = L.latLngBounds([fields.bounds[1], fields.bounds[0]], [fields.bounds[3], fields.bounds[2]]);
    const fieldUrlFor = (layer) => (layer === 'seas5'
        ? (fields.seas5 ? fields.seas5.url : null)
        : (fields.zmd[periodOf(layer)] || null));
    let fieldLayer = null;
    function showField() {
        if (fieldLayer) { map.removeLayer(fieldLayer); fieldLayer = null; }
        const url = fieldUrlFor(currentLayer);
        if (!url) return;
        fieldLayer = L.tileLayer(url, {
            bounds: fieldBounds,
            minNativeZoom: fields.min_zoom,
            maxNativeZoom: fields.max_zoom,
            maxZoom: 10,
        }).addTo(map);
    }

    let districtLayer = null;
    let selectionLayer = null;
    // Without a rendered field (tiles not built yet) the districts fall back to a
    // category fill so the layer still says something.
    const styleFor = (feature) => {
        if (fieldUrlFor(currentLayer)) {
            return {fillColor: '#ffffff', fillOpacity: 0, color: '#111827', weight: 0.45, opacity: 0.28};
        }
        const category = categoryFor(feature.properties.name);
        return {
            fillColor: category ? paletteFor(currentLayer)[category] : '#ffffff',
            fillOpacity: category ? 0.9 : 0.5,
            color: '#111827',
            weight: 0.45,
            opacity: 0.5,
            dashArray: category ? null : '3',
        };
    };
    const hoverStyle = {fillColor: '#ffffff', fillOpacity: 0.22};

    function drawSelection(feature) {
        if (selectionLayer) map.removeLayer(selectionLayer);
        selectionLayer = L.layerGroup([
            L.geoJSON(feature, {pane: 'selection', interactive: false, style: {color: '#ffffff', weight: 4, opacity: 0.9, fill: false}}),
            L.geoJSON(feature, {pane: 'selection', interactive: false, style: {color: '#111827', weight: 1.8, fill: false}}),
        ]).addTo(map);
    }

    function loadOutlines(url, style) {
        if (!url) return;
        fetch(url)
            .then((response) => response.json())
            .then((geojson) => L.geoJSON(geojson, {pane: 'outlines', interactive: false, style}).addTo(map))
            .catch(() => {});
    }

    function renderLegend() {
        const legend = document.getElementById('map-legend');
        const palette = paletteFor(currentLayer);
        const hasField = Boolean(fieldUrlFor(currentLayer));
        if (currentLayer === 'seas5' && hasField) {
            // A continuous field gets a gradient bar; stops sit at category centres.
            const stops = SEAS5_ORDER.map((category) => palette[category]).join(', ');
            legend.innerHTML = `<li class="w-100"><div class="field-gradient" style="background: linear-gradient(to right, ${stops})"></div>` +
                '<div class="field-ticks"><span>≤ −20%</span><span>−10%</span><span>0</span><span>+10%</span><span>≥ +20%</span></div>' +
                '<div class="field-ticks text-muted"><span>Below Normal</span><span>Normal</span><span>Above Normal</span></div></li>';
        } else {
            const order = currentLayer === 'seas5' ? SEAS5_ORDER : ZMD_ORDER;
            legend.innerHTML = order.map((category) => (
                `<li><span class="swatch" style="background:${palette[category]}"></span>${escapeHtml(data.labels[category])}</li>`
            )).join('') + (hasField ? '' : '<li><span class="swatch no-data"></span>No data</li>');
        }
        const note = document.getElementById('map-layer-note');
        if (currentLayer === 'seas5') {
            const count = Object.keys(data.seas5).length;
            note.textContent = hasField
                ? `SEAS5 Oct–Mar rainfall vs the model's own normal, interpolated and smoothed from a 0.5° grid (retrieved ${fields.seas5.retrieved}). District figures: under −15% Below Normal, −15% to −5% Normal to Below, ±5% Normal, +5% to +15% Normal to Above, over +15% Above Normal. ${count} of ${totalDistricts} districts have a cached outlook.`
                : `The smooth SEAS5 field has not been built yet (Refresh SEAS5 for all districts), so districts are filled by category. ${count} of ${totalDistricts} districts have a cached outlook.`;
        } else {
            note.textContent = hasField
                ? `ZMD ${data.season} ${periodOf(currentLayer)} forecast in the official ZMD map colours, as rendered by ZEWCO. Hover a district for its majority category.`
                : `ZMD ${data.season} ${periodOf(currentLayer)} consensus category: the zone covering most of each district.`;
        }
    }

    function renderZmdChips(name) {
        const container = document.getElementById('district-zmd');
        const record = findBy(data.zmd, name);
        if (!record) {
            container.innerHTML = '<span class="small text-muted">No ZMD outlook for this district.</span>';
            return;
        }
        container.innerHTML = data.periods.map((period) => {
            const entry = record[period];
            if (!entry) return '';
            return `<div class="zmd-chip small"><div class="text-muted">${period}</div>` +
                `<div><span class="swatch" style="background:${data.colors.zmd[period][entry.category]}"></span>${escapeHtml(data.labels[entry.category])}</div>` +
                `<div class="text-muted">Confidence: ${escapeHtml(entry.confidence || 'n/a')}</div></div>`;
        }).join('');
    }

    let chart = null;
    function renderChart(name) {
        const record = findBy(data.seas5, name);
        const empty = document.getElementById('seas5-chart-empty');
        const summary = document.getElementById('district-seas5-summary');
        const table = document.getElementById('seas5-table');
        if (chart) { chart.destroy(); chart = null; }
        if (!record) {
            summary.textContent = '';
            empty.textContent = 'No SEAS5 outlook is cached for this district yet. Refresh SEAS5 for all districts to plot it.';
            table.innerHTML = '';
            return;
        }
        empty.textContent = `SEAS5 retrieved ${record.retrieved}. Hover a month for values.`;
        summary.innerHTML = record.departure_percent !== null
            ? `SEAS5 Oct–Mar: <strong>${signed(record.departure_percent)}%</strong> vs model normal · ${escapeHtml(data.labels[record.category])} (${record.months_used} months)`
            : '';
        table.innerHTML = record.months.map((m) => (
            `<tr><td>${escapeHtml(m.month)}</td><td>${m.forecast_mm !== null ? m.forecast_mm.toFixed(1) + ' mm' : '—'}</td>` +
            `<td>${m.normal_mm !== null ? m.normal_mm.toFixed(1) + ' mm' : '—'}</td>` +
            `<td>${m.anomaly_mm !== null ? signed(m.anomaly_mm) + ' mm' : '—'}</td></tr>`
        )).join('');
        chart = new Chart(document.getElementById('seas5-chart'), {
            data: {
                labels: record.months.map((m) => m.month.split(' ')[0]),
                datasets: [
                    {
                        type: 'bar',
                        label: 'SEAS5 forecast',
                        data: record.months.map((m) => m.forecast_mm),
                        backgroundColor: data.colors.seas5.above,
                        borderRadius: 4,
                        maxBarThickness: 28,
                        order: 2,
                    },
                    {
                        type: 'line',
                        label: 'Model normal',
                        data: record.months.map((m) => m.normal_mm),
                        borderColor: '#6b6a66',
                        backgroundColor: '#6b6a66',
                        borderWidth: 2,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        order: 1,
                    },
                ],
            },
            options: {
                maintainAspectRatio: false,
                interaction: {mode: 'index', intersect: false},
                scales: {
                    x: {grid: {display: false}},
                    y: {beginAtZero: true, title: {display: true, text: 'Rainfall (mm)'}, grid: {color: '#ecebe8'}},
                },
                plugins: {
                    legend: {position: 'bottom', labels: {boxWidth: 12}},
                    tooltip: {
                        callbacks: {
                            title: (items) => record.months[items[0].dataIndex].month,
                            label: (item) => `${item.dataset.label}: ${item.parsed.y === null ? '—' : item.parsed.y.toFixed(1) + ' mm'}`,
                            afterBody: (items) => {
                                const anomaly = record.months[items[0].dataIndex].anomaly_mm;
                                return anomaly === null ? '' : `Anomaly: ${signed(anomaly)} mm`;
                            },
                        },
                    },
                },
            },
        });
    }

    function selectDistrict(feature) {
        const properties = feature.properties;
        selectedName = properties.name;
        document.getElementById('district-name').textContent = properties.name;
        document.getElementById('district-province').textContent = `${properties.province} Province`;
        renderChart(properties.name);
        renderZmdChips(properties.name);
        drawSelection(feature);
        document.dispatchEvent(new CustomEvent('seasonal-map:district-selected', {detail: properties.name}));
    }

    let districtFeatures = [];
    const featureNamed = (name) => districtFeatures.find(
        (f) => name && f.properties.name.toLowerCase() === String(name).toLowerCase(),
    );

    fetch(mapElement.dataset.geojsonUrl)
        .then((response) => response.json())
        .then((geojson) => {
            districtLayer = L.geoJSON(geojson, {
                style: styleFor,
                onEachFeature: (feature, layer) => {
                    layer.bindTooltip(() => tooltipHtml(feature.properties), {sticky: true});
                    layer.on({
                        mouseover: () => layer.setStyle(hoverStyle),
                        mouseout: () => districtLayer.resetStyle(layer),
                        click: () => selectDistrict(feature),
                    });
                },
            }).addTo(map);
            map.fitBounds(districtLayer.getBounds(), {padding: [8, 8]});
            totalDistricts = geojson.features.length;
            districtFeatures = geojson.features;
            renderLegend();
            const initial = featureNamed(initialDistrict);
            if (initial) selectDistrict(initial);
        })
        .catch(() => {
            document.getElementById('map-layer-note').textContent = 'District boundaries could not be loaded. Run "python manage.py build_district_geojson".';
        });
    loadOutlines(mapElement.dataset.provincesUrl, {color: '#111827', weight: 0.9, opacity: 0.72, fill: false});
    loadOutlines(mapElement.dataset.countryUrl, {color: '#111827', weight: 1.4, opacity: 0.95, fill: false});

    function setLayer(layer) {
        if (![...layerSelect.options].some((option) => option.value === layer)) return;
        currentLayer = layer;
        layerSelect.value = layer;
        showField();
        renderLegend();
        if (districtLayer) districtLayer.setStyle(styleFor);
        document.dispatchEvent(new CustomEvent('seasonal-map:layer-changed', {detail: layer}));
    }

    layerSelect.addEventListener('change', () => setLayer(layerSelect.value));
    document.addEventListener('seasonal-map:set-layer', (event) => setLayer(event.detail));
    document.addEventListener('seasonal-map:select-district', (event) => {
        const feature = featureNamed(event.detail);
        if (feature && feature.properties.name !== selectedName) selectDistrict(feature);
    });
    showField();
    renderLegend();
})();
