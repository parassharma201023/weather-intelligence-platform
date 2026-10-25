
const API_BASE = (
  window.WEATHER_API_BASE || "http://127.0.0.1:8000"
).replace(/\/$/, "");

const $ = (id) => document.getElementById(id);

const stateSelect = $("stateSelect");
const districtSearch = $("districtSearch");
const resetFilters = $("resetFilters");
const refreshButton = $("refreshButton");
const weatherTableBody = $("weatherTableBody");
const forecastDistrict = $("forecastDistrict");
const forecastCards = $("forecastCards");

let allWeather = [];
let visibleWeather = [];
let indiaMap = null;
let weatherLayer = null;
let stateBoundaryLayer = null;
let forecastRequest = 0;
let searchTimer = null;

function showMessage(id, message) {
  const element = $(id);
  if (element) element.textContent = message;
}

function setApiStatus(message, healthy = false) {
  const status = $("apiStatus");
  const sideStatus = $("sideApiStatus");
  const dot = document.querySelector(".status-dot");

  if (status) status.textContent = message;
  if (sideStatus) sideStatus.textContent = healthy ? "Connected" : "Offline";

  if (dot) {
    dot.style.background = healthy ? "#34d399" : "#f87171";
  }
}

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "—";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  })[character]);
}

async function fetchJson(url) {
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`API request failed: HTTP ${response.status}`);
  }

  return response.json();
}

function numeric(items, key) {
  return items
    .map((item) => item[key])
    .filter(
      (value) =>
        value !== null &&
        value !== undefined &&
        value !== "" &&
        Number.isFinite(Number(value))
    )
    .map(Number);
}

function average(items, key) {
  const values = numeric(items, key);

  return values.length
    ? values.reduce((sum, value) => sum + value, 0) / values.length
    : null;
}

function getLat(district) {
  return Number(
    district.latitude ?? district.lat ?? district.latitude_deg
  );
}

function getLon(district) {
  return Number(
    district.longitude ??
    district.lon ??
    district.lng ??
    district.longitude_deg
  );
}

async function loadWeather() {
  setApiStatus("Connecting...");
  showMessage("message", "Loading district weather data...");

  if (refreshButton) refreshButton.disabled = true;

  try {
    const data = await fetchJson(`${API_BASE}/weather/current`);

    // Backend can return a direct array or an object containing weather.
    allWeather = Array.isArray(data)
      ? data
      : Array.isArray(data.weather)
        ? data.weather
        : [];

    populateStates();
    populateForecastDistricts();
    applyFilters({ forceForecast: true });

    setApiStatus("API Connected", true);

    showMessage(
      "message",
      `Loaded ${allWeather.length.toLocaleString()} district weather records.`
    );
  } catch (error) {
    console.error("Weather API error:", error);

    allWeather = [];
    visibleWeather = [];

    renderTable([]);
    updateMetrics([]);
    renderRankings([]);
    renderMap([]);

    if (forecastCards) forecastCards.innerHTML = "";

    setApiStatus("API Connection Failed");

    showMessage(
      "message",
      "Could not load weather data. Check the API URL and backend status."
    );
  } finally {
    if (refreshButton) refreshButton.disabled = false;
  }
}

function populateStates() {
  if (!stateSelect) return;

  const previous = stateSelect.value;

  const states = [
    ...new Set(
      allWeather.map((item) => item.state_name).filter(Boolean)
    )
  ].sort((a, b) => a.localeCompare(b));

  stateSelect.innerHTML =
    '<option value="">All States / UTs</option>';

  states.forEach((state) => {
    const option = document.createElement("option");
    option.value = state;
    option.textContent = state;
    stateSelect.appendChild(option);
  });

  if (states.includes(previous)) {
    stateSelect.value = previous;
  }
}

function populateForecastDistricts() {
  if (!forecastDistrict) return;

  const previous = forecastDistrict.value;

  const districts = [...allWeather].sort((a, b) =>
    (a.district_name || "").localeCompare(b.district_name || "")
  );

  forecastDistrict.innerHTML =
    '<option value="">Choose a district</option>';

  districts.forEach((district) => {
    const option = document.createElement("option");

    option.value = district.district_id;
    option.textContent =
      `${district.district_name}, ${district.state_name}`;

    forecastDistrict.appendChild(option);
  });

  if (
    districts.some(
      (district) =>
        String(district.district_id) === String(previous)
    )
  ) {
    forecastDistrict.value = previous;
  }
}

