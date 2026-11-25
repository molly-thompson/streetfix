/* Officer phone screens: route maps and voice input for text boxes.
   Pages work without this script; it only adds the map and dictation. */
(() => {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function toast(msg, ms = 3500) {
    const t = $('#toast'); if (!t) return;
    t.textContent = msg; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => { t.hidden = true; }, ms);
  }

  /* ---------------- maps ---------------- */
  function drawMap(el) {
    const data = JSON.parse($('#map-points').textContent);
    if (typeof L === 'undefined') { el.innerHTML = '<p class="pad muted">Map unavailable — use the list.</p>'; return; }
    const theme = getComputedStyle(document.documentElement);
    const token = name => theme.getPropertyValue(name).trim();
    const single = el.dataset.single === '1';
    const m = L.map(el, { zoomControl: true });
    L.tileLayer(data.tiles, { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(m);
    const pts = [];
    if (!single) {
      L.circleMarker([data.depot.lat, data.depot.lng], { radius: 7, color: token('--theme-surface'), weight: 2, fillColor: token('--theme-emphasis-text'), fillOpacity: 1 })
        .bindPopup('Depot · ' + esc(data.depot.name)).addTo(m);
      pts.push([data.depot.lat, data.depot.lng]);
    }
    data.stops.forEach((s, i) => {
      pts.push([s.lat, s.lng]);
      L.marker([s.lat, s.lng], { icon: L.divIcon({ className: '', html: `<div class="pin" style="background:${esc(s.colour)}">${single ? '•' : i + 1}</div>` }) })
        .bindPopup(`<b>${esc(s.title)}</b><br>${esc(s.address)}<br><a href="${esc(s.url)}">Open job</a>`).addTo(m);
    });
    if (!single && data.stops.length) {
      L.polyline(pts.concat([[data.depot.lat, data.depot.lng]]), { color: token('--theme-primary'), weight: 3, dashArray: '6 6' }).addTo(m);
    }
    if (pts.length > 1) m.fitBounds(pts, { padding: [30, 30] }); else if (pts.length) m.setView(pts[0], 15);
  }
  document.querySelectorAll('[data-map]').forEach(drawMap);

  /* ---------------- voice input (dictation into text boxes) ---------------- */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const MIC = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
  let dictation = null;
  function stopDictation() { if (dictation) { try { dictation.rec.stop(); } catch (e) { /* already stopped */ } } }
  function dictate(btn, box) {
    if (dictation && dictation.btn === btn) return stopDictation();   // tap again to stop
    stopDictation();
    if (!navigator.onLine) return toast('Voice input needs a signal. Use your keyboard\'s microphone instead.');
    const rec = new SR(), base = box.value.trim();
    rec.lang = 'en-GB'; rec.interimResults = true; rec.continuous = true; rec.maxAlternatives = 1;
    let finalText = '';
    const show = interim => { box.value = [base, (finalText + ' ' + interim).trim()].filter(Boolean).join(base ? ' ' : ''); };
    rec.onresult = ev => {
      let interim = '';
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const t = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) finalText = (finalText + ' ' + t).trim(); else interim += t;
      }
      show(interim);
    };
    rec.onerror = ev => {
      const msg = { 'not-allowed': 'Allow microphone access to use voice input.', 'service-not-allowed': 'Allow microphone access to use voice input.',
        'no-speech': 'No speech heard. Tap the microphone and try again.',
        network: navigator.onLine ? 'This browser can\'t turn speech into text. Use Google Chrome, or your keyboard\'s microphone.'
          : 'Voice input needs a signal. Use your keyboard\'s microphone instead.' }[ev.error];
      if (msg) toast(msg);
    };
    rec.onend = () => { show(''); btn.classList.remove('on'); btn.setAttribute('aria-label', 'Dictate with your voice'); if (dictation && dictation.rec === rec) dictation = null; };
    dictation = { rec, btn };
    btn.classList.add('on'); btn.setAttribute('aria-label', 'Stop dictating');
    try { rec.start(); toast('Listening… tap the microphone again to stop', 2500); }
    catch (e) { dictation = null; btn.classList.remove('on'); toast('Voice input could not start.'); }
  }
  if (SR) {
    document.querySelectorAll('textarea[data-dictate]').forEach(box => {
      const wrap = document.createElement('div'); wrap.className = 'dict';
      box.parentNode.insertBefore(wrap, box); wrap.appendChild(box);
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'mic'; btn.innerHTML = MIC;
      btn.setAttribute('aria-label', 'Dictate with your voice'); btn.title = 'Dictate';
      btn.addEventListener('click', e => { e.preventDefault(); dictate(btn, box); });
      wrap.appendChild(btn);
    });
  }
})();
