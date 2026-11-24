(() => {
  // Shared by the report form and the chat: a Leaflet map where a reporter can
  // click once to drop a pin. Callers own the surrounding fields and wording.
  window.createReportMap = ({ element, config, onSelect }) => {
    const leaflet = window.L;
    if (!leaflet || !element || !config) return null;

    const map = leaflet
      .map(element, { attributionControl: false })
      .setView([config.latitude, config.longitude], config.zoom);
    leaflet.tileLayer(config.tile_url, { maxZoom: 22 }).addTo(map);

    // Leaflet guesses its icon folder from the CSS, which breaks when static
    // file names are fingerprinted, so the server supplies the exact URLs.
    const icon = leaflet.icon({
      iconUrl: config.icons["marker-icon"],
      iconRetinaUrl: config.icons["marker-icon-2x"],
      shadowUrl: config.icons["marker-shadow"],
      iconSize: [25, 41],
      iconAnchor: [12, 41],
      popupAnchor: [1, -34],
      shadowSize: [41, 41],
    });
    let marker = null;

    function setPoint(lat, lng, pan) {
      if (marker) marker.setLatLng([lat, lng]);
      else marker = leaflet.marker([lat, lng], { icon }).addTo(map);
      if (pan) map.panTo([lat, lng]);
    }

    function clear() {
      if (marker) map.removeLayer(marker);
      marker = null;
    }

    map.on("click", (event) => {
      const point = event.latlng.wrap();
      setPoint(point.lat, point.lng, false);
      if (onSelect) onSelect(Number(point.lat.toFixed(6)), Number(point.lng.toFixed(6)));
    });

    return { map, setPoint, clear };
  };
})();
