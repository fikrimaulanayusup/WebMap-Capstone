const $ = (id) => document.getElementById(id);

const SENSOR_LABELS = { "sentinel-1": "Sentinel-1", "sentinel-2": "Sentinel-2", "landsat-8": "Landsat 8" };
// Katalog sumber tiap sensor (untuk pesan status).
const CATALOG_LABELS = { "sentinel-1": "AWS", "sentinel-2": "AWS", "landsat-8": "Planetary Computer" };
const isOptical = (sensor) => sensor !== "sentinel-1";
const platformLabel = (platform) => (platform || "").replace("sentinel-", "S").replace("landsat-", "L").toUpperCase();

// ---------- Peta ----------
// Tampilan awal: perairan Kepulauan Riau / Selat Singapura, jalur pelayaran padat.
// worldCopyJump: bila peta digeser melewati bujur ±180°, tampilan melompat ke salinan dunia
// utama sehingga koordinat tetap di −180…180 (katalog STAC tidak mengenal bujur 271°).
const map = L.map("map", { center: [1.0, 104.3], zoom: 8, minZoom: 3, worldCopyJump: true });

// Bujur Leaflet tetap bisa di luar ±180 (mis. tampilan yang diatur lewat kode); samakan ke −180…180.
function normalizeBounds(bounds) {
  const shift = Math.round(bounds.getCenter().lng / 360) * 360;
  if (!shift) return bounds;
  return L.latLngBounds([bounds.getSouth(), bounds.getWest() - shift], [bounds.getNorth(), bounds.getEast() - shift]);
}

const basemaps = {
  OpenStreetMap: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; kontributor OpenStreetMap",
    maxZoom: 19,
    zIndex: 0,
  }),
  "Citra optik (Esri)": L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Tiles &copy; Esri", maxZoom: 19, zIndex: 0 }
  ),
};
basemaps.OpenStreetMap.addTo(map);

const FOOTPRINT_STYLE = { color: "#1f6fd1", weight: 1, fillOpacity: 0.05 };
const FOOTPRINT_ACTIVE = { color: "#e8590c", weight: 2, fillOpacity: 0 };

const footprints = L.featureGroup().addTo(map);
L.control.layers(basemaps, { "Jejak scene (footprint)": footprints }, { position: "topright" }).addTo(map);
L.control.scale({ imperial: false }).addTo(map);

// ---------- State ----------
// Filter yang sedang berlaku (hasil form filter); chip sensor dan pencarian memakai ini.
let applied = null;
// Sensor dari hasil pencarian yang sedang ditampilkan di daftar.
let resultSensor = null;
// id scene -> { feature, footprint, card, checkbox, tileLayer, toggleDay, dayItems }
const scenes = new Map();
let searchSeq = 0;
const pendingTiles = new Set(); // elemen <img> tile citra yang masih dimuat
// Hasil deteksi oil spill terakhir (FeatureCollection) dan layernya di peta.
let detectLayer = null;
let detectBusy = false;
const mxLayers = { overlay: null }; // peta kelas MariNeXt

// ---------- Menu & panel ----------
// Satu panel terbuka pada satu waktu; klik menu yang sama lagi untuk menutupnya.
const menuItems = document.querySelectorAll(".menu-item");

// Layer peta milik tiap panel hanya tampil saat panelnya terbuka. Saat panel ditutup / berganti,
// layer yang sedang tampil disimpan lalu disembunyikan, dan dikembalikan saat panel dibuka lagi.
const panelLayers = {
  "menu-imagery": () => [footprints, ...[...scenes.values()].map((s) => s.tileLayer)],
  "menu-detect": () => [detect.layer, detect.box, detect.drawing?.rect, mxLayers.overlay, detectLayer],
};
const stashedLayers = { "menu-imagery": [], "menu-detect": [] };

function setPanelLayers(menuId, show) {
  if (show) {
    stashedLayers[menuId].forEach((layer) => layer.addTo(map));
    stashedLayers[menuId] = [];
    if (detectLayer && map.hasLayer(detectLayer)) detectLayer.bringToFront();
  } else {
    const visible = panelLayers[menuId]().filter((layer) => layer && map.hasLayer(layer));
    visible.forEach((layer) => map.removeLayer(layer));
    stashedLayers[menuId].push(...visible);
  }
}

// Lapisan yang sengaja dibuang (mis. kotak setelah klasifikasi) tidak boleh muncul lagi dari simpanan.
function unstashLayer(layer) {
  for (const id in stashedLayers) stashedLayers[id] = stashedLayers[id].filter((l) => l !== layer);
}

function togglePanel(button) {
  const opening = button.getAttribute("aria-expanded") !== "true";
  menuItems.forEach((item) => {
    const open = opening && item === button;
    const wasOpen = item.getAttribute("aria-expanded") === "true";
    item.setAttribute("aria-expanded", open);
    $(item.getAttribute("aria-controls")).hidden = !open;
    if (wasOpen && !open) setPanelLayers(item.id, false);
  });
  if (opening) setPanelLayers(button.id, true);
  map.invalidateSize(); // lebar peta berubah saat panel muncul/hilang
  if (opening && button.id === "menu-imagery" && !applied) applyFilters();
  if (opening && button.id === "menu-detect") updateDetectUI();
}

menuItems.forEach((item) => item.addEventListener("click", () => togglePanel(item)));

function setFiltersOpen(open) {
  $("filters").hidden = !open;
  $("filter-btn").setAttribute("aria-expanded", open);
}

$("filter-btn").addEventListener("click", () => setFiltersOpen($("filters").hidden));

// ---------- Form filter ----------
const isoDate = (d) => d.toISOString().slice(0, 10);
const formSensor = () => document.querySelector('input[name="sensor"]:checked').value;

function setRange(days) {
  const end = new Date();
  const start = new Date(end.getTime() - (days - 1) * 86400000);
  $("start").value = isoDate(start);
  $("end").value = isoDate(end);
}
setRange(7);
$("start").max = $("end").max = isoDate(new Date());

document.querySelectorAll(".presets button").forEach((btn) =>
  btn.addEventListener("click", () => setRange(Number(btn.dataset.days)))
);

document.querySelectorAll('input[name="sensor"]').forEach((radio) =>
  radio.addEventListener("change", () => {
    // Awan hanya relevan untuk optik, arah orbit hanya untuk radar.
    document.querySelectorAll("#filters [data-sensor]").forEach((field) => {
      field.hidden = !field.dataset.sensor.split(" ").includes(formSensor());
    });
  })
);

$("cloud").addEventListener("input", () => {
  $("cloud-out").textContent = `${$("cloud").value}%`;
});

const shortDate = (day) =>
  new Date(`${day}T00:00:00Z`).toLocaleDateString("id-ID", {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });

function filterSummary(f) {
  const dates = f.start === f.end ? shortDate(f.start) : `${shortDate(f.start)} – ${shortDate(f.end)}`;
  const extra = isOptical(f.sensor)
    ? `awan ≤ ${f.cloud}%`
    : { "": "semua orbit", ascending: "orbit naik", descending: "orbit turun" }[f.orbit];
  return `${dates} · ${extra}`;
}

function applyFilters() {
  const start = $("start").value;
  const end = $("end").value;
  if (!start || !end) {
    setStatus("Isi tanggal awal dan akhir.", true);
    return false;
  }
  if (start > end) {
    setStatus("Tanggal awal harus sebelum tanggal akhir.", true);
    return false;
  }

  applied = { sensor: formSensor(), start, end, cloud: $("cloud").value, orbit: $("orbit").value };
  $("sensor-chip").textContent = SENSOR_LABELS[applied.sensor];
  $("filter-summary").textContent = filterSummary(applied);
  $("sar-display").hidden = applied.sensor !== "sentinel-1";
  search();
  return true;
}

$("filters").addEventListener("submit", (e) => {
  e.preventDefault();
  if (applyFilters()) setFiltersOpen(false);
});

$("search-here").addEventListener("click", search);

// ---------- Pencarian ----------
function setStatus(text, isError = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", isError);
}

function clearScenes() {
  scenes.forEach((s) => s.tileLayer && map.removeLayer(s.tileLayer));
  scenes.clear();
  footprints.clearLayers();
  $("results").replaceChildren();
  $("hide-all").hidden = true;
}

