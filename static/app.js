const MUSH_COLOR = { 3: "#86cb66", 4: "#219b51" };

// Lesní vĕk dle indexu (odpovídá souborům age_<id>.geojson a forest_age_index v mushrooms.json)
const FOREST_LABELS = {
  0: "1–20 let", 1: "21–40 let", 2: "41–60 let", 3: "61–80 let",
  4: "81–100 let", 5: "101–120 let", 6: "121–140 let", 7: "141 a více let",
};

const map = L.map("map", { zoomControl: true }).setView([49.75, 15.45], 7);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "© OpenStreetMap contributors",
}).addTo(map);

const $ = (id) => document.getElementById(id);
const metaEl = $("meta");
const statusEl = $("status");
const opSlider = $("opSlider");
const opVal = $("opVal");

const listView = $("mushroomListView");
const detailView = $("mushroomDetailView");
const mushListEl = $("mushList");
const mushDetailEl = $("mushDetail");
const mushAgeInfoEl = $("mushAgeInfo");
const backBtn = $("backToList");

let currentLayer = null;
let currentAge = null;

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function styleFor(feature) {
  const c = feature.properties && feature.properties.mushClass;
  const color = MUSH_COLOR[c] || "#888";
  return {
    color: color,
    weight: 0,
    fillColor: color,
    fillOpacity: opSlider.value / 100,
  };
}

function onEachFeature(feature, layer) {
  const p = feature.properties || {};
  const label = p.mushLabel || p.mushClass;
  layer.bindPopup(
    `<strong>${p.ageLabel || "lesní vĕk"}</strong><br>` +
    `Výskyt hub: <strong>${label}</strong>`,
    { direction: "auto" }
  );
}

function setOpacity(v) {
  opVal.textContent = v;
  if (currentLayer) {
    currentLayer.eachLayer((l) => l.setStyle({ fillOpacity: v / 100 }));
  }
}

function removeLayer() {
  if (currentLayer) {
    map.removeLayer(currentLayer);
    currentLayer = null;
  }
  currentAge = null;
}

/* Načte a zobrazí vrstvu pro daný věk lesa. label se zobrazí v informaci. */
function showAgeLayer(age, label) {
  currentAge = age;
  if (currentLayer) {
    map.removeLayer(currentLayer);
    currentLayer = null;
  }
  statusEl.textContent = "Načítám…";
  statusEl.classList.remove("empty");
  fetch(`/data/age_${age}.geojson`)
    .then((r) => {
      if (!r.ok) return { type: "FeatureCollection", features: [] };
      return r.json();
    })
    .then((geojson) => {
      currentLayer = L.geoJSON(geojson, {
        style: styleFor,
        onEachFeature: onEachFeature,
      }).addTo(map);
      const n = geojson.features.length;
      if (n === 0) {
        statusEl.textContent = `Pro ${label || "věk " + age} nebyly nalezeny žádné plochy.`;
        statusEl.classList.add("empty");
      } else {
        statusEl.textContent = `Zobrazeno ${n} ploch pro ${label || "věk " + age}.`;
        statusEl.classList.remove("empty");
      }
    })
    .catch((err) => {
      statusEl.textContent = "Chyba při načítání dat.";
      statusEl.classList.add("empty");
      console.error(err);
    });
}

function showMushroom(m) {
  showAgeLayer(m.forest_age_index, m.name);
  const ageLabel = FOREST_LABELS[m.forest_age_index] ?? `vĕk ${m.forest_age_index}`;
  mushAgeInfoEl.textContent = `Na mapě se zobrazuje lesní vĕk: ${ageLabel}.`;
  mushDetailEl.innerHTML = `
    <img src="/static/${escapeHtml(m.image_url)}" alt="${escapeHtml(m.name)}" class="mush-img" onerror="this.style.display='none'" />
    <h3>${escapeHtml(m.name)}</h3>
    <p><strong>Jedlost:</strong> ${escapeHtml(m.edibility)}</p>
    <p>${escapeHtml(m.description)}</p>
  `;
  listView.style.display = "none";
  detailView.style.display = "block";
}

function backToList() {
  removeLayer();
  statusEl.textContent = "Vyberte houbu v seznamu.";
  statusEl.classList.remove("empty");
  mushAgeInfoEl.textContent = "";
  mushDetailEl.innerHTML = "";
  listView.style.display = "block";
  detailView.style.display = "none";
}

function buildMushroomMenu(mushrooms) {
  mushListEl.innerHTML = "";
  mushrooms.forEach((m) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "mush-card";
    card.onclick = () => showMushroom(m);
    card.innerHTML = `
      <img src="/static/${escapeHtml(m.image_url)}" alt="${escapeHtml(m.name)}" class="mush-card-img" onerror="this.style.display='none'" />
      <div class="mush-card-body">
        <div class="mush-card-name">${escapeHtml(m.name)}</div>
      </div>
    `;
    mushListEl.appendChild(card);
  });
}

opSlider.addEventListener("input", (e) => setOpacity(e.target.value));
backBtn.addEventListener("click", backToList);

fetch("/api/meta")
  .then((r) => r.json())
  .then((meta) => {
    const [w, s, e, n] = meta.mushBounds;
    metaEl.textContent = `Data hub: ${meta.timeLabel || "neznámo"}. WMTS matice ${meta.matrix} (JTSK:5514).`;
    map.fitBounds([[s, w], [n, e]], { padding: [40, 40] });
    statusEl.textContent = "Připraveno — vyberte houbu.";
  })
  .catch((err) => {
    statusEl.textContent = "Nepodařilo se načíst metadata.";
    statusEl.classList.add("empty");
    console.error(err);
  });

fetch("/static/mushrooms.json")
  .then((r) => {
    if (!r.ok) throw new Error("seznam hub není dostupný");
    return r.json();
  })
  .then((mushrooms) => {
    buildMushroomMenu(mushrooms);
  })
  .catch((err) => {
    statusEl.textContent = "Nepodařilo se načíst seznam hub.";
    statusEl.classList.add("empty");
    console.error(err);
  });
