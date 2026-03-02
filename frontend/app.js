const presetQueries = [
  "Kadikoy civarinda sessiz ders calisabilecegim yer",
  "Besiktas'ta vegan ve sakin bir kafe",
  "Sisli'de priz ve wifi olan coworking",
];

const chipsEl = document.getElementById("chips");
const form = document.getElementById("searchForm");
const queryEl = document.getElementById("query");
const searchBtn = document.getElementById("searchBtn");
const saveProfileBtn = document.getElementById("saveProfileBtn");
const userIdEl = document.getElementById("userId");
const profileTagsEl = document.getElementById("profileTags");
const budgetLevelEl = document.getElementById("budgetLevel");
const homeAreaEl = document.getElementById("homeArea");
const resultsEl = document.getElementById("results");
const metaEl = document.getElementById("meta");

const map = L.map("map").setView([41.02, 29.02], 11);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: '&copy; OpenStreetMap contributors',
}).addTo(map);

let markerLayer = L.layerGroup().addTo(map);
let lastQueryText = "";
let lastQueryKey = "";
let lastResultIds = [];
let recentResultIds = [];

function normalizeQuery(text) {
  return (text || "")
    .toLowerCase()
    .replaceAll("ç", "c")
    .replaceAll("ğ", "g")
    .replaceAll("ı", "i")
    .replaceAll("ö", "o")
    .replaceAll("ş", "s")
    .replaceAll("ü", "u");
}

function detectSignalTags(queryText) {
  const q = normalizeQuery(queryText);
  const tags = [];
  if (q.includes("sessiz") || q.includes("sakin") || q.includes("quiet")) tags.push("sessiz");
  if (q.includes("kalabalik") || q.includes("gurultu") || q.includes("crowded") || q.includes("noisy")) tags.push("kalabalik");
  return tags;
}

function renderChips() {
  presetQueries.forEach((text) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = text;
    btn.onclick = () => {
      queryEl.value = text;
      queryEl.focus();
    };
    chipsEl.appendChild(btn);
  });
}

async function sendFeedback(placeId, helpful) {
  try {
    const signal_tags = detectSignalTags(lastQueryText);
    const user_id = userIdEl.value.trim() || null;
    await fetch("/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ place_id: placeId, helpful, signal_tags, user_id }),
    });
  } catch (_e) {
    // Keep UX non-blocking when DB is not configured.
  }
}

function parseTags(raw) {
  return (raw || "")
    .split(",")
    .map((x) => x.trim().toLowerCase())
    .filter(Boolean);
}

async function saveProfile() {
  const userId = userIdEl.value.trim();
  if (!userId) {
    alert("Profil kaydi icin kullanici ID gir.");
    return;
  }

  const tags = parseTags(profileTagsEl.value);
  const budgetRaw = budgetLevelEl.value.trim();
  const budget_level = budgetRaw ? Number(budgetRaw) : null;
  const home_area = homeAreaEl.value.trim() || null;

  try {
    const res = await fetch("/users/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, tags, budget_level, home_area }),
    });
    if (!res.ok) throw new Error("profile_save_failed");
    alert("Profil kaydedildi.");
  } catch (_e) {
    alert("Profil kaydi basarisiz. DB baglantisini kontrol et.");
  }
}

async function runSearchRequest(payload) {
  const res = await fetch("/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return await res.json();
}

function renderResults(data) {
  resultsEl.innerHTML = "";
  markerLayer.clearLayers();

  const results = data.results || [];
  const markers = [];

  const effectiveTags = (data.meta?.effective_user_tags || []).join(",");
  metaEl.textContent = `parser: ${data.meta?.parser_source || "?"} | profil: ${data.meta?.intent_profile || "-"} | summary: ${data.meta?.summary_source || "?"} | storage: ${data.meta?.storage_source || "?"} | aday: ${data.meta?.total_candidates || 0} | etiket: ${effectiveTags || "-"}`;

  if (!results.length) {
    resultsEl.innerHTML = "<p>Sonuc bulunamadi.</p>";
    return;
  }

  results.forEach((item, idx) => {
    const p = item.place;
    const card = document.createElement("article");
    card.className = "card";

    const reasons = (item.reasons || []).join(" • ");
    const summary = item.recommendation_summary || "Bu mekan sorguna genel olarak uyuyor.";
    const quietnessLabel = item.place.quietness_level === 3 ? "Yuksek" : item.place.quietness_level === 2 ? "Orta" : "Dusuk";
    card.innerHTML = `
      <h3>${idx + 1}. ${p.name}</h3>
      <div class="meta">${p.area} • ${p.category} • ${p.is_open_now ? "Acik" : "Kapali"}</div>
      <div class="summary">${summary}</div>
      <div class="scores">
        <span class="score">Final: ${item.final_score}</span>
        <span class="score">Local: ${item.local_score}</span>
        <span class="score">Yerel Orani: ${Math.round((item.local_authenticity_score || 0) * 100)}%</span>
        <span class="score">Google: ${item.general_score}</span>
        <span class="score">Mesafe: ${item.distance_m ?? "?"}m</span>
        <span class="score">Sessizlik: ${quietnessLabel}</span>
      </div>
      <div class="meta">${reasons}</div>
      <div class="actions">
        <button type="button" data-fb="up">Iyi oneriydi</button>
        <button type="button" data-fb="down">Uymadi</button>
      </div>
    `;

    card.querySelector('[data-fb="up"]').onclick = () => sendFeedback(p.id, true);
    card.querySelector('[data-fb="down"]').onclick = () => sendFeedback(p.id, false);

    resultsEl.appendChild(card);

    const marker = L.marker([p.latitude, p.longitude]).bindPopup(`<b>${p.name}</b><br/>Final: ${item.final_score}`);
    markerLayer.addLayer(marker);
    markers.push(marker);
  });

  if (markers.length) {
    const group = L.featureGroup(markers);
    map.fitBounds(group.getBounds().pad(0.2));
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = queryEl.value.trim();
  if (!query) return;
  lastQueryText = query;
  const queryKey = normalizeQuery(query);

  searchBtn.disabled = true;
  searchBtn.textContent = "Araniyor...";

  try {
    const userId = userIdEl.value.trim();
    const tags = parseTags(profileTagsEl.value);
    const sameQueryExclude = queryKey === lastQueryKey ? lastResultIds.slice(0, 8) : [];
    const globalExclude = recentResultIds.slice(0, 8);
    const excludeIds = [...new Set([...sameQueryExclude, ...globalExclude])];
    const payload = {
      query,
      user_id: userId || null,
      user_tags: tags,
      exclude_place_ids: excludeIds,
      max_results: 6,
    };
    let data = await runSearchRequest(payload);
    if ((data.results || []).length === 0 && excludeIds.length > 0) {
      data = await runSearchRequest({ ...payload, exclude_place_ids: [] });
    }
    renderResults(data);
    lastQueryKey = queryKey;
    lastResultIds = (data.results || []).map((x) => x.place?.id).filter(Boolean);
    recentResultIds = [...lastResultIds, ...recentResultIds].filter(Boolean).slice(0, 24);
  } catch (_err) {
    resultsEl.innerHTML = "<p>Arama sirasinda hata olustu.</p>";
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = "AI ile Bul";
  }
});

renderChips();
saveProfileBtn.addEventListener("click", saveProfile);