async function search() {
  if (!applied) return;
  const filter = applied;
  const label = SENSOR_LABELS[filter.sensor];

  const b = normalizeBounds(map.getBounds());
  const params = new URLSearchParams({
    sensor: filter.sensor,
    start: filter.start,
    end: filter.end,
    bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(5)).join(","),
  });
  if (isOptical(filter.sensor)) params.set("cloud", filter.cloud);
  else if (filter.orbit) params.set("orbit", filter.orbit);

  const seq = ++searchSeq;
  $("apply-btn").disabled = $("search-here").disabled = true;
  setStatus(`Mencari citra ${label} di katalog ${CATALOG_LABELS[filter.sensor]}…`);

  try {
    const resp = await fetch(`/api/search?${params}`);
    const data = await resp.json();
    if (seq !== searchSeq) return; // sudah ada pencarian yang lebih baru
    if (!resp.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${resp.status}`);

    clearScenes();
    resultSensor = filter.sensor;
    renderResults(data.features);
    if (data.returned === 0) {
      const tip = isOptical(filter.sensor) ? " Coba naikkan batas tutupan awan atau perpanjang rentang tanggal." : "";
      setStatus(`Tidak ada citra ${label} pada rentang tanggal dan area ini.${tip}`);
    } else if (data.matched > data.returned) {
      setStatus(`${data.returned} citra terbaru ditampilkan dari ${data.matched} yang cocok. Persempit tanggal atau area.`);
    } else {
      setStatus(`${data.returned} citra ${label} ditemukan. Klik untuk menampilkan di peta.`);
    }
  } catch (err) {
    if (seq === searchSeq) setStatus(`Pencarian gagal: ${err.message}`, true);
  } finally {
    if (seq === searchSeq) $("apply-btn").disabled = $("search-here").disabled = false;
  }
}

// ---------- Daftar hasil ----------
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const dayLabel = (day) =>
  new Date(`${day}T00:00:00Z`).toLocaleDateString("id-ID", {
    weekday: "short", day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  });

function sceneMeta(p) {
  const platform = platformLabel(p.platform);
  if (isOptical(resultSensor)) {
    const cloud = p.cloud_cover == null ? "" : `awan ${Math.round(p.cloud_cover)}%`;
    return [platform, p.tile, cloud].filter(Boolean).join(" · ");
  }
  const orbit = p.orbit_state === "ascending" ? "↑ naik" : p.orbit_state === "descending" ? "↓ turun" : "";
  const pols = p.assets.map((x) => x.toUpperCase()).join("+");
  return [platform, p.mode, orbit, `orbit ${p.relative_orbit}`, pols].filter(Boolean).join(" · ");
}

function renderResults(features) {
  const byDay = new Map();
  for (const f of features) {
    const day = f.properties.datetime.slice(0, 10);
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(f);
  }

  for (const [day, items] of byDay) {
    const group = el("div", "day");
    const head = el("div", "day-head");
    const title = el("span", null, dayLabel(day));
    title.append(el("span", "count", `${items.length} citra`));
    const toggleDay = el("button", "link", "Tampilkan semua");
    toggleDay.type = "button";
    toggleDay.addEventListener("click", () => {
      const turnOn = items.some((f) => !scenes.get(f.id).tileLayer);
      items.forEach((f) => setSceneVisible(f.id, turnOn));
    });
    head.append(title, toggleDay);
    group.append(head);

    for (const f of items) {
      const card = el("div", "scene");
      const checkbox = el("input");
      checkbox.type = "checkbox";
      checkbox.setAttribute("aria-label", `Tampilkan citra ${f.id}`);
      const info = el("div", "info");
      info.append(
        el("div", "time", `${f.properties.datetime.slice(11, 16)} UTC`),
        el("div", "meta", sceneMeta(f.properties))
      );
      info.title = f.id;
      const zoom = el("button", "zoom", "Zoom");
      zoom.type = "button";

      const footprint = L.geoJSON(f, { style: FOOTPRINT_STYLE });
      footprint.bindTooltip(
        [day, `${f.properties.datetime.slice(11, 16)} UTC`, f.properties.tile].filter(Boolean).join(" · "),
        { sticky: true }
      );
      footprint.addTo(footprints);

      const scene = { feature: f, footprint, card, checkbox, tileLayer: null, toggleDay, dayItems: items };
      scenes.set(f.id, scene);

      card.addEventListener("click", (e) => {
        if (e.target === zoom) return;
        setSceneVisible(f.id, !scene.tileLayer);
      });
      zoom.addEventListener("click", () => map.fitBounds(footprint.getBounds(), { padding: [20, 20] }));
      card.addEventListener("mouseenter", () => footprint.setStyle({ weight: 3 }));
      card.addEventListener("mouseleave", () => footprint.setStyle({ weight: scene.tileLayer ? 2 : 1 }));
      footprint.on("click", () => {
        setSceneVisible(f.id, !scene.tileLayer);
        card.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });

      card.append(checkbox);
      if (f.properties.thumbnail) {
        const thumb = el("img", "thumb");
        thumb.src = f.properties.thumbnail;
        thumb.alt = "";
        thumb.loading = "lazy";
        card.append(thumb);
      }
      card.append(info, zoom);
      group.append(card);
    }
    $("results").append(group);
  }
}

// ---------- Layer citra ----------
// URL tile sebuah scene, atau null jika scene tidak punya aset yang bisa ditampilkan.
function tileUrlFor(sensor, feature) {
  // Landsat 8: tile dirender langsung oleh Microsoft Planetary Computer (URL dari backend).
  if (sensor === "landsat-8") return feature.properties.tiles || null;
  const assets = feature.properties.assets;
  const base = `/api/tiles/${sensor}/${feature.id}`;
  if (sensor === "sentinel-2") {
    return assets.includes("visual") ? `${base}/visual/{z}/{x}/{y}.png` : null;
  }
  if (!assets.length) return null;
  // Scene polarisasi tunggal (mis. hanya VV) tetap tampil walau pilihan pengguna berbeda.
  const pol = assets.includes($("pol").value) ? $("pol").value : assets[0];
  return `${base}/${pol}/{z}/{x}/{y}.png?vmin=${$("vmin").value}&vmax=${$("vmax").value}`;
}

const tileUrl = (scene) => tileUrlFor(resultSensor, scene.feature);

// Resolusi & atribusi per sensor.
const TILE_SOURCES = {
  sentinel: {
    maxNativeZoom: 14, // piksel 10 m, baik Sentinel-1 GRD maupun Sentinel-2
    attribution: "Citra Sentinel &copy; Copernicus/ESA, via AWS Open Data",
  },
  "landsat-8": {
    maxNativeZoom: 13, // piksel 30 m
    attribution: "Citra Landsat 8 &copy; USGS, via Microsoft Planetary Computer",
  },
};

function sceneTileLayer(url, bounds, sensor) {
  const layer = L.tileLayer(url, {
    bounds,
    minZoom: 4,
    maxZoom: 18,
    opacity: $("opacity").value / 100,
    zIndex: 10,
    ...(TILE_SOURCES[sensor] || TILE_SOURCES.sentinel),
  });
  // Dilacak per tile: status isLoading() milik Leaflet bisa macet saat tile dibatalkan oleh zoom.
  layer.on("tileloadstart", (e) => { pendingTiles.add(e.tile); updateLoading(); });
  layer.on("tileload tileerror tileabort tileunload", (e) => { pendingTiles.delete(e.tile); updateLoading(); });
  return layer;
}

function updateLoading() {
  $("loading").hidden = pendingTiles.size === 0;
}

function setSceneVisible(id, visible) {
  const scene = scenes.get(id);
  if (!scene || Boolean(scene.tileLayer) === visible) return;

  if (visible) {
    const url = tileUrl(scene);
    if (!url) return;
    const layer = sceneTileLayer(url, scene.footprint.getBounds(), resultSensor);
    scene.tileLayer = layer;
    layer.addTo(map);
  } else {
    map.removeLayer(scene.tileLayer);
    scene.tileLayer = null;
  }

  scene.checkbox.checked = visible;
  scene.card.classList.toggle("active", visible);
  scene.footprint.setStyle(visible ? FOOTPRINT_ACTIVE : FOOTPRINT_STYLE);
  if (visible) scene.footprint.bringToFront();
  if (detectLayer && map.hasLayer(detectLayer)) detectLayer.bringToFront(); // poligon deteksi harus tetap bisa diklik

  const allOn = scene.dayItems.every((f) => scenes.get(f.id).tileLayer);
  scene.toggleDay.textContent = allOn ? "Sembunyikan" : "Tampilkan semua";
  $("hide-all").hidden = ![...scenes.values()].some((s) => s.tileLayer);
}

$("hide-all").addEventListener("click", () => scenes.forEach((_, id) => setSceneVisible(id, false)));

// ---------- Pengaturan tampilan ----------
function refreshTiles() {
  scenes.forEach((s) => s.tileLayer && s.tileLayer.setUrl(tileUrl(s)));
}

$("pol").addEventListener("change", refreshTiles);

$("opacity").addEventListener("input", () => {
  $("opacity-out").textContent = `${$("opacity").value}%`;
  scenes.forEach((s) => s.tileLayer && s.tileLayer.setOpacity($("opacity").value / 100));
});

function syncStretch(changed) {
  // Jaga agar batas gelap selalu di bawah batas terang.
  let vmin = Number($("vmin").value);
  let vmax = Number($("vmax").value);
  if (vmin >= vmax) {
    if (changed === "vmin") $("vmax").value = vmax = Math.min(80, vmin + 1);
    else $("vmin").value = vmin = Math.max(10, vmax - 1);
    if (vmin >= vmax) $(changed).value = changed === "vmin" ? (vmin = vmax - 1) : (vmax = vmin + 1);
  }
  $("vmin-out").textContent = `${vmin} dB`;
  $("vmax-out").textContent = `${vmax} dB`;
}

for (const id of ["vmin", "vmax"]) {
  $(id).addEventListener("input", () => syncStretch(id));
  $(id).addEventListener("change", refreshTiles); // muat ulang tile hanya saat slider dilepas
}

// ---------- Deteksi oil spill ----------
// Model per sensor: endpoint, pilihan ukuran kotak (km) beserta perkiraan lama proses.
const SCHEMES = {
  "sentinel-1": {
    chip: "SAR · U-Net",
    model: "U-Net SAR",
    api: "/api/sar-unet",
    sizes: [[20, "~20 dtk"], [40, "~40 dtk"], [80, "~1,5 menit"]], // mode standar; akurat 2–3× lebih lama
    km: 40,
    run: "Klasifikasi SAR dengan U-Net",
    hint: "Yang dianalisis: bagian citra di dalam kotak. Prosesnya kalibrasi σ⁰ → dB −35..0 ke 0–255 → " +
      "potongan seukuran data latih → U-Net 5 kelas.",
    classHead: "Kelas",
  },
  "sentinel-2": {
    chip: "Optik · MariNeXt",
    model: "MariNeXt",
    api: "/api/marinext",
    sizes: [[10, "~5 menit"], [20, "~15 menit"], [40, "~45 menit"]],
    km: 20,
    run: "Klasifikasi dengan MariNeXt",
    hint: "Yang dianalisis: bagian citra di dalam kotak. Prosesnya unduh L1C → ACOLITE → MariNeXt → " +
      "masker awan (L2A); lama proses mengikuti ukuran kotak.",
    classHead: "Kelas",
  },
};

const num = (v, digits = 2) => Number(v).toLocaleString("id-ID", { maximumFractionDigits: digits });
const pct = (v) => `${Math.round(v * 100)}%`;

function setDetectStatus(text, isError = false) {
  $("detect-status").textContent = text;
  $("detect-status").classList.toggle("error", isError);
}

// ---------- Panel deteksi: kotak analisis → citra yang menutupinya ----------
// Kotak bisa diklik/ditarik untuk dipindah; isinya ikut terisi tipis agar mudah dipegang.
const BOX_STYLE = {
  color: "#ffd43b", weight: 2, dashArray: "6 5", fill: true, fillOpacity: 0.04,
  interactive: true, className: "analysis-box",
};
const DETECT_SCENE_LIMIT = 15;
const FULL_COVERAGE = 0.99;

const detect = {
  box: null, // L.Rectangle kotak analisis
  drawing: null, // { start, rect } selama menggambar
  scenes: [], // hasil pencarian untuk kotak, dengan cakupan
  selected: null, // fitur citra yang dipilih
  layer: null, // layer tile citra terpilih
  seq: 0,
  sensor: "sentinel-2", // sensor dari pencarian terakhir
};

const detectSensor = () => document.querySelector('input[name="d-sensor"]:checked').value;
const maxBoxKm = () => Number($("box-size").value);
const kmPerDegLon = (lat) => 111.32 * Math.cos((lat * Math.PI) / 180);
const KM_PER_DEG_LAT = 110.57;

function boxKm(bounds) {
  const lat = bounds.getCenter().lat;
  return { w: (bounds.getEast() - bounds.getWest()) * kmPerDegLon(lat), h: (bounds.getNorth() - bounds.getSouth()) * KM_PER_DEG_LAT };
}

const boxLabel = (bounds) => {
  const { w, h } = boxKm(bounds);
  return `${num(w, 1)} × ${num(h, 1)} km`;
};

function squareAround(center, km) {
  const dLon = km / 2 / kmPerDegLon(center.lat);
  const dLat = km / 2 / KM_PER_DEG_LAT;
  return L.latLngBounds([center.lat - dLat, center.lng - dLon], [center.lat + dLat, center.lng + dLon]);
}

// Kotak dari titik awal ke titik akhir, sisinya dibatasi maxKm dengan titik awal tetap.
function clampedBox(start, end, maxKm) {
  const dLonMax = maxKm / kmPerDegLon(start.lat);
  const dLatMax = maxKm / KM_PER_DEG_LAT;
  const lng = start.lng + Math.sign(end.lng - start.lng) * Math.min(Math.abs(end.lng - start.lng), dLonMax);
  const lat = start.lat + Math.sign(end.lat - start.lat) * Math.min(Math.abs(end.lat - start.lat), dLatMax);
  return L.latLngBounds(start, [lat, lng]);
}

// Bila ukuran maksimum mengecil (ganti sensor/ukuran), kotak diperkecil di sekitar pusatnya.
function fitBoxToLimit(bounds) {
  const { w, h } = boxKm(bounds);
  const maxKm = maxBoxKm();
  if (w <= maxKm * 1.001 && h <= maxKm * 1.001) return bounds;
  const c = bounds.getCenter();
  const dLon = Math.min(w, maxKm) / 2 / kmPerDegLon(c.lat);
  const dLat = Math.min(h, maxKm) / 2 / KM_PER_DEG_LAT;
  return L.latLngBounds([c.lat - dLat, c.lng - dLon], [c.lat + dLat, c.lng + dLon]);
}

function setBox(bounds) {
  const normal = normalizeBounds(bounds);
  if (!normal.equals(bounds)) {
    // Geser tampilan peta dengan jumlah yang sama agar kotak tetap di bawah kursor.
    const shift = bounds.getCenter().lng - normal.getCenter().lng;
    const c = map.getCenter();
    map.setView([c.lat, c.lng - shift], map.getZoom(), { animate: false });
    bounds = normal;
  }
  if (detect.box) {
    detect.box.setBounds(bounds);
    if (!map.hasLayer(detect.box)) detect.box.addTo(map); // tersembunyi setelah klasifikasi
  } else {
    detect.box = L.rectangle(bounds, BOX_STYLE).addTo(map);
    detect.box.on("mousedown", startMoveBox);
  }
  $("clear-box").hidden = false;
  searchDetectScenes();
}

// ---------- Menggeser kotak ----------
function startMoveBox(e) {
  // Saat mode gambar aktif, event diteruskan ke peta: menarik di dalam kotak = gambar kotak baru.
  if (detect.drawingMode) return;
  L.DomEvent.preventDefault(e.originalEvent);
  // Dimatikan sebelum handler geser peta milik Leaflet menerima mousedown yang sama.
  map.dragging.disable();
  map.getContainer().classList.add("moving-box");
  detect.moving = { start: e.latlng, startPoint: e.containerPoint, bounds: detect.box.getBounds() };
}

function moveBox(e) {
  const m = detect.moving;
  const dLat = e.latlng.lat - m.start.lat;
  const dLng = e.latlng.lng - m.start.lng;
  const b = m.bounds;
  const bounds = L.latLngBounds([b.getSouth() + dLat, b.getWest() + dLng], [b.getNorth() + dLat, b.getEast() + dLng]);
  detect.box.setBounds(bounds);
  $("box-info").textContent = `Kotak: ${boxLabel(bounds)} (maks. ${maxBoxKm()} km). Lepas untuk mencari citra.`;
}

function finishMoveBox(point) {
  const m = detect.moving;
  detect.moving = null;
  map.dragging.enable();
  map.getContainer().classList.remove("moving-box");
  if (point && m.startPoint.distanceTo(point) <= 3) return; // hanya klik, kotak tidak berpindah
  // Lebar kotak dalam km sedikit berubah bila digeser ke lintang lain; jaga tetap di bawah batas.
  setBox(fitBoxToLimit(detect.box.getBounds()));
}

// Bila tombol mouse dilepas di luar peta, geser/gambar tetap diselesaikan.
// Bila tombol mouse dilepas di tempat yang tidak diteruskan Leaflet ke peta (di luar peta, di
// atas panel atau kontrol), geser/gambar diselesaikan di sini. Leaflet sudah memprosesnya lebih
// dulu bila dilepas di peta, sehingga pemeriksaan ini tidak berbuat apa-apa.
document.addEventListener("mouseup", () => {
  setTimeout(() => {
    if (detect.moving) finishMoveBox(null);
    if (detect.drawing) finishDrawing(null, null);
  }, 0);
});

function clearBox() {
  removePreview();
  if (detect.box) map.removeLayer(detect.box);
  detect.box = null;
  $("clear-box").hidden = true;
  detect.scenes = [];
  selectDetectScene(null);
  renderDetectScenes();
}

$("clear-box").addEventListener("click", clearBox);

// Menggambar: tarik untuk kotak bebas, atau klik sekali untuk kotak seukuran pilihan.
// Pratinjau kotak saat menggambar; selalu dibuang sebelum menggambar lagi atau saat batal.
function removePreview() {
  if (detect.drawing?.rect) map.removeLayer(detect.drawing.rect);
  detect.drawing = null;
}

function setDrawing(on) {
  if (!on) removePreview();
  $("draw-box").setAttribute("aria-pressed", on);
  $("draw-box").textContent = on ? "Batal menggambar" : "Gambar kotak";
  map.getContainer().classList.toggle("drawing", on);
  if (on) map.dragging.disable();
  else map.dragging.enable();
  detect.drawingMode = on;
}

$("draw-box").addEventListener("click", () => setDrawing(!detect.drawingMode));

map.on("mousedown", (e) => {
  if (!detect.drawingMode) return;
  L.DomEvent.preventDefault(e.originalEvent); // cegah browser menyeleksi teks saat menarik
  removePreview();
  detect.drawing = { start: e.latlng, startPoint: e.containerPoint, rect: null, last: null };
});

map.on("mousemove", (e) => {
  if (detect.moving) {
    moveBox(e);
    return;
  }
  const d = detect.drawing;
  if (!d) return;
  d.last = e.latlng;
  const bounds = clampedBox(d.start, e.latlng, maxBoxKm());
  if (d.rect) d.rect.setBounds(bounds);
  else d.rect = L.rectangle(bounds, { ...BOX_STYLE, dashArray: null, interactive: false }).addTo(map);
  $("box-info").textContent = `Kotak: ${boxLabel(bounds)} (maks. ${maxBoxKm()} km)`;
});

map.on("mouseup", (e) => {
  if (detect.moving) {
    finishMoveBox(e.containerPoint);
    return;
  }
  if (detect.drawing) finishDrawing(e.latlng, e.containerPoint);
});

// latlng/point null = tombol dilepas di luar peta: pakai posisi terakhir pratinjau, atau batal
// bila mouse belum digerakkan.
function finishDrawing(latlng, point) {
  const d = detect.drawing;
  setDrawing(false); // juga membuang pratinjau
  const end = latlng || d.last;
  if (!end) return;
  const moved = point ? d.startPoint.distanceTo(point) > 6 : true;
  setBox(moved ? clampedBox(d.start, end, maxBoxKm()) : squareAround(end, maxBoxKm()));
}

// ---------- Tanggal & filter ----------
function setDetectRange(days) {
  const end = new Date();
  const start = new Date(end.getTime() - (days - 1) * 86400000);
  $("d-start").value = isoDate(start);
  $("d-end").value = isoDate(end);
}
setDetectRange(30);
$("d-start").max = $("d-end").max = isoDate(new Date());

document.querySelectorAll(".d-presets button").forEach((btn) =>
  btn.addEventListener("click", () => {
    setDetectRange(Number(btn.dataset.days));
    searchDetectScenes();
  })
);
for (const id of ["d-start", "d-end"]) $(id).addEventListener("change", searchDetectScenes);
$("d-cloud").addEventListener("input", () => { $("d-cloud-out").textContent = `${$("d-cloud").value}%`; });
$("d-cloud").addEventListener("change", searchDetectScenes);

function fillBoxSizes() {
  const scheme = SCHEMES[detectSensor()];
  $("box-size").replaceChildren(
    ...scheme.sizes.map(([km, estimate]) => {
      const option = el("option", null, `${km} × ${km} km · ${estimate}`);
      option.value = km;
      option.selected = km === scheme.km;
      return option;
    })
  );
}
fillBoxSizes();

document.querySelectorAll('input[name="d-sensor"]').forEach((radio) =>
  radio.addEventListener("change", () => {
    fillBoxSizes();
    if (detect.box) detect.box.setBounds(fitBoxToLimit(detect.box.getBounds()));
    updateDetectUI();
    searchDetectScenes();
  })
);

$("box-size").addEventListener("change", () => {
  SCHEMES[detectSensor()].km = maxBoxKm();
  if (!detect.box) return;
  const bounds = fitBoxToLimit(detect.box.getBounds());
  if (!bounds.equals(detect.box.getBounds())) setBox(bounds);
  else updateDetectUI();
});

// ---------- Pencarian citra untuk kotak ----------
function pointInRing(lng, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function pointInGeometry(lng, lat, geometry) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  return polygons.some((rings) => pointInRing(lng, lat, rings[0]) && !rings.slice(1).some((hole) => pointInRing(lng, lat, hole)));
}

// Bagian kotak yang tertutup jejak citra, diperkirakan dari grid 12 × 12 titik.
function coverage(feature, bounds) {
  const n = 12;
  let hit = 0;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const lng = bounds.getWest() + ((i + 0.5) / n) * (bounds.getEast() - bounds.getWest());
      const lat = bounds.getSouth() + ((j + 0.5) / n) * (bounds.getNorth() - bounds.getSouth());
      if (pointInGeometry(lng, lat, feature.geometry)) hit++;
    }
  }
  return hit / (n * n);
}

// Urutan: menutupi kotak penuh lebih dulu, lalu awan paling sedikit (optik), lalu paling baru.
function rankScenes(a, b) {
  const fullA = a.coverage >= FULL_COVERAGE, fullB = b.coverage >= FULL_COVERAGE;
  if (fullA !== fullB) return fullA ? -1 : 1;
  if (!fullA && Math.abs(a.coverage - b.coverage) > 0.05) return b.coverage - a.coverage;
  const cloudA = a.feature.properties.cloud_cover ?? 0, cloudB = b.feature.properties.cloud_cover ?? 0;
  if (Math.abs(cloudA - cloudB) >= 5) return cloudA - cloudB;
  return b.feature.properties.datetime.localeCompare(a.feature.properties.datetime);
}

async function searchDetectScenes() {
  updateDetectUI();
  if (!detect.box) return;
  const start = $("d-start").value, end = $("d-end").value;
  if (!start || !end || start > end) {
    $("d-scene-status").textContent = "Periksa tanggal: tanggal awal harus sebelum tanggal akhir.";
    return;
  }
  const sensor = detectSensor();
  const b = detect.box.getBounds();
  if (b.getWest() < -180 || b.getEast() > 180) {
    detect.seq++;
    detect.scenes = [];
    selectDetectScene(null);
    renderDetectScenes();
    $("d-scene-status").textContent = "Kotak melintasi garis bujur 180°. Geser kotak sedikit ke timur atau barat.";
    return;
  }
  const params = new URLSearchParams({
    sensor, start, end,
    bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(5)).join(","),
  });
  if (sensor === "sentinel-2") params.set("cloud", $("d-cloud").value);

  const seq = ++detect.seq;
  $("d-scene-status").textContent = `Mencari citra ${SENSOR_LABELS[sensor]} yang menutupi kotak…`;
  try {
    const data = await apiJson(`/api/search?${params}`);
    if (seq !== detect.seq) return;
    detect.sensor = sensor;
    detect.scenes = data.features
      .map((feature) => ({ feature, coverage: coverage(feature, b) }))
      .filter((s) => s.coverage > 0)
      .sort(rankScenes);
    const keep = detect.scenes.find((s) => s.feature.id === detect.selected?.id);
    selectDetectScene(keep ? keep.feature : detect.scenes[0]?.feature || null);
    renderDetectScenes();
  } catch (err) {
    if (seq === detect.seq) $("d-scene-status").textContent = `Pencarian gagal: ${err.message}`;
  }
}

function renderDetectScenes() {
  const list = detect.scenes.slice(0, DETECT_SCENE_LIMIT);
  // Citra terpilih selalu ditampilkan, walaupun peringkatnya di luar daftar teratas.
  const chosen = detect.scenes.find((s) => s.feature.id === detect.selected?.id);
  if (chosen && !list.includes(chosen)) list.push(chosen);
  if (!detect.box) {
    $("d-scene-status").textContent = "Gambar kotak dulu; citra yang menutupi kotak dicari otomatis.";
  } else if (!detect.scenes.length) {
    const tip = detect.sensor === "sentinel-2" ? " Coba perpanjang rentang tanggal atau naikkan batas awan." : " Coba perpanjang rentang tanggal.";
    $("d-scene-status").textContent = `Tidak ada citra ${SENSOR_LABELS[detect.sensor]} yang menutupi kotak.${tip}`;
  } else {
    const shown = Math.min(detect.scenes.length, DETECT_SCENE_LIMIT);
    const more = detect.scenes.length > shown ? ` (${shown} terbaik ditampilkan)` : "";
    $("d-scene-status").textContent = `${detect.scenes.length} citra menutupi kotak${more}. Yang terbaik sudah dipilih.`;
  }
  $("d-scenes").replaceChildren(
    ...list.map((s) => {
      const p = s.feature.properties;
      const card = el("label", "d-scene");
      const radio = el("input");
      radio.type = "radio";
      radio.name = "d-scene";
      radio.value = s.feature.id;
      radio.checked = s.feature.id === detect.selected?.id;
      radio.addEventListener("change", () => selectDetectScene(s.feature));
      card.append(radio);
      if (p.thumbnail) {
        const thumb = el("img", "thumb");
        thumb.src = p.thumbnail;
        thumb.alt = "";
        thumb.loading = "lazy";
        card.append(thumb);
      }
      const info = el("div", "info");
      const time = el("div", "time", `${p.datetime.slice(0, 10)} · ${p.datetime.slice(11, 16)} UTC`);
      if (s === detect.scenes[0]) time.append(el("span", "best", "terbaik"));
      const cover = el("span", s.coverage >= FULL_COVERAGE ? null : "partial", `cakupan ${Math.round(s.coverage * 100)}%`);
      const meta = el("div", "meta", `${sceneMetaFor(detect.sensor, p)} · `);
      meta.append(cover);
      info.append(time, meta);
      info.title = s.feature.id;
      card.append(info);
      return card;
    })
  );
  updateDetectUI();
}

function sceneMetaFor(sensor, p) {
  const platform = (p.platform || "").replace("sentinel-", "S").toUpperCase();
  if (sensor === "sentinel-2") {
    return [platform, p.tile, p.cloud_cover == null ? "" : `awan ${Math.round(p.cloud_cover)}%`].filter(Boolean).join(" · ");
  }
  const orbit = p.orbit_state === "ascending" ? "↑ naik" : p.orbit_state === "descending" ? "↓ turun" : "";
  return [platform, p.mode, orbit].filter(Boolean).join(" · ");
}

// Citra terpilih langsung ditampilkan di peta sebagai konteks.
function selectDetectScene(feature) {
  if (detect.layer) map.removeLayer(detect.layer);
  detect.layer = null;
  detect.selected = feature;
  if (feature) {
    const url = tileUrlFor(detect.sensor, feature);
    if (url) detect.layer = sceneTileLayer(url, L.geoJSON(feature).getBounds(), detect.sensor).addTo(map);
    if (detect.box && map.hasLayer(detect.box)) detect.box.bringToFront();
    if (detectLayer && map.hasLayer(detectLayer)) detectLayer.bringToFront();
  }
  updateDetectUI();
}

function updateDetectUI() {
  const sensor = detectSensor();
  const ready = Boolean(detect.box && detect.selected && detect.sensor === sensor);
  const scheme = SCHEMES[sensor];
  $("scheme-chip").textContent = scheme.chip;
  $("d-cloud-field").hidden = sensor !== "sentinel-2";
  $("method-sar").hidden = sensor === "sentinel-2";
  $("method-optic").hidden = sensor === "sentinel-1";
  $("detect-btn").textContent = scheme.run;
  $("detect-btn").disabled = !ready || detectBusy;
  $("detect-run-hint").textContent = scheme.hint;
  if (detect.box && !detect.drawing) {
    $("box-info").textContent = `Kotak: ${boxLabel(detect.box.getBounds())} (maks. ${maxBoxKm()} km). ` +
      "Tarik kotak untuk memindahkannya; gambar ulang untuk mengganti ukuran.";
  }
}

$("detect-form").addEventListener("submit", (e) => {
  e.preventDefault();
  if (!detect.box || !detect.selected || detectBusy) return;
  const b = detect.box.getBounds();
  const bbox = [
    Math.max(-180, b.getWest()), Math.max(-90, b.getSouth()),
    Math.min(180, b.getEast()), Math.min(90, b.getNorth()),
  ];
  runJob(detect.sensor, detect.selected, bbox, maxBoxKm());
});

function clearDetection() {
  for (const layer of [detectLayer, mxLayers.overlay]) if (layer) map.removeLayer(layer);
  detectLayer = mxLayers.overlay = null;
  for (const id of ["detect-summary", "detect-clear", "mx-overlay", "mx-classes", "mx-downloads", "detect-progress"]) {
    $(id).hidden = true;
  }
  setDetectStatus("");
  // Kotak analisis disembunyikan setelah klasifikasi; tampilkan lagi saat hasil dihapus.
  if (detect.box && !map.hasLayer(detect.box)) detect.box.addTo(map);
}

$("detect-clear").addEventListener("click", clearDetection);

// ---------- Kartu progres ----------
// Satu kartu progres untuk satu pekerjaan: tahap, batang progres, waktu berjalan.
function createProgress(title, labels, estimate) {
  const started = Date.now();
  const stepStarted = [];
  const stepEnded = [];
  let current = -1;
  $("progress-title").textContent = title;
  $("detect-progress").hidden = false;
  $("detect-progress").classList.remove("failed");
  const items = labels.map((label) => {
    const li = el("li", "pending");
    li.append(el("span", "step-icon"), el("span", "step-label", label), el("span", "step-time", ""));
    return li;
  });
  $("progress-steps").replaceChildren(...items);

  function render() {
    const now = Date.now();
    $("progress-elapsed").textContent = duration((now - started) / 1000) + (estimate ? ` · perkiraan ${estimate}` : "");
    $("progress-count").textContent = current >= 0 ? `tahap ${Math.min(current + 1, labels.length)} / ${labels.length}` : "menunggu giliran";
    const done = items.filter((li) => li.classList.contains("done")).length;
    const share = Math.min(100, ((done + (current >= 0 && current < labels.length ? 0.5 : 0)) / labels.length) * 100);
    $("progress-fill").style.width = `${share}%`;
    $("detect-progress").querySelector(".progress-bar").setAttribute("aria-valuenow", Math.round(share));
    items.forEach((li, i) => {
      if (stepStarted[i] == null) return;
      li.querySelector(".step-time").textContent = duration(((stepEnded[i] ?? now) - stepStarted[i]) / 1000);
    });
  }

  function setStep(index) {
    if (index === current) return render();
    const now = Date.now();
    for (let i = 0; i < items.length; i++) {
      if (i < index) {
        if (stepStarted[i] == null) stepStarted[i] = stepEnded[i - 1] ?? now;
        if (stepEnded[i] == null) stepEnded[i] = now;
        items[i].className = "done";
      } else if (i === index) {
        if (stepStarted[i] == null) stepStarted[i] = now;
        items[i].className = "active";
      } else {
        items[i].className = "pending";
      }
    }
    current = index;
    render();
  }

  const timer = setInterval(render, 1000);
  render();
  return {
    setStep,
    finish() {
      clearInterval(timer);
      setStep(items.length);
      $("detect-progress").hidden = true;
    },
    fail() {
      clearInterval(timer);
      if (current >= 0 && current < items.length) {
        stepEnded[current] = Date.now();
        items[current].className = "failed";
      }
      render();
      $("detect-progress").classList.add("failed");
      $("progress-title").textContent = "Proses gagal";
    },
  };
}

// ---------- Hasil klasifikasi (MariNeXt & U-Net SAR) ----------
const MX_OIL_STYLE = { color: "#ff00ff", weight: 2, fillColor: "#ff00ff", fillOpacity: 0.2 };

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const duration = (s) => (s >= 60 ? `${Math.floor(s / 60)} mnt ${Math.round(s % 60)} dtk` : `${Math.round(s)} dtk`);

async function apiJson(url, options) {
  const resp = await fetch(url, options);
  const data = await resp.json();
  if (!resp.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${resp.status}`);
  return data;
}