function applyFilters({ forceForecast = false } = {}) {
  const selectedState = stateSelect?.value || "";
  const term = (districtSearch?.value || "").trim().toLowerCase();

  visibleWeather = allWeather.filter((district) => {
    const matchesState =
      !selectedState || district.state_name === selectedState;

    const searchableText =
      `${district.district_name || ""} ${district.state_name || ""}`
        .toLowerCase();

    const matchesSearch = !term || searchableText.includes(term);

    return matchesState && matchesSearch;
  });

  updateMetrics(visibleWeather);
  renderTable(visibleWeather);
  renderRankings(visibleWeather);
  renderMap(visibleWeather);

  showMessage(
    "message",
    `Showing ${visibleWeather.length} of ${allWeather.length} districts.`
  );

  const tableCount = $("tableCount");

  if (tableCount) {
    tableCount.textContent =
      `${visibleWeather.length.toLocaleString()} records`;
  }

  const current = allWeather.find(
    (item) =>
      String(item.district_id) === String(forecastDistrict?.value)
  );

  const stillVisible =
    current &&
    visibleWeather.some(
      (item) =>
        String(item.district_id) === String(current.district_id)
    );

  if (forceForecast || !stillVisible) {
    const next = visibleWeather[0];

    if (forecastDistrict) {
      forecastDistrict.value = next ? next.district_id : "";
    }

    loadForecast(next ? next.district_id : "");
  } else {
    renderSelected(current);
  }
}

function updateMetrics(items) {
  const districtCount = $("districtCount");
  const sideDistrictCount = $("sideDistrictCount");
  const countCaption = $("districtCountCaption");
  const temperature = $("avgTemperature");
  const humidity = $("avgHumidity");
  const wind = $("avgWind");

  if (districtCount) {
    districtCount.textContent = items.length.toLocaleString();
  }

  if (sideDistrictCount) {
    sideDistrictCount.textContent = allWeather.length.toLocaleString();
  }

  if (countCaption) {
    countCaption.textContent =
      `of ${allWeather.length.toLocaleString()} available records`;
  }

  const avgTemp = average(items, "temperature_c");
  const avgHumidity = average(items, "humidity_pct");
  const avgWind = average(items, "wind_speed_kmh");

  if (temperature) {
    temperature.textContent =
      avgTemp === null ? "—" : `${formatNumber(avgTemp)}°C`;
  }

  if (humidity) {
    humidity.textContent =
      avgHumidity === null ? "—" : `${formatNumber(avgHumidity, 0)}%`;
  }

  if (wind) {
    wind.textContent =
      avgWind === null ? "—" : `${formatNumber(avgWind)} km/h`;
  }
}

function renderTable(items) {
  if (!weatherTableBody) return;

  if (!items.length) {
    weatherTableBody.innerHTML =
      '<tr><td colspan="7">No matching weather records found.</td></tr>';
    return;
  }

  const sorted = [...items].sort(
    (a, b) =>
      (a.state_name || "").localeCompare(b.state_name || "") ||
      (a.district_name || "").localeCompare(b.district_name || "")
  );

  weatherTableBody.innerHTML = sorted
    .slice(0, 250)
    .map(
      (item) => `
        <tr data-district="${escapeHtml(item.district_id)}">
          <td>${escapeHtml(item.district_name)}</td>
          <td>${escapeHtml(item.state_name)}</td>
          <td>${formatNumber(item.temperature_c)}°C</td>
          <td>${formatNumber(item.feels_like_c)}°C</td>
          <td>${formatNumber(item.humidity_pct, 0)}%</td>
          <td>${formatNumber(item.precipitation_mm)} mm</td>
          <td>${formatNumber(item.wind_speed_kmh)} km/h</td>
        </tr>
      `
    )
    .join("");

  if (sorted.length > 250) {
    weatherTableBody.insertAdjacentHTML(
      "beforeend",
      `<tr><td colspan="7">
        Showing first 250 rows. Filter by state or district to narrow results.
      </td></tr>`
    );
  }

  weatherTableBody
    .querySelectorAll("tr[data-district]")
    .forEach((row) => {
      row.addEventListener("click", () =>
        selectDistrict(row.dataset.district)
      );
    });
}

