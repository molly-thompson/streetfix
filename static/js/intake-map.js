(() => {
  const configElement = document.getElementById("report-map-config");
  const mapElement = document.getElementById("report-map");
  const latitude = document.getElementById("id_latitude");
  const longitude = document.getElementById("id_longitude");
  const clear = document.getElementById("clear-map-pin");
  const status = document.getElementById("map-status");
  if (!configElement || !mapElement || !latitude || !longitude || !clear || !status || !window.createReportMap) return;

  const reportMap = window.createReportMap({
    element: mapElement,
    config: JSON.parse(configElement.textContent),
    onSelect: (lat, lng) => {
      latitude.value = lat.toFixed(6);
      longitude.value = lng.toFixed(6);
      status.textContent = "Map pin selected. Coordinates have been filled in below.";
    },
  });
  if (!reportMap) return;

  function showCoordinates(moveMap) {
    const latText = latitude.value.trim();
    const lngText = longitude.value.trim();
    const lat = Number(latText);
    const lng = Number(lngText);
    if (!latText || !lngText || !Number.isFinite(lat) || !Number.isFinite(lng) ||
        lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      reportMap.clear();
      return;
    }
    reportMap.setPoint(lat, lng, moveMap);
  }

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