// Klasifikasi berjalan di latar belakang server; tahap dan status diambil berkala sampai selesai.
async function runJob(sensor, scene, bbox, maxKm) {
  const scheme = SCHEMES[sensor];
  clearDetection();
  detectBusy = true;
  updateDetectUI();
  let progress = null;
  try {
    let job = await apiJson(scheme.api, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scene_id: scene.id, bbox, max_km: maxKm }),
    });
    const id = job.job_id;
    const estimate = scheme.sizes.find(([km]) => km === maxKm)?.[1];
    progress = createProgress(`${scheme.model} · citra ${scene.properties.datetime.slice(0, 10)}`, job.stages, estimate);
    while (job.status !== "done") {
      if (job.status === "error") throw new Error(job.error);
      progress.setStep(job.stage_index);
      await sleep(2000);
      job = await apiJson(`/api/jobs/${id}`);
    }
    progress.finish();
    showResult(job.result, job.elapsed_s, scheme);
    // Kotak analisis tidak lagi diperlukan di peta setelah klasifikasi selesai.
    if (detect.box) {
      map.removeLayer(detect.box);
      unstashLayer(detect.box);
    }
    // Pekerjaan bisa selesai saat pengguna sedang di panel lain: hasil disimpan, tampil saat kembali.
    if ($("detect-panel").hidden) setPanelLayers("menu-detect", false);
  } catch (err) {
    progress?.fail();
    setDetectStatus(`Klasifikasi gagal: ${err.message}`, true);
  } finally {
    detectBusy = false;
    updateDetectUI();
  }
}