function weatherIcon(code) {
  const value = Number(code);

  if (value === 0) return "☀️";
  if ([1, 2].includes(value)) return "🌤️";
  if (value === 3) return "☁️";
  if ([45, 48].includes(value)) return "🌫️";
  if ([51, 53, 55, 56, 57].includes(value)) return "🌦️";
  if ([61, 63, 65, 66, 67, 80, 81, 82].includes(value)) return "🌧️";
  if ([71, 73, 75, 77, 85, 86].includes(value)) return "❄️";
  if ([95, 96, 99].includes(value)) return "⛈️";

  return "🌡️";
}

function renderRankings(items) {
  const valid = items.filter(
    (item) =>
      item.temperature_c !== null &&
      item.temperature_c !== undefined &&
      Number.isFinite(Number(item.temperature_c))
  );

  const hottest = [...valid]
    .sort((a, b) => Number(b.temperature_c) - Number(a.temperature_c))
    .slice(0, 5);

  const coldest = [...valid]
    .sort((a, b) => Number(a.temperature_c) - Number(b.temperature_c))
    .slice(0, 5);

  const makeRows = (districts, className) =>
    districts.length
      ? districts
          .map(
            (district, index) => `
              <div class="rank-row">
                <span class="rank-num">
                  ${String(index + 1).padStart(2, "0")}
                </span>
                <div class="rank-name">
                  <strong>${escapeHtml(district.district_name)}</strong>
                  <small>${escapeHtml(district.state_name)}</small>
                </div>
                <span class="rank-value ${className}">
                  ${formatNumber(district.temperature_c)}°C
                </span>
              </div>
            `
          )
          .join("")
      : '<p class="muted">No temperature data available.</p>';

  const hotElement = $("hotDistricts");
  const coldElement = $("coldDistricts");

  if (hotElement) hotElement.innerHTML = makeRows(hottest, "hot-value");
  if (coldElement) coldElement.innerHTML = makeRows(coldest, "cold-value");
}

function renderSelected(district) {
  const selectedWeather = $("selectedWeather");

  if (!district) {
    if (selectedWeather) {
      selectedWeather.innerHTML = `
        <div class="weather-symbol">🌤️</div>
        <div>
          <h3>Select a district</h3>
          <p>Current weather details will appear here.</p>
        </div>
      `;
    }

    ["selectedFeels", "selectedHumidity", "selectedRain", "selectedWind"]
      .forEach((id) => {
        const element = $(id);
        if (element) element.textContent = "—";
      });

    return;
  }

  if (selectedWeather) {
    selectedWeather.innerHTML = `
      <div class="weather-symbol">
        ${weatherIcon(district.weather_code)}
      </div>
      <div>
        <h3>${formatNumber(district.temperature_c)}°C</h3>
        <p>
          ${escapeHtml(district.district_name)},
          ${escapeHtml(district.state_name)}
        </p>
      </div>
    `;
  }

  const values = {
    selectedFeels: `${formatNumber(district.feels_like_c)}°C`,
    selectedHumidity: `${formatNumber(district.humidity_pct, 0)}%`,
    selectedRain: `${formatNumber(district.precipitation_mm)} mm`,
    selectedWind: `${formatNumber(district.wind_speed_kmh)} km/h`
  };

  Object.entries(values).forEach(([id, value]) => {
    const element = $(id);
    if (element) element.textContent = value;
  });
}

function selectDistrict(id) {
  const district = allWeather.find(
    (item) => String(item.district_id) === String(id)
  );

  if (!district) return;

  if (stateSelect) stateSelect.value = district.state_name || "";
  if (districtSearch) districtSearch.value = "";
  if (forecastDistrict) forecastDistrict.value = district.district_id;

  applyFilters();
  loadForecast(district.district_id);

  if (indiaMap) {
    const latitude = getLat(district);
    const longitude = getLon(district);

    if (Number.isFinite(latitude) && Number.isFinite(longitude)) {
      indiaMap.setView([latitude, longitude], 7);
    }
  }
}

