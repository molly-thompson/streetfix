(() => {
  const configElement = document.getElementById("report-map-config");
  const mapElement = document.getElementById("report-map");
  const latitude = document.getElementById("id_latitude");
  const longitude = document.getElementById("id_longitude");
  const clear = document.getElementById("clear-map-pin");
  const status = document.getElementById("map-status");
  if (!configElement || !mapElement || !latitude || !longitude || !clear || !status || !window.L) return;

  const config = JSON.parse(configElement.textContent);
  const map = L.map(mapElement, { attributionControl: false }).setView(
    [config.latitude, config.longitude],
    config.zoom,
  );
  L.tileLayer(config.tile_url, { maxZoom: 22 }).addTo(map);
  // Leaflet guesses its icon folder from the CSS, which breaks when static
  // file names are fingerprinted, so the server supplies the exact URLs.
  const icon = L.icon({
    iconUrl: config.icons["marker-icon"],
    iconRetinaUrl: config.icons["marker-icon-2x"],
    shadowUrl: config.icons["marker-shadow"],
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41],
  });
  let marker = null;

  function showCoordinates(moveMap) {
    const latText = latitude.value.trim();
    const lngText = longitude.value.trim();
    const lat = Number(latText);
    const lng = Number(lngText);
    if (!latText || !lngText || !Number.isFinite(lat) || !Number.isFinite(lng) ||
        lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      if (marker) map.removeLayer(marker);
      marker = null;
      return;
    }
    if (marker) marker.setLatLng([lat, lng]);
    else marker = L.marker([lat, lng], { icon }).addTo(map);
    if (moveMap) map.panTo([lat, lng]);
  }

  map.on("click", (event) => {
    const point = event.latlng.wrap();
    latitude.value = point.lat.toFixed(6);
    longitude.value = point.lng.toFixed(6);
    showCoordinates(false);
    status.textContent = "Map pin selected. Coordinates have been filled in below.";
  });
  for (const input of [latitude, longitude]) {
    input.addEventListener("change", () => showCoordinates(true));
  }
  clear.addEventListener("click", () => {
    latitude.value = "";
    longitude.value = "";
    showCoordinates(false);
    status.textContent = "Map pin cleared.";
  });
  showCoordinates(true);
})();