function showResult(r, elapsed, scheme) {
  const oil = r.oil.features;
  // MariNeXt: awan & bayangan awan dimasker; bila masker gagal, pengguna perlu tahu.
  const cloudWarning = r.cloud && !r.cloud.applied ? ` Masker awan tidak diterapkan: ${r.cloud.error}` : "";
  setDetectStatus(
    (oil.length
      ? `Oil Spill terdeteksi: ${num(r.oil_area_km2, 3)} km² dalam ${oil.length} petak.`
      : "Tidak ada piksel Oil Spill di area ini.") + cloudWarning,
    Boolean(cloudWarning)
  );

  const stats = [
    ["Model", r.polarization ? `${r.model} · ${r.polarization}` : r.model],
    ["Resolusi", `${num(r.resolution_m, 0)} m`],
    ["Kotak dianalisis", boxLabel(L.latLngBounds([r.aoi[1], r.aoi[0]], [r.aoi[3], r.aoi[2]]))],
    ["Area dianalisis", `${num(r.valid_km2, 1)} km²`],
    ["Luas Oil Spill", `${num(r.oil_area_km2, 3)} km²`],
    ["Waktu proses", duration(elapsed)],
  ];
  if (r.tiles) stats.splice(2, 0, ["Potongan U-Net", String(r.tiles)]);
  if (r.cloud) {
    stats.splice(-1, 0, r.cloud.applied
      ? ["Awan & bayangan", `${num(r.cloud.area_km2, 2)} km² (Oil Spill dibuang ${num(r.cloud.oil_removed_km2, 3)} km²)`]
      : ["Masker awan", "tidak diterapkan"]);
  }
  // Nama produk panjang: satu baris penuh, dipecah di garis bawah agar tetap di dalam kotak.
  const product = el("div", "wide");
  const productName = el("dd", "product");
  productName.append(...r.product.split("_").flatMap((part, i) => (i ? [document.createElement("wbr"), `_${part}`] : [part])));
  productName.title = r.product;
  product.append(el("dt", null, "Produk"), productName);
  $("detect-summary").replaceChildren(
    product,
    ...stats.map(([term, value]) => {
      const row = el("div");
      row.append(el("dt", null, term), el("dd", null, value));
      return row;
    })
  );
  $("detect-summary").hidden = false;

  // Peta kelas sebagai gambar (warna sama dengan legenda dataset; area tanpa data transparan).
  mxLayers.overlay = L.imageOverlay(r.overlay.url, r.overlay.bounds, {
    opacity: $("mx-opacity").value / 100, className: "mx-classes", interactive: false,
  });
  if ($("mx-show").checked) mxLayers.overlay.addTo(map);
  $("mx-overlay").hidden = false;

  const rows = r.classes.filter((c) => c.area_km2 >= 0.001).sort((a, b) => b.area_km2 - a.area_km2);
  $("mx-classes").querySelector("tbody").replaceChildren(
    ...rows.map((c) => {
      const tr = el("tr", c.id === r.oil_class ? "oil" : null);
      const name = el("td");
      const dot = el("span", "dot");
      dot.style.background = c.color;
      name.append(dot, el("span", null, c.name), el("span", "name-id", c.name_id));
      tr.append(name, el("td", null, num(c.area_km2, 3)), el("td", null, num(c.percent, 1)));
      return tr;
    })
  );
  $("mx-classes-head").textContent = scheme.classHead;
  $("mx-classes").hidden = false;

  const links = [
    ["classes.tif", "Peta kelas", "GeoTIFF"],
    ["oil_spill_prob.tif", "Probabilitas Oil Spill", "GeoTIFF"],
    ["oil_spill.geojson", "Poligon Oil Spill", "GeoJSON"],
    ["cloud_mask.tif", "Masker awan", "GeoTIFF"],
  ].filter(([file]) => r.downloads[file]).map(([file, label, type]) => {
    const a = el("a", "dl");
    a.href = r.downloads[file];
    a.download = "";
    a.title = `Unduh ${label} (${file})`;
    a.innerHTML = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 19h14"/></svg>';
    a.append(el("span", "dl-name", label), el("span", "dl-type", type));
    return a;
  });
  $("mx-downloads").replaceChildren(el("h3", null, "Unduh hasil"), ...links);
  $("mx-downloads").hidden = false;
  $("detect-clear").hidden = false;

  // Poligon Oil Spill di atas peta kelas, bisa diklik; tampil/sembunyi lewat sakelar.
  detectLayer = L.geoJSON(r.oil, {
    style: MX_OIL_STYLE,
    onEachFeature: (f, layer) => layer.bindPopup(() => mxPopup(f.properties, scheme.model), { maxWidth: 280 }),
  });
  if ($("oil-show").checked) detectLayer.addTo(map);
  $("oil-show").disabled = !oil.length;
}