async function loadForecast(id) {
  const request = ++forecastRequest;

  if (forecastCards) forecastCards.innerHTML = "";

  const district = allWeather.find(
    (item) => String(item.district_id) === String(id)
  );

  renderSelected(district);

  if (!id) {
    showMessage(
      "forecastMessage",
      "Choose a district with available weather records."
    );
    return;
  }

  showMessage("forecastMessage", "Loading forecast...");

  try {
    const data = await fetchJson(
      `${API_BASE}/weather/forecast/${encodeURIComponent(id)}`
    );

    if (request !== forecastRequest) return;

    // Backend forecast endpoint returns an array directly.
    const forecast = Array.isArray(data)
      ? data
      : Array.isArray(data.forecast)
        ? data.forecast
        : [];

    if (!forecast.length) {
      showMessage("forecastMessage", "No forecast records available.");
      return;
    }

    showMessage(
      "forecastMessage",
      `${district?.district_name || "Selected district"}, ${
        district?.state_name || ""
      } · ${forecast.length}-day forecast`
    );

    if (!forecastCards) return;

    forecastCards.innerHTML = forecast
      .map((day) => {
        const date = new Date(`${day.forecast_date}T00:00:00`);

        const dateLabel = Number.isNaN(date.getTime())
          ? escapeHtml(day.forecast_date)
          : date.toLocaleDateString("en-IN", {
              weekday: "short",
              day: "numeric",
              month: "short"
            });

        return `
          <article class="forecast-card">
            <p class="forecast-date">${dateLabel}</p>
            <div class="forecast-icon">
              ${weatherIcon(day.weather_code)}
            </div>
            <p class="high">${formatNumber(day.temperature_max_c, 0)}°</p>
            <p class="low">
              Low ${formatNumber(day.temperature_min_c, 0)}°
            </p>
            <p class="rain">
              ☂ ${formatNumber(day.precipitation_sum_mm)} mm
            </p>
          </article>
        `;
      })
      .join("");
  } catch (error) {
    if (request !== forecastRequest) return;

    console.error("Forecast API error:", error);

    showMessage(
      "forecastMessage",
      "Could not load forecast. Check the API and try again."
    );
  }
}

function normalizeStateName(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/\s+/g, " ")
    .trim();
}

function stateFeatureName(feature) {
  const properties = feature?.properties || {};

  return (
    properties.ST_NM ||
    properties.st_nm ||
    properties.NAME_1 ||
    properties.name_1 ||
    properties.NAME ||
    properties.name ||
    properties.state ||
    properties.State ||
    properties.state_name ||
    ""
  );
}

function styleStateFeature(feature) {
  const selected = normalizeStateName(stateSelect?.value);
  const name = normalizeStateName(stateFeatureName(feature));

  const active =
    !selected ||
    name === selected ||
    name.includes(selected) ||
    selected.includes(name);

  return {
    color: active ? (selected ? "#67e8f9" : "#64748b") : "#334155",
    weight: active ? (selected ? 3 : 1.2) : 0.7,
    opacity: active ? 1 : 0.6,
    fillColor: active ? (selected ? "#0891b2" : "#334155") : "#0f172a",
    fillOpacity: active ? (selected ? 0.38 : 0.1) : 0.035
  };
}

async function loadStateBoundaries() {
  try {
    const response = await fetch(
      "https://raw.githubusercontent.com/geohacker/india/master/state/india_state.geojson"
    );

    if (!response.ok) {
      throw new Error(`State boundary request failed: ${response.status}`);
    }

    const geojson = await response.json();

    stateBoundaryLayer = L.geoJSON(geojson, {
      style: styleStateFeature,

      onEachFeature: (feature, layer) => {
        layer.bindTooltip(stateFeatureName(feature), { sticky: true });

        layer.on("click", () => {
          const name = normalizeStateName(stateFeatureName(feature));

          const option = [...stateSelect.options].find(
            (item) =>
              normalizeStateName(item.value) === name ||
              normalizeStateName(item.textContent) === name
          );

          if (option) {
            stateSelect.value = option.value;
            if (districtSearch) districtSearch.value = "";

            applyFilters({ forceForecast: true });
          }
        });
      }
    }).addTo(indiaMap);

    stateBoundaryLayer.bringToBack();
    updateStateBoundaryStyle();
  } catch (error) {
    console.warn("Could not load state boundaries:", error);

    showMessage(
      "mapMessage",
      "State boundaries could not load. District markers may still work."
    );
  }
}

