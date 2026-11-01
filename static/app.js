const MUSH_COLOR = { 3: "#86cb66", 4: "#219b51" };

const map = L.map("map", { zoomControl: true }).setView([49.75, 15.45], 7);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "© OpenStreetMap contributors",
}).addTo(map);

const $ = (id) => document.getElementById(id);
const metaEl = $("meta");
const statusEl = $("status");
const formEl = $("ageForm");
const opSlider = $("opSlider");
const opVal = $("opVal");

let currentLayer = null;
let currentAge = null;

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

function showAge(age) {
  currentAge = age;
  if (currentLayer) {
    map.removeLayer(currentLayer);
    currentLayer = null;
  }
  statusEl.textContent = "Načítám…";
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
        statusEl.textContent = `Pro vĕk "${formEl.querySelector(`input[value="${age}"]`).nextSibling.textContent.trim()}" nebyly nalezeny žádné plochy (viz časová pečeť mapy hub).`;
        statusEl.classList.add("empty");
      } else {
        const lab = formEl.querySelector(`input[value="${age}"]`).nextSibling.textContent.trim();
        statusEl.textContent = `Zobrazeno ${n} ploch pro vĕk "${lab}".`;
        statusEl.classList.remove("empty");
      }
    })
    .catch((err) => {
      statusEl.textContent = "Chyba při načítání dat.";
      statusEl.classList.add("empty");
      console.error(err);
    });
}

function buildMenu(ages) {
  formEl.innerHTML = "";
  const none = document.createElement("label");
  const rbNone = document.createElement("input");
  rbNone.type = "radio"; rbNone.name = "age"; rbNone.value = "none";
  rbNone.checked = true;
  rbNone.onchange = () => {
    if (currentLayer) { map.removeLayer(currentLayer); currentLayer = null; }
    currentAge = null;
    statusEl.textContent = "Žádná vrstva není vybrána.";
    statusEl.classList.remove("empty");
  };
  none.appendChild(rbNone);
  none.append(document.createTextNode("Žádná (základní mapa)"));
  formEl.appendChild(none);

  ages.forEach((a) => {
    const lab = document.createElement("label");
    const rb = document.createElement("input");
    rb.type = "radio"; rb.name = "age"; rb.value = a.id;
    rb.onchange = () => showAge(a.id);
    lab.appendChild(rb);
    lab.append(document.createTextNode(`${a.label} (${a.count} ploch)`));
    formEl.appendChild(lab);
  });
}

opSlider.addEventListener("input", (e) => setOpacity(e.target.value));

fetch("/api/meta")
  .then((r) => r.json())
  .then((meta) => {
    const [w, s, e, n] = meta.mushBounds;
    metaEl.textContent = `Data hub: ${meta.timeLabel || "neznámo"}. WMTS matice ${meta.matrix} (JTSK:5514).`;
    map.fitBounds([[s, w], [n, e]], { padding: [40, 40] });
    buildMenu(meta.ages);
    statusEl.textContent = "Připraveno — vyberte vĕkovou třídu.";
  })
  .catch((err) => {
    statusEl.textContent = "Nepodařilo se načíst metadata.";
    statusEl.classList.add("empty");
    console.error(err);
  });