function mxPopup(p, model) {
  const box = el("div", "popup");
  box.append(el("h3", null, `#${p.id} Oil Spill (${model})`));
  const table = el("table");
  for (const [k, v] of [
    ["Luas", `${num(p.area_km2, 4)} km²`],
    ["Probabilitas rata-rata", `${num(p.prob_mean * 100, 0)}%`],
    ["Probabilitas maksimum", `${num(p.prob_max * 100, 0)}%`],
  ]) {
    const tr = el("tr");
    tr.append(el("td", null, k), el("td", null, v));
    table.append(tr);
  }
  box.append(table);
  return box;
}

$("mx-show").addEventListener("change", () => {
  if (!mxLayers.overlay) return;
  if ($("mx-show").checked) {
    mxLayers.overlay.addTo(map);
    if (detectLayer && map.hasLayer(detectLayer)) detectLayer.bringToFront();
  } else {
    map.removeLayer(mxLayers.overlay);
  }
});

$("oil-show").addEventListener("change", () => {
  if (!detectLayer) return;
  if ($("oil-show").checked) detectLayer.addTo(map).bringToFront();
  else map.removeLayer(detectLayer);
});

$("mx-opacity").addEventListener("input", () => {
  $("mx-opacity-out").textContent = `${$("mx-opacity").value}%`;
  if (mxLayers.overlay) mxLayers.overlay.setOpacity($("mx-opacity").value / 100);
});