function updateStateBoundaryStyle() {
  if (!stateBoundaryLayer || !indiaMap) return;

  stateBoundaryLayer.setStyle(styleStateFeature);

  const selected = normalizeStateName(stateSelect?.value);
  if (!selected) return;

  const bounds = [];

  stateBoundaryLayer.eachLayer((layer) => {
    const name = normalizeStateName(stateFeatureName(layer.feature));

    if (name === selected || name.includes(selected) || selected.includes(name)) {
      try {
        bounds.push(layer.getBounds());
      } catch (error) {
        console.warn("Could not read state bounds:", error);
      }
    }
  });

  if (bounds.length) {
    const combinedBounds = bounds.reduce(
      (result, current) => result.extend(current)
    );

    indiaMap.fitBounds(combinedBounds, {
      padding: [24, 24],
      maxZoom: 7,
      animate: true
    });
  }
}

function initMap() {
  if (!window.L || !$("indiaWeatherMap")) {
    showMessage(
      "mapMessage",
      "Map library could not load. Check your internet connection."
    );
    return;
  }

  indiaMap = L.map("indiaWeatherMap", {
    scrollWheelZoom: false
  }).setView([22.7, 79.2], 4.4);

  L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
      maxZoom: 12,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }
  ).addTo(indiaMap);

  weatherLayer = L.layerGroup().addTo(indiaMap);

  loadStateBoundaries();

  showMessage(
    "mapMessage",
    "Map ready. Select a state or district to explore weather."
  );

  window.setTimeout(() => indiaMap?.invalidateSize(), 250);
}

function renderMap(items) {
  if (!indiaMap || !weatherLayer || !window.L) return;

  weatherLayer.clearLayers();

  updateStateBoundaryStyle();

  let count = 0;

  items.forEach((district) => {
    const latitude = getLat(district);
    const longitude = getLon(district);

    if (
      !Number.isFinite(latitude) ||
      !Number.isFinite(longitude) ||
      latitude < 5 ||
      latitude > 38 ||
      longitude < 65 ||
      longitude > 100
    ) {
      return;
    }

    const temperature = Number(district.temperature_c);

    const markerClass =
      Number.isFinite(temperature) && temperature >= 32
        ? "hot"
        : Number.isFinite(temperature) && temperature <= 18
          ? "cold"
          : "mild";

    const marker = L.marker([latitude, longitude], {
      icon: L.divIcon({
        className: `weather-marker ${markerClass}`,
        html: "<span></span>",
        iconSize: [15, 15],
        iconAnchor: [7, 7]
      })
    }).bindPopup(`
      <strong>
        ${escapeHtml(district.district_name)},
        ${escapeHtml(district.state_name)}
      </strong>
      <br>Temperature: ${formatNumber(district.temperature_c)}°C
      <br>Humidity: ${formatNumber(district.humidity_pct, 0)}%
      <br>
      <button
        type="button"
        class="map-select-district"
        data-id="${escapeHtml(district.district_id)}"
      >
        View district forecast
      </button>
    `);

    marker.on("popupopen", (event) => {
      const button = event.popup
        .getElement()
        ?.querySelector(".map-select-district");

      if (button) {
        button.addEventListener("click", () =>
          selectDistrict(district.district_id)
        );
      }
    });

    marker.addTo(weatherLayer);
    count++;
  });

  const pointCount = $("mapPointCount");

  if (pointCount) {
    pointCount.textContent = `${count} DISTRICT POINTS`;
  }
}

// Connect page controls.
if (stateSelect) {
  stateSelect.addEventListener("change", () => applyFilters({
    forceForecast: true
  }));
}

if (districtSearch) {
  districtSearch.addEventListener("input", () => {
    window.clearTimeout(searchTimer);

    searchTimer = window.setTimeout(() => applyFilters(), 200);
  });
}

if (resetFilters) {
  resetFilters.addEventListener("click", () => {
    if (stateSelect) stateSelect.value = "";
    if (districtSearch) districtSearch.value = "";

    applyFilters({ forceForecast: true });
  });
}

if (refreshButton) {
  refreshButton.addEventListener("click", loadWeather);
}

if (forecastDistrict) {
  forecastDistrict.addEventListener("change", () => {
    loadForecast(forecastDistrict.value);
  });
}

// Start the dashboard after the page is ready.
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  loadWeather();
});
