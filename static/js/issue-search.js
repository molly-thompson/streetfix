(() => {
  const script = document.currentScript;
  const apiUrl = script && script.dataset.apiUrl;
  const form = document.getElementById("issue-search-form");
  const query = document.getElementById("issue-query");
  const summary = document.getElementById("issue-search-summary");
  const results = document.getElementById("issue-results");
  const nearMe = document.getElementById("use-my-location");
  const areaButton = document.getElementById("search-map-area");
  const mapElement = document.getElementById("issue-map");
  const configElement = document.getElementById("issue-map-config");
  if (!apiUrl || !form || !query || !summary || !results) return;

  const leaflet = window.L;
  let map = null;
  let markers = null;
  let icon = null;
  if (leaflet && mapElement && configElement) {
    const config = JSON.parse(configElement.textContent);
    map = leaflet
      .map(mapElement, { attributionControl: false })
      .setView([config.latitude, config.longitude], config.zoom);
    leaflet.tileLayer(config.tile_url, { maxZoom: 22 }).addTo(map);
    markers = leaflet.layerGroup().addTo(map);
    // The server supplies exact icon URLs because static file names may be fingerprinted.
    icon = leaflet.icon({
      iconUrl: config.icons["marker-icon"],
      iconRetinaUrl: config.icons["marker-icon-2x"],
      shadowUrl: config.icons["marker-shadow"],
      iconSize: [25, 41],
      iconAnchor: [12, 41],
      popupAnchor: [1, -34],
      shadowSize: [41, 41],
    });
  }

  function age(days) {
    if (days < 1) return "reported today";
    return `reported ${days} day${days === 1 ? "" : "s"} ago`;
  }

  function describe(issue) {
    const parts = [issue.status, age(issue.days_open)];
    if (issue.distance_km !== null) parts.push(`${issue.distance_km} km away`);
    return `${issue.issue}: ${parts.join(", ")}`;
  }

  function show(data, fitMap) {
    results.replaceChildren();
    if (markers) markers.clearLayers();
    const points = [];
    for (const issue of data.issues) {
      const item = document.createElement("li");
      item.textContent = describe(issue);
      results.append(item);
      if (markers) {
        leaflet
          .marker([issue.latitude, issue.longitude], { icon, title: issue.issue })
          .bindPopup(describe(issue))
          .addTo(markers);
        points.push([issue.latitude, issue.longitude]);
      }
    }
    if (fitMap && map && points.length) map.fitBounds(points, { maxZoom: 17, padding: [24, 24] });
    const count = data.issues.length;
    let text = `${count} open issue${count === 1 ? "" : "s"} found`;
    if (data.truncated) text += " (showing the first results only; narrow your search)";
    if (data.understood.length) text += `. Searched for: ${data.understood.join("; ")}`;
    if (data.place_missing) text += ". We could not find that postcode, so location was ignored";
    summary.textContent = `${text}.`;
  }

  async function search(params, fitMap) {
    summary.textContent = "Searching...";
    try {
      const response = await fetch(`${apiUrl}?${params}`, { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (!response.ok) {
        summary.textContent = data.error || "The search failed. Try again.";
        return;
      }
      show(data, fitMap);
    } catch {
      summary.textContent = "The search failed. Try again.";
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    search(new URLSearchParams({ q: query.value }), true);
  });

  if (areaButton && map) {
    areaButton.addEventListener("click", () => {
      const bounds = map.getBounds();
      search(
        new URLSearchParams({
          q: query.value,
          south: bounds.getSouth().toFixed(6),
          west: bounds.getWest().toFixed(6),
          north: bounds.getNorth().toFixed(6),
          east: bounds.getEast().toFixed(6),
        }),
        false,
      );
    });
  }

  if (nearMe && navigator.geolocation) {
    nearMe.hidden = false;
    nearMe.addEventListener("click", () => {
      summary.textContent = "Finding your location...";
      navigator.geolocation.getCurrentPosition(
        (position) => {
          search(
            new URLSearchParams({
              q: query.value,
              lat: position.coords.latitude.toFixed(6),
              lng: position.coords.longitude.toFixed(6),
            }),
            true,
          );
        },
        () => {
          summary.textContent = "We could not get your location. Search by postcode instead.";
        },
      );
    });
  }

  search(new URLSearchParams(), true);
})();