// ---------- Pencarian lokasi ----------
// Nama tempat lewat /api/geocode (Nominatim OpenStreetMap, dicari saat Enter, bukan tiap ketikan,
// sesuai aturan pakai Nominatim); koordinat "lat, lon" langsung dikenali tanpa permintaan.
const geo = { results: [], active: -1, seq: 0 };
const GEO_POINT_ZOOM = 11;

function parseLatLon(text) {
  const m = text.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  let lat = Number(m[1]), lon = Number(m[2]);
  if (Math.abs(lat) > 90 && Math.abs(lon) <= 90) [lat, lon] = [lon, lat]; // kemungkinan tertulis "lon, lat"
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { name: `${lat.toFixed(5)}, ${lon.toFixed(5)}`, type: "koordinat", lat, lon, bbox: null };
}

function showGeoResults(items, note) {
  geo.results = items;
  geo.active = items.length ? 0 : -1;
  const list = $("geo-results");
  list.replaceChildren(
    ...items.map((r, i) => {
      const li = el("li", null, r.name);
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === geo.active);
      if (r.type) li.append(el("span", "type", r.type));
      li.addEventListener("mousedown", (e) => {
        e.preventDefault(); // jangan biarkan input kehilangan fokus sebelum klik diproses
        goToPlace(r);
      });
      return li;
    }),
    ...(note ? [el("li", "note", note)] : [])
  );
  list.hidden = !items.length && !note;
  $("geo-q").setAttribute("aria-expanded", !list.hidden);
}

function highlightGeo(index) {
  geo.active = index;
  [...$("geo-results").querySelectorAll("li[role=option]")].forEach((li, i) => li.setAttribute("aria-selected", i === index));
}

function goToPlace(r) {
  showGeoResults([]);
  $("geo-q").value = r.name;
  if (r.bbox && (r.bbox[2] - r.bbox[0] > 0.01 || r.bbox[3] - r.bbox[1] > 0.01)) {
    map.fitBounds([[r.bbox[1], r.bbox[0]], [r.bbox[3], r.bbox[2]]], { maxZoom: 13 });
  } else {
    map.setView([r.lat, r.lon], Math.max(map.getZoom(), GEO_POINT_ZOOM));
  }
}

$("geo-search").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!$("geo-results").hidden && geo.active >= 0 && geo.results[geo.active]) {
    goToPlace(geo.results[geo.active]);
    return;
  }
  const q = $("geo-q").value.trim();
  if (!q) return;
  const coord = parseLatLon(q);
  if (coord) {
    goToPlace(coord);
    return;
  }
  const seq = ++geo.seq;
  showGeoResults([], "Mencari…");
  try {
    const data = await apiJson(`/api/geocode?q=${encodeURIComponent(q)}`);
    if (seq !== geo.seq) return;
    showGeoResults(data.results, data.results.length ? null : "Lokasi tidak ditemukan.");
  } catch (err) {
    if (seq === geo.seq) showGeoResults([], `Pencarian gagal: ${err.message}`);
  }
});

$("geo-q").addEventListener("input", () => {
  geo.seq++;
  showGeoResults([]); // hasil lama tidak lagi sesuai teks; tekan Enter untuk mencari lagi
});

$("geo-q").addEventListener("keydown", (e) => {
  const n = geo.results.length;
  if (e.key === "ArrowDown" && n) {
    e.preventDefault();
    highlightGeo((geo.active + 1) % n);
  } else if (e.key === "ArrowUp" && n) {
    e.preventDefault();
    highlightGeo((geo.active - 1 + n) % n);
  } else if (e.key === "Escape") {
    showGeoResults([]);
  }
});

$("geo-q").addEventListener("blur", () => setTimeout(() => showGeoResults([]), 150));
