(function() {
  var boot = {};
  try {
    var bootEl = document.getElementById('tkDashboardBoot');
    boot = JSON.parse((bootEl && bootEl.textContent) || '{}') || {};
  } catch (e) { boot = {}; }

  // ── Mobile detection — layout class must be applied before Leaflet measures ──
  var mq = window.matchMedia('(max-width: 767px)');
  function isMobile() { return mq.matches; }
  document.documentElement.classList.toggle('tk-mobile', isMobile());

  function haptic(style) {
    try {
      var H = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Haptics;
      if (H && typeof H.impact === 'function') { H.impact({ style: style || 'Light' }); return; }
      if (navigator.vibrate) navigator.vibrate(8);
    } catch (e) {}
  }

  var map = L.map('trackingMap', { zoomControl: !isMobile(), preferCanvas: false, zoomAnimation: true, fadeAnimation: true, tap: true }).setView([30.15, 71.0], 8);

  // Google Streets is the default basemap; other tiles stay available in the layer picker.
  var osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap'
  });

  var voyagerLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    maxZoom: 20, attribution: '&copy; OSM &copy; CARTO', subdomains: 'abcd'
  });

  var darkLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 20, attribution: '&copy; OSM &copy; CARTO', subdomains: 'abcd'
  });

  var satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19, attribution: '&copy; Esri'
  });

  var esriStreetLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19, attribution: '&copy; Esri'
  });

  var googleStreetsLayer = L.tileLayer('https://{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}', {
    maxZoom: 20, attribution: '&copy; Google', subdomains: ['mt0','mt1','mt2','mt3']
  }).addTo(map);

  var baseLayers = [
    { name: 'OSM Standard', layer: osmLayer },
    { name: 'Voyager (Modern)', layer: voyagerLayer },
    { name: 'Dark Mode', layer: darkLayer },
    { name: 'Satellite', layer: satelliteLayer },
    { name: 'Esri Street', layer: esriStreetLayer },
    { name: 'Google Streets', layer: googleStreetsLayer }
  ];
  var activeBaseName = 'Google Streets';

  function renderLayerList() {
    var host = document.getElementById('tkLayerList');
    if (!host) return;
    host.innerHTML = baseLayers.map(function(b) {
      return '<div class="tk-layer-item' + (b.name === activeBaseName ? ' active' : '') +
        '" data-layer="' + b.name + '"><i class="bi bi-map"></i> ' + b.name + '</div>';
    }).join('');
  }

  function setBaseLayer(name) {
    var target = baseLayers.filter(function(b) { return b.name === name; })[0];
    if (!target || name === activeBaseName) return;
    baseLayers.forEach(function(b) { if (map.hasLayer(b.layer)) map.removeLayer(b.layer); });
    target.layer.addTo(map);
    activeBaseName = name;
    renderLayerList();
  }

  var markers = {};
  var markerState = {};   // RegNo -> {lat, lon, icon} for change-detection
  var currentFilter = 'all';
  /** Empty Set = All Groups; otherwise only these group names are shown. */
  var selectedGroups = new Set();
  var positions = [];
  var posByReg = {};
  var feedMeta = boot.feed || {};
  var feedReceivedAt = Date.now();
  var ufoneTasksByReg = boot.ufone_tasks_by_reg || {};
  var parkingByReg = boot.parking_by_reg || {};
  var ufoneLastClosedByReg = {};
  var ufoneLastClosedPending = {};
  var POSITIONS_TIMEOUT_MS = 25000;
  var nearestLayer = L.layerGroup();
  var nearestMarkers = {};
  var nearestState = null;
  var parkingLayer = L.layerGroup();
  var parkingState = null;
  var parkingRedrawing = false;
  var AT_PARKING_M = 500;
  var nearbyState = null;
  var nearbyCircle = null;
  var meMarker = null;

  function fetchUfoneTaskMap() {
    var ctrl = new AbortController();
    var timer = setTimeout(function() { ctrl.abort(); }, POSITIONS_TIMEOUT_MS);
    return fetch('/api/tracking/ufone-active-tasks?_=' + Date.now(), {
      credentials: 'same-origin',
      signal: ctrl.signal
    })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d && d.tasks_by_reg && typeof d.tasks_by_reg === 'object') {
          ufoneTasksByReg = d.tasks_by_reg;
        }
      })
      .catch(function() { /* keep SSR seed */ })
      .finally(function() { clearTimeout(timer); });
  }

  function renderAfterTaskSync(vehicles) {
    var list = vehicles || positions || [];
    if (list.length) renderVehicles(list);
  }

  function normalizeRegKey(reg) {
    if (!reg) return '';
    var s = String(reg).trim().toUpperCase();
    s = s.replace(/[\s\-]+(COW|USG\+P|USG|RAS|MNHC|EMS|NHP)\s*$/i, '');
    if (s.indexOf(' ') >= 0) s = s.split(/\s+/)[0];
    return s.replace(/[^A-Z0-9]/g, '');
  }

  function activeUfoneTask(regNo) {
    return ufoneTasksByReg[normalizeRegKey(regNo)] || null;
  }

  function lastClosedUfoneTask(regNo) {
    var key = normalizeRegKey(regNo);
    if (!key || !Object.prototype.hasOwnProperty.call(ufoneLastClosedByReg, key)) return null;
    return ufoneLastClosedByReg[key] || null;
  }

  function lastClosedKnown(regNo) {
    return Object.prototype.hasOwnProperty.call(ufoneLastClosedByReg, normalizeRegKey(regNo));
  }

  function refreshOpenVehicleDetail(regNo) {
    var v = posByReg[regNo];
    if (!v) return;
    var m = markers[regNo];
    if (m && m.isPopupOpen && m.isPopupOpen()) m.setPopupContent(popupHtml(v));
    if (detailReg === regNo) renderDetail(v);
  }

  function requestLastClosedTask(regNo) {
    var key = normalizeRegKey(regNo);
    if (!key || activeUfoneTask(regNo) || lastClosedKnown(regNo) || ufoneLastClosedPending[key]) return;
    ufoneLastClosedPending[key] = true;
    refreshOpenVehicleDetail(regNo);
    fetch('/api/tracking/ufone-last-closed-task?reg=' + encodeURIComponent(regNo) + '&_=' + Date.now(), {
      credentials: 'same-origin'
    })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        ufoneLastClosedByReg[key] = (d && d.task) ? d.task : null;
        refreshOpenVehicleDetail(regNo);
      })
      .catch(function() { /* keep placeholder */ })
      .then(function() {
        delete ufoneLastClosedPending[key];
        if (!lastClosedKnown(regNo)) refreshOpenVehicleDetail(regNo);
      });
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function(ch) {
      return {'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch];
    });
  }
  var escapeNearest = escapeHtml;

  function nearestHasCoords(row) {
    return row && isFinite(parseFloat(row.latitude)) && isFinite(parseFloat(row.longitude)) &&
      parseFloat(row.latitude) !== 0 && parseFloat(row.longitude) !== 0;
  }

  function nearestIcon(label, kind, available) {
    var cls = kind === 'reference' ? 'reference' : (available ? 'free' : 'busy');
    return L.divIcon({
      className: 'tk-nearest-divicon',
      html: '<div class="tk-nearest-marker ' + cls + '">' + escapeNearest(label) + '</div>',
      iconSize: kind === 'reference' ? [35, 35] : [29, 29],
      iconAnchor: kind === 'reference' ? [17, 17] : [14, 14]
    });
  }

  function clearNearestOverlay() {
    nearestLayer.clearLayers();
    nearestMarkers = {};
    nearestState = null;
    if (map.hasLayer(nearestLayer)) map.removeLayer(nearestLayer);
    var panel = document.getElementById('tkNearestPanel');
    if (panel) panel.classList.remove('open');
  }

  function nearestMarkerKey(reg) {
    return normalizeRegKey(reg);
  }

  function syncNearestMarkerPositions() {
    if (!nearestState) return;
    var ref = nearestState.reference;
    var liveRef = ref && positions.find(function(v) {
      return normalizeRegKey(v.RegNo) === normalizeRegKey(ref.regno);
    });
    if (ref && liveRef && nearestHasCoords(ref)) {
      if (isFinite(parseFloat(liveRef.LAT)) && isFinite(parseFloat(liveRef.LON))) {
        ref.latitude = parseFloat(liveRef.LAT);
        ref.longitude = parseFloat(liveRef.LON);
      }
    }
    var all = (nearestState.candidates || []);
    all.forEach(function(row) {
      var live = positions.find(function(v) {
        return normalizeRegKey(v.RegNo) === normalizeRegKey(row.regno);
      });
      if (live && isFinite(parseFloat(live.LAT)) && isFinite(parseFloat(live.LON))) {
        row.latitude = parseFloat(live.LAT);
        row.longitude = parseFloat(live.LON);
      }
      var marker = nearestMarkers[nearestMarkerKey(row.regno)];
      if (marker && nearestHasCoords(row)) marker.setLatLng([row.latitude, row.longitude]);
    });
    var refMarker = nearestMarkers[nearestMarkerKey(ref && ref.regno)];
    if (refMarker && ref && nearestHasCoords(ref)) {
      refMarker.setLatLng([ref.latitude, ref.longitude]);
    }
  }

  function renderNearestPanel() {
    if (!nearestState) return;
    var panel = document.getElementById('tkNearestPanel');
    var list = document.getElementById('tkNearestList');
    var kpis = document.getElementById('tkNearestKpis');
    var onlyFree = !!nearestState.onlyFree;
    var all = nearestState.candidates || [];
    var shown = all.filter(function(row) { return !onlyFree || row.available; });
    var ref = nearestState.reference;

    document.getElementById('tkNearestTitle').textContent =
      'Nearest to ' + ((ref && (ref.display_name || ref.regno)) || nearestState.regno);
    document.getElementById('tkNearestSub').textContent =
      shown.length + ' shown · PortalXS proximity order';
    kpis.innerHTML =
      '<div class="tk-nearest-kpi"><span class="n">' + all.length + '</span><span class="l">Nearby</span></div>' +
      '<div class="tk-nearest-kpi free"><span class="n">' + all.filter(function(r) { return r.available; }).length + '</span><span class="l">Free now</span></div>' +
      '<div class="tk-nearest-kpi busy"><span class="n">' + all.filter(function(r) { return !r.available; }).length + '</span><span class="l">On task</span></div>';

    if (!shown.length) {
      list.innerHTML = '<div class="tk-nearest-empty">No vehicles match this filter.</div>';
    } else {
      list.innerHTML = shown.map(function(row) {
        var index = all.indexOf(row) + 1;
        var taskText = row.task && (row.task.task_id_display || row.task.task_id)
          ? ' · ' + (row.task.task_id_display || ('PHF-' + row.task.task_id)) : '';
        return '<div class="tk-nearest-row" data-nearest-reg="' + escapeNearest(row.regno) + '">' +
          '<span class="tk-nearest-rank">' + index + '</span>' +
          '<div class="tk-nearest-row-body">' +
          '<div class="tk-nearest-reg">' + escapeNearest(row.display_name || row.regno) + '</div>' +
          '<div class="tk-nearest-meta">' +
          '<span class="tk-nearest-badge ' + (row.available ? 'free' : 'busy') + '">' +
            (row.available ? 'FREE' : 'ON TASK') + '</span>' +
          '<span class="tk-nearest-badge status">' + escapeNearest(row.status || 'Unknown') + '</span>' +
          '</div>' +
          '<div class="tk-nearest-loc">' + escapeNearest(row.landmark || 'Location not available') +
            escapeNearest(taskText) + '</div>' +
          '</div></div>';
      }).join('');
    }

    nearestLayer.clearLayers();
    nearestMarkers = {};
    if (ref && nearestHasCoords(ref)) {
      var refMarker = L.marker([ref.latitude, ref.longitude], {
        icon: nearestIcon('R', 'reference', true), zIndexOffset: 1000
      }).bindTooltip('Reference · ' + (ref.display_name || ref.regno), { direction: 'top' });
      refMarker.addTo(nearestLayer);
      nearestMarkers[nearestMarkerKey(ref.regno)] = refMarker;
    }
    shown.forEach(function(row) {
      if (!nearestHasCoords(row)) return;
      var marker = L.marker([row.latitude, row.longitude], {
        icon: nearestIcon(String(all.indexOf(row) + 1), 'candidate', row.available),
        zIndexOffset: 900 - all.indexOf(row)
      }).bindTooltip(
        (all.indexOf(row) + 1) + '. ' + (row.display_name || row.regno) +
        (row.available ? ' · FREE' : ' · ON TASK'),
        { direction: 'top' }
      );
      marker.addTo(nearestLayer);
      nearestMarkers[nearestMarkerKey(row.regno)] = marker;
    });
    if (!map.hasLayer(nearestLayer)) nearestLayer.addTo(map);
    panel.classList.add('open');
  }

  function openNearest(regno) {
    if (!regno) return;
    clearParkingOverlay();
    closeDetail();
    var panel = document.getElementById('tkNearestPanel');
    panel.classList.add('open');
    document.getElementById('tkNearestTitle').textContent = 'Finding nearest vehicles…';
    document.getElementById('tkNearestSub').textContent = 'PortalXS live search';
    document.getElementById('tkNearestKpis').innerHTML = '';
    document.getElementById('tkNearestList').innerHTML =
      '<div class="tk-nearest-empty"><span class="spinner-border spinner-border-sm"></span> Loading live positions…</div>';
    var account = document.getElementById('accountSelect');
    var query = '?regno=' + encodeURIComponent(regno);
    if (account && account.value) query += '&account_id=' + encodeURIComponent(account.value);
    fetch('/api/tracking/nearest' + query, { credentials: 'same-origin' })
      .then(function(response) { return response.json(); })
      .then(function(data) {
        if (!data.ok) throw new Error(data.error || 'Nearest vehicle search failed.');
        nearestState = {
          regno: regno,
          reference: data.reference,
          candidates: data.candidates || [],
          onlyFree: false
        };
        document.getElementById('tkNearestFreeOnly').checked = false;
        renderNearestPanel();
        var points = [];
        if (nearestHasCoords(data.reference)) points.push([data.reference.latitude, data.reference.longitude]);
        (data.candidates || []).forEach(function(row) {
          if (nearestHasCoords(row)) points.push([row.latitude, row.longitude]);
        });
        if (points.length > 1) map.fitBounds(L.latLngBounds(points), { padding: [60, 60], maxZoom: 14, animate: true });
        else if (points.length === 1) map.setView(points[0], Math.max(map.getZoom(), 14), { animate: true });
      })
      .catch(function(error) {
        clearNearestOverlay();
        panel.classList.add('open');
        document.getElementById('tkNearestTitle').textContent = 'Nearest vehicles unavailable';
        document.getElementById('tkNearestSub').textContent = 'PortalXS could not complete the live search';
        document.getElementById('tkNearestList').innerHTML =
          '<div class="tk-nearest-empty">' + escapeNearest(error.message) + '</div>';
      });
  }

  function parkingOf(regNo) {
    return parkingByReg[normalizeRegKey(regNo)] || null;
  }

  function haversineMeters(lat1, lon1, lat2, lon2) {
    var r = 6371000;
    var p1 = lat1 * Math.PI / 180;
    var p2 = lat2 * Math.PI / 180;
    var dp = (lat2 - lat1) * Math.PI / 180;
    var dl = (lon2 - lon1) * Math.PI / 180;
    var h = Math.sin(dp / 2) * Math.sin(dp / 2) +
      Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) * Math.sin(dl / 2);
    return 2 * r * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function formatParkingDistance(meters) {
    if (meters == null || !isFinite(meters)) return '';
    if (meters < 1000) return Math.round(meters) + ' m';
    var km = meters / 1000;
    return km.toFixed(km < 10 ? 1 : 0) + ' km';
  }

  function nearbyDistanceMeters(v) {
    if (!nearbyState || !v) return null;
    var lat = parseFloat(v.LAT);
    var lon = parseFloat(v.LON);
    if (!isFinite(lat) || !isFinite(lon) || lat === 0 || lon === 0) return null;
    return haversineMeters(nearbyState.lat, nearbyState.lon, lat, lon);
  }

  function matchesNearby(v) {
    if (!nearbyState) return true;
    var meters = nearbyDistanceMeters(v);
    return meters != null && meters <= nearbyState.meters;
  }

  function nearbyLabelFor(regNo) {
    if (!nearbyState) return '';
    var meters = nearbyDistanceMeters(posByReg[regNo]);
    if (meters == null) return '';
    return formatParkingDistance(meters) + ' away';
  }

  function setNearbyHint(text) {
    var hint = document.getElementById('tkNearbyHint');
    if (hint) hint.textContent = text || 'Vehicles around your current location';
  }

  function syncNearbyTips() {
    Object.keys(markers).forEach(function(reg) {
      var marker = markers[reg];
      var prev = markerState[reg];
      var v = posByReg[reg];
      if (!marker || !prev || !v) return;
      if (marker.getTooltip()) marker.unbindTooltip();
      var color = colorFor(v.VehicleStatus || 'Idle');
      var hasTask = !!activeUfoneTask(reg);
      var gpsSt = gpsStatusOf(v);
      var keys = iconKeys(color, hasTask, reg, prev.applied, gpsSt);
      if (prev.icon === keys.full) return;
      marker.setIcon(carIcon(color, prev.applied, hasTask, reg, gpsSt));
      prev.icon = keys.full;
      prev.iconBase = keys.base;
    });
  }

  function clearNearbyFilter() {
    nearbyState = null;
    if (nearbyCircle) {
      map.removeLayer(nearbyCircle);
      nearbyCircle = null;
    }
    var fab = document.getElementById('tkFabNearby');
    if (fab) fab.classList.remove('active');
    var clearBtn = document.getElementById('tkNearbyClear');
    if (clearBtn) clearBtn.hidden = true;
    document.querySelectorAll('[data-nearby-km]').forEach(function(btn) {
      btn.classList.remove('active');
    });
    setNearbyHint('Vehicles around your current location');
    applyFilter();
  }

  function applyNearbyFilter(lat, lon, km) {
    nearbyState = { lat: lat, lon: lon, km: km, meters: km * 1000 };
    var ll = [lat, lon];
    if (meMarker) meMarker.setLatLng(ll);
    else meMarker = L.circleMarker(ll, { radius: 7, weight: 3, color: '#ffffff', fillColor: '#3b82f6', fillOpacity: 1 }).addTo(map);
    if (nearbyCircle) map.removeLayer(nearbyCircle);
    nearbyCircle = L.circle(ll, {
      radius: nearbyState.meters,
      color: '#2563eb',
      weight: 2,
      fillColor: '#3b82f6',
      fillOpacity: 0.08
    }).addTo(map);
    var fab = document.getElementById('tkFabNearby');
    if (fab) fab.classList.add('active');
    var clearBtn = document.getElementById('tkNearbyClear');
    if (clearBtn) clearBtn.hidden = false;
    document.querySelectorAll('[data-nearby-km]').forEach(function(btn) {
      btn.classList.toggle('active', parseFloat(btn.getAttribute('data-nearby-km')) === km);
    });
    applyFilter();
    var count = positions.filter(function(v) { return vehicleIsVisible(v); }).length;
    setNearbyHint(count + ' vehicle' + (count === 1 ? '' : 's') + ' within ' + km + ' km');
    map.fitBounds(nearbyCircle.getBounds(), { padding: [48, 48], maxZoom: 15, animate: true });
  }

  function getMyLocation(onOk, onFail) {
    var Geo = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Geolocation;
    if (Geo && typeof Geo.getCurrentPosition === 'function') {
      Geo.getCurrentPosition({ enableHighAccuracy: true, timeout: 8000 })
        .then(function(p) { onOk(p.coords.latitude, p.coords.longitude); })
        .catch(onFail);
      return;
    }
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(function(p) {
        onOk(p.coords.latitude, p.coords.longitude);
      }, onFail, { enableHighAccuracy: true, timeout: 8000 });
      return;
    }
    onFail();
  }

  function startNearby(km) {
    km = parseFloat(km);
    if (!isFinite(km) || km <= 0) {
      setNearbyHint('Enter a range in km');
      return;
    }
    km = Math.min(200, Math.max(0.5, km));
    setNearbyHint('Getting your location…');
    getMyLocation(function(lat, lon) {
      applyNearbyFilter(lat, lon, km);
      closeNearbyPop({ restoreLegend: !isMobile() });
      haptic();
    }, function() {
      setNearbyHint('Location unavailable. Allow GPS and try again.');
    });
  }

  function parkingDistanceInfo(v) {
    var parking = v && parkingOf(v.RegNo);
    if (!parking) return null;
    var lat = parseFloat(v.LAT);
    var lon = parseFloat(v.LON);
    if (!isFinite(lat) || !isFinite(lon) || lat === 0 || lon === 0) {
      return { parking: parking, meters: null, at: false, label: 'GPS unavailable' };
    }
    var meters = haversineMeters(lat, lon, parking.latitude, parking.longitude);
    return {
      parking: parking,
      meters: meters,
      at: meters <= AT_PARKING_M,
      label: formatParkingDistance(meters)
    };
  }

  function parkingIcon() {
    return L.divIcon({
      className: 'tk-nearest-divicon',
      html: '<div class="tk-parking-marker">P</div>',
      iconSize: [32, 32],
      iconAnchor: [16, 16]
    });
  }

  function parkingPopupHtml(info) {
    var status = info.meters == null
      ? 'Parking location set · vehicle GPS unavailable'
      : ((info.at ? 'At parking' : 'Away from parking') +
        ' · ' + info.label + ' · ' + AT_PARKING_M + ' m yard');
    return '<div class="tk-parking-pop">' +
      '<div class="tk-parking-pop-title">' + escapeHtml(info.parking.name || 'Assigned parking') + '</div>' +
      '<div class="tk-parking-pop-sub">' + escapeHtml(status) + '</div>' +
      '</div>';
  }

  function clearParkingOverlay() {
    parkingRedrawing = true;
    parkingLayer.clearLayers();
    parkingState = null;
    if (map.hasLayer(parkingLayer)) map.removeLayer(parkingLayer);
    parkingRedrawing = false;
  }

  function armParkingPopupClose() {
    map.once('moveend', function() { parkingRedrawing = false; });
    setTimeout(function() { parkingRedrawing = false; }, 700);
  }

  function drawParkingOverlay(v, info) {
    parkingRedrawing = true;
    parkingLayer.clearLayers();
    var parkLatLng = [info.parking.latitude, info.parking.longitude];
    L.circle(parkLatLng, {
      radius: AT_PARKING_M,
      color: info.at ? '#16a34a' : '#f59e0b',
      weight: 2,
      fillColor: info.at ? '#16a34a' : '#f59e0b',
      fillOpacity: 0.12
    }).addTo(parkingLayer);
    var parkMarker = L.marker(parkLatLng, { icon: parkingIcon(), zIndexOffset: 1100 })
      .bindPopup(parkingPopupHtml(info), {
        className: 'tk-parking-popup',
        closeButton: true,
        autoClose: false,
        closeOnClick: false,
        offset: [0, -6]
      })
      .addTo(parkingLayer);
    parkMarker.on('popupclose', function() {
      if (parkingRedrawing) return;
      clearParkingOverlay();
    });
    var vLat = parseFloat(v.LAT);
    var vLon = parseFloat(v.LON);
    if (isFinite(vLat) && isFinite(vLon) && vLat !== 0 && vLon !== 0) {
      L.polyline([parkLatLng, [vLat, vLon]], {
        color: info.at ? '#22c55e' : '#f59e0b',
        weight: 3,
        dashArray: '8 6',
        opacity: 0.9
      }).addTo(parkingLayer);
    }
    if (!map.hasLayer(parkingLayer)) parkingLayer.addTo(map);
    parkMarker.openPopup();
  }

  function syncParkingOverlay() {
    if (!parkingState || !parkingState.regno) return;
    var v = posByReg[parkingState.regno];
    if (!v) return;
    var info = parkingDistanceInfo(v);
    if (!info) return;
    parkingState.info = info;
    drawParkingOverlay(v, info);
    armParkingPopupClose();
  }

  function openParking(regno) {
    var v = posByReg[regno];
    var info = parkingDistanceInfo(v);
    if (!info) return;
    clearNearestOverlay();
    closeDetail();
    parkingState = { regno: regno, info: info };
    drawParkingOverlay(v, info);
    var points = [[info.parking.latitude, info.parking.longitude]];
    var vLat = parseFloat(v.LAT);
    var vLon = parseFloat(v.LON);
    if (isFinite(vLat) && isFinite(vLon) && vLat !== 0 && vLon !== 0) {
      points.push([vLat, vLon]);
    }
    if (points.length > 1) {
      map.fitBounds(L.latLngBounds(points), { padding: [70, 70], maxZoom: 16, animate: true });
    } else {
      map.setView(points[0], Math.max(map.getZoom(), 15), { animate: true });
    }
    armParkingPopupClose();
  }

  function popupParkingBlock(v) {
    var info = parkingDistanceInfo(v);
    if (!info) return '';
    var badge = info.at ? 'At parking' : 'Away from parking';
    var dist = info.meters == null ? 'GPS unavailable' : (info.label + ' from assigned parking');
    return '<div class="pop-parking-block">' +
      '<span class="pop-parking-badge ' + (info.at ? 'at' : 'away') + '">' + badge + '</span>' +
      '<div class="pop-parking-name">' + escapeHtml(info.parking.name) +
        (info.parking.district ? ' · ' + escapeHtml(info.parking.district) : '') + '</div>' +
      '<div class="pop-parking-dist">' + escapeHtml(dist) + '</div></div>' +
      '<button type="button" class="pop-link pop-parking-btn" data-parking-reg="' + encodeURIComponent(v.RegNo) + '">' +
      '<i class="bi bi-geo-alt"></i> Show parking on map</button>';
  }

  function matchesListFilter(regNo, status) {
    if (currentFilter === 'all') return true;
    if (currentFilter === 'Task') return !!activeUfoneTask(regNo);
    if (currentFilter === 'NoGPS') return isNoGps(posByReg[regNo]);
    return status === currentFilter;
  }

  function vehicleMatchesSearch(v, search) {
    if (!search) return true;
    var q = String(search).toLowerCase();
    var landmark = String((v && v.LandMark) || '').replace(/^0\|\|/, '');
    return String((v && v.RegNo) || '').toLowerCase().indexOf(q) >= 0
      || landmark.toLowerCase().indexOf(q) >= 0
      || String((v && v.GroupName) || '').toLowerCase().indexOf(q) >= 0;
  }

  function currentSearchQuery() {
    var el = document.getElementById('vehicleSearch');
    return el ? String(el.value || '').toLowerCase() : '';
  }

  function vehicleIsVisible(v) {
    if (!v) return false;
    var grp = v.GroupName || 'Unassigned';
    return matchesListFilter(v.RegNo, v.VehicleStatus)
      && isGroupSelected(grp)
      && vehicleMatchesSearch(v, currentSearchQuery())
      && matchesNearby(v);
  }

  // ── Vehicle Icons — modern navigation arrow markers ──
  function colorFor(status) {
    if (status === 'Moving') return '#22c55e';
    if (status === 'Stopped') return '#111827';
    if (status === 'Idle') return '#3b82f6';
    return '#f59e0b';
  }

  function gpsStatusOf(v) {
    return (v && v.gps_status) || 'unknown';
  }

  function isNoGps(v) {
    if (!v) return true;
    if ((v.VehicleStatus || '') === 'Unknown') return true;
    var lat = parseFloat(v.LAT);
    var lon = parseFloat(v.LON);
    return !isFinite(lat) || !isFinite(lon) || lat === 0 || lon === 0;
  }

  function displayGpsAgeSec(v) {
    if (!v || v.gps_age_sec == null || v.gps_age_sec === '') return null;
    var age = Number(v.gps_age_sec);
    if (isNaN(age)) return null;
    return Math.max(0, Math.round(age + (Date.now() - feedReceivedAt) / 1000));
  }

  function formatGpsAge(sec) {
    if (sec == null) return 'unknown';
    if (sec < 60) return sec + 's old';
    var mins = Math.floor(sec / 60);
    var rem = sec % 60;
    if (mins < 60) return rem ? (mins + 'm ' + rem + 's old') : (mins + 'm old');
    var hrs = Math.floor(mins / 60);
    var hm = mins % 60;
    return hm ? (hrs + 'h ' + hm + 'm old') : (hrs + 'h old');
  }

  function freshnessLabel(status) {
    var s = String(status || 'UNKNOWN').toUpperCase();
    if (s === 'LIVE' || s === 'DELAYED' || s === 'OFFLINE' || s === 'UNKNOWN') return s;
    return 'UNKNOWN';
  }

  function applyFeedMeta(data) {
    if (!data) return;
    if (data.source) feedMeta.source = data.source;
    if (data.fetched_at != null) feedMeta.fetched_at = data.fetched_at;
    if (data.cache_age_sec != null) feedMeta.cache_age_sec = data.cache_age_sec;
    if (data.data_status) feedMeta.data_status = data.data_status;
    if (data.warning !== undefined) feedMeta.warning = data.warning;
    if (data.error && !feedMeta.warning) feedMeta.warning = data.error;
    feedReceivedAt = Date.now();
  }

  function freshestDisplayAge() {
    var best = null;
    positions.forEach(function(v) {
      var age = displayGpsAgeSec(v);
      if (age == null) return;
      if (best == null || age < best) best = age;
    });
    return best;
  }

  function updateFreshnessUi() {
    var status = freshnessLabel(feedMeta.data_status);
    var age = freshestDisplayAge();
    var text;
    if (status === 'OFFLINE') {
      text = age == null ? 'OFFLINE' : ('OFFLINE · Last GPS ' + formatGpsAge(age).replace(' old', ' ago'));
    } else if (status === 'UNKNOWN') {
      text = 'UNKNOWN · No GPS time';
    } else {
      text = status + (age == null ? '' : (' · GPS ' + formatGpsAge(age)));
    }
    var dot = document.getElementById('tbFreshDot');
    var label = document.getElementById('tbFreshText');
    if (dot) dot.className = 'tb-fresh-dot ' + status;
    if (label) label.textContent = text;
    var updated = document.getElementById('tbUpdated');
    if (updated) updated.title = text;
    var gripDot = document.getElementById('tsLiveDot');
    if (gripDot) gripDot.className = 'ts-live-dot ' + status;
    var gripHint = document.getElementById('tsGripHint');
    if (gripHint) gripHint.textContent = text;
    var banner = document.getElementById('trackingErrorBanner');
    var bannerText = document.getElementById('trackingErrorText');
    var warn = feedMeta.warning;
    if (banner) {
      if (warn) {
        if (bannerText) bannerText.textContent = warn;
        banner.style.display = '';
      } else {
        banner.style.display = 'none';
      }
    }
    var gpsEls = document.querySelectorAll('[data-gps-age]');
    for (var i = 0; i < gpsEls.length; i++) {
      var reg = gpsEls[i].getAttribute('data-gps-age');
      var veh = posByReg[reg];
      if (!veh) continue;
      gpsEls[i].textContent = formatGpsAge(displayGpsAgeSec(veh));
    }
  }

  function shadeHex(hex, amount) {
    var h = (hex || '#888888').replace('#', '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var num = parseInt(h, 16);
    var r = Math.min(255, Math.max(0, (num >> 16) + amount));
    var g = Math.min(255, Math.max(0, ((num >> 8) & 255) + amount));
    var b = Math.min(255, Math.max(0, (num & 255) + amount));
    return '#' + [r, g, b].map(function(c) { return c.toString(16).padStart(2, '0'); }).join('');
  }

  function markerUid(regNo, color) {
    return String(regNo || 'v').replace(/[^a-zA-Z0-9]/g, '') + color.replace('#', '');
  }

  var showLabels = true;

  function moveMarker(reg, marker, lat, lon) {
    var to = L.latLng(lat, lon);
    marker.setLatLng(to);
    if (followReg === reg) map.setView(to, map.getZoom(), { animate: false });
  }

  /* Keeps a continuously growing angle so 350° → 10° turns 20° right, not 340° left */
  function nextAngle(applied, targetDeg) {
    var delta = ((targetDeg - applied) % 360 + 540) % 360 - 180;
    return applied + delta;
  }

  function iconKeys(color, hasTask, regNo, appliedDeg, gpsStatus) {
    var base = color + '|' + hasTask + '|' + (showLabels ? regNo : '') + '|' + (gpsStatus || '') + '|' + nearbyLabelFor(regNo);
    return { base: base, full: base + '|' + Math.round(appliedDeg) };
  }

  function arrowColorForGps(gpsStatus) {
    if (gpsStatus === 'delayed') return '#f59e0b';
    if (gpsStatus === 'offline') return '#ef4444';
    return '#ffffff';
  }

  function navArrowSvg(color, uid, gpsStatus) {
    var dark = shadeHex(color, -32);
    var light = shadeHex(color, 28);
    var needle = arrowColorForGps(gpsStatus);
    return '<svg width="34" height="34" viewBox="0 0 40 40" aria-hidden="true">' +
      '<defs>' +
      '<linearGradient id="ng-' + uid + '" x1="20" y1="2" x2="20" y2="38" gradientUnits="userSpaceOnUse">' +
      '<stop offset="0%" stop-color="' + light + '"/>' +
      '<stop offset="100%" stop-color="' + dark + '"/>' +
      '</linearGradient>' +
      '<filter id="nf-' + uid + '" x="-35%" y="-35%" width="170%" height="170%">' +
      '<feDropShadow dx="0" dy="2" stdDeviation="2.2" flood-color="#0f172a" flood-opacity="0.42"/>' +
      '</filter>' +
      '</defs>' +
      '<g filter="url(#nf-' + uid + ')">' +
      '<circle cx="20" cy="20" r="17" fill="url(#ng-' + uid + ')" stroke="#ffffff" stroke-width="2.6"/>' +
      '<path d="M20 8 L27.5 23.5 L20 19.5 L12.5 23.5 Z" fill="' + needle + '" stroke="' + needle + '" stroke-width="0.6" stroke-linejoin="round"/>' +
      '<circle cx="20" cy="20" r="3.2" fill="' + needle + '" opacity=".95"/>' +
      '</g></svg>';
  }

  function carIcon(color, deg, hasUfoneTask, regNo, gpsStatus) {
    var rotate = deg || 0;
    var uid = markerUid(regNo, color);
    var safeReg = escapeHtml(regNo || '');
    var label = (showLabels && regNo)
      ? '<div class="vmarker-label" style="color:' + color + ';">' + safeReg + '</div>'
      : '';
    var dist = nearbyLabelFor(regNo);
    var distHtml = dist ? '<div class="vmarker-dist">' + escapeHtml(dist) + '</div>' : '';
    var pulseHtml = hasUfoneTask ? '<div class="vmarker-task-pulse" aria-hidden="true"></div>' : '';
    return L.divIcon({
      className: 'fleet-vmarker' + (hasUfoneTask ? ' has-ufone-task' : ''),
      html: '<div class="vmarker-wrap">' + label + distHtml +
            '<div class="vmarker-car-slot">' +
            pulseHtml +
            '<div class="vmarker-car" style="transform:rotate(' + rotate + 'deg);">' +
            navArrowSvg(color, uid, gpsStatus) +
            '</div></div></div>',
      iconSize: [56, 56],
      iconAnchor: [28, 42]
    });
  }

  function popupTaskBlock(regNo) {
    var task = activeUfoneTask(regNo);
    if (task) {
      var label = escapeHtml(task.task_id_display || ('PHF-' + task.task_id));
      var sub = task.patient_name ? (' — ' + escapeHtml(task.patient_name)) : '';
      return '<div class="pop-task-block">' +
        '<span class="pop-ufone-badge"><i class="bi bi-exclamation-circle"></i> Active Ufone Task</span>' +
        '<a href="#" class="pop-task-link task-detail-btn" data-id="' + escapeHtml(task.task_id) + '">' +
        'View ' + label + sub + '</a></div>';
    }
    var closed = lastClosedUfoneTask(regNo);
    if (closed) {
      var clabel = escapeHtml(closed.task_id_display || ('PHF-' + closed.task_id));
      var csub = closed.patient_name ? (' — ' + escapeHtml(closed.patient_name)) : '';
      var metaParts = [];
      if (closed.status) metaParts.push(escapeHtml(closed.status));
      if (closed.closed_at) metaParts.push(escapeHtml(closed.closed_at));
      var meta = metaParts.length
        ? '<span class="pop-task-meta">' + metaParts.join(' · ') + '</span>'
        : '';
      return '<div class="pop-task-block">' +
        '<span class="pop-ufone-badge closed"><i class="bi bi-check-circle"></i> Last Closed Task</span>' +
        '<a href="#" class="pop-task-link pop-task-link-closed task-detail-btn" data-id="' + escapeHtml(closed.task_id) + '">' +
        'View ' + clabel + csub + '</a>' + meta + '</div>';
    }
    if (!lastClosedKnown(regNo) && ufoneLastClosedPending[normalizeRegKey(regNo)]) {
      return '<div class="pop-task-block pop-no-task">Checking last Ufone task...</div>';
    }
    return '<div class="pop-task-block pop-no-task">No active Ufone task on this vehicle</div>';
  }

  function popupHtml(v) {
    var cls = v.VehicleStatus || 'Idle';
    var color = colorFor(cls);
    var lm = escapeHtml((v.LandMark || '').replace(/^0\|\|/, ''));
    var spd = parseFloat(v.Speed || 0).toFixed(0);
    var gpsSt = gpsStatusOf(v);
    var gpsData = gpsSt === 'delayed' ? 'GPS Stale' : (gpsSt === 'offline' ? 'Offline' : (gpsSt === 'live' ? 'Live' : 'Unknown'));
    var reg = escapeHtml(v.RegNo || '');
    return '<div class="pop-title">' + reg + '</div>' +
      '<div class="pop-row"><b>Status:</b> <span style="color:' + color + '">' + escapeHtml(String(cls).toUpperCase()) + '</span></div>' +
      '<div class="pop-row"><b>Speed:</b> ' + spd + ' km/h</div>' +
      '<div class="pop-row"><b>Ignition:</b> ' + escapeHtml(v.IgnitionStatus || 'N/A') + '</div>' +
      '<div class="pop-row"><b>GPS:</b> <span data-gps-age="' + reg + '">' + formatGpsAge(displayGpsAgeSec(v)) + '</span></div>' +
      '<div class="pop-row"><b>Data:</b> ' + gpsData + '</div>' +
      '<div class="pop-row"><b>Landmark:</b> ' + (lm || 'n/a') + '</div>' +
      '<div class="pop-row"><b>Time:</b> ' + escapeHtml(v.RDT || 'N/A') + '</div>' +
      '<div class="pop-row"><b>Coords:</b> ' + escapeHtml(v.LAT) + ', ' + escapeHtml(v.LON) + '</div>' +
      popupParkingBlock(v) +
      popupTaskBlock(v.RegNo) +
      '<button type="button" class="pop-link pop-nearest-btn" data-nearest-reg="' + encodeURIComponent(v.RegNo) + '">' +
      '<i class="bi bi-broadcast-pin"></i> Find nearest vehicles</button>' +
      '<a href="/tracking/vehicle/' + encodeURIComponent(v.RegNo) + '" class="pop-link">View Details</a>';
  }

  /* ═══════════════════════════════════════════════════════════════
     Sidebar list: incremental (diff) rendering.
     Rows and group sections are created once and then patched in place,
     so a 15s poll only touches the vehicles that actually changed. This
     also preserves scroll position, collapsed groups and row selection.
     ═══════════════════════════════════════════════════════════════ */
  var rowNodes = {};      // RegNo -> row element
  var groupNodes = {};    // group name -> { header, body, count }
  var listAdopted = false;

  function cacheRowEls(row) {
    var reg = row.querySelector('.vreg');
    if (reg && !reg.querySelector('.vreg-txt')) {
      reg.innerHTML = '<span class="vreg-txt"></span><span class="v-task-tag" style="display:none;">TASK</span>';
    }
    var spd = row.querySelector('.vspd');
    if (spd && !spd.querySelector('.vspd-num')) {
      spd.innerHTML = '<span class="vspd-num"></span><br><small>km/h</small>';
    }
    row._tkEls = {
      dot: row.querySelector('.vdot'),
      regTxt: reg ? reg.querySelector('.vreg-txt') : null,
      tag: reg ? reg.querySelector('.v-task-tag') : null,
      sub: row.querySelector('.vsub'),
      spd: spd ? spd.querySelector('.vspd-num') : null
    };
    return row._tkEls;
  }

  function buildRow() {
    var row = document.createElement('div');
    row.className = 'vrow';
    row.innerHTML =
      '<div class="vdot"></div>' +
      '<div class="vinfo"><div class="vreg"></div><div class="vsub"></div></div>' +
      '<div class="vspd"></div>';
    cacheRowEls(row);
    return row;
  }

  function buildGroupSection(name) {
    var header = document.createElement('div');
    header.className = 'vg-header';
    header.dataset.group = name;
    header.innerHTML = '<i class="bi bi-chevron-down vg-chevron"></i><span></span><span class="vg-count"></span>';
    header.querySelector('span').textContent = name;
    var body = document.createElement('div');
    body.className = 'vg-body';
    body.dataset.groupBody = name;
    return { header: header, body: body, count: header.querySelector('.vg-count') };
  }

  function rowSignature(v, hasTask) {
    return [v.VehicleStatus, v.Speed, v.LandMark, v.RDT, v.LAT, v.LON, hasTask, gpsStatusOf(v)].join('|');
  }

  function updateRow(row, v) {
    var hasTask = !!activeUfoneTask(v.RegNo);
    var sig = rowSignature(v, hasTask);
    if (row._tkSig === sig) return;
    row._tkSig = sig;

    var els = row._tkEls || cacheRowEls(row);
    var cls = v.VehicleStatus || 'Idle';
    var lm = (v.LandMark || '').replace(/^0\|\|/, '').split(',')[0];
    var time = v.RDT ? String(v.RDT).substr(11, 5) : '--';

    row.dataset.regno = v.RegNo;
    row.dataset.status = cls;
    row.dataset.group = v.GroupName || 'Unassigned';
    row.dataset.lat = v.LAT;
    row.dataset.lon = v.LON;
    row.classList.toggle('has-ufone-task', hasTask);
    if (els.dot) els.dot.className = 'vdot ' + cls;
    if (els.regTxt) els.regTxt.textContent = v.RegNo;
    if (els.tag) els.tag.style.display = hasTask ? '' : 'none';
    if (els.sub) els.sub.textContent = (lm || '-') + ' \u00B7 ' + time;
    if (els.spd) els.spd.textContent = parseFloat(v.Speed || 0).toFixed(0);
  }

  /* Reuse the server-rendered rows for the first patch instead of throwing them away */
  function adoptServerNodes(list) {
    if (listAdopted) return;
    listAdopted = true;
    var pendingHeader = null;
    Array.prototype.slice.call(list.children).forEach(function(el) {
      if (el.classList.contains('vg-header')) {
        pendingHeader = el;
      } else if (el.classList.contains('vg-body') && pendingHeader) {
        groupNodes[pendingHeader.dataset.group] = {
          header: pendingHeader,
          body: el,
          count: pendingHeader.querySelector('.vg-count')
        };
        pendingHeader = null;
      }
    });
    list.querySelectorAll('.vrow').forEach(function(row) {
      if (!row.dataset.regno) return;
      cacheRowEls(row);
      rowNodes[row.dataset.regno] = row;
    });
  }

  /* Walks the desired order and only moves nodes that are out of place */
  function syncList(list, groupOrder, groups) {
    adoptServerNodes(list);
    var seenRows = {};
    var cursor = list.firstChild;

    groupOrder.forEach(function(g) {
      var section = groupNodes[g] || (groupNodes[g] = buildGroupSection(g));
      if (cursor === section.header) cursor = section.header.nextSibling;
      else list.insertBefore(section.header, cursor);
      if (cursor === section.body) cursor = section.body.nextSibling;
      else list.insertBefore(section.body, cursor);

      var gv = groups[g];
      if (section.count && section.count.textContent !== String(gv.length)) {
        section.count.textContent = gv.length;
      }

      var rowCursor = section.body.firstChild;
      gv.forEach(function(v) {
        var row = rowNodes[v.RegNo] || (rowNodes[v.RegNo] = buildRow());
        if (rowCursor === row) rowCursor = row.nextSibling;
        else section.body.insertBefore(row, rowCursor);
        updateRow(row, v);
        seenRows[v.RegNo] = true;
      });
      while (rowCursor) {
        var deadRow = rowCursor;
        rowCursor = rowCursor.nextSibling;
        section.body.removeChild(deadRow);
      }
    });

    while (cursor) {
      var dead = cursor;
      cursor = cursor.nextSibling;
      list.removeChild(dead);
    }

    Object.keys(rowNodes).forEach(function(reg) {
      if (!seenRows[reg]) delete rowNodes[reg];
    });
    Object.keys(groupNodes).forEach(function(g) {
      if (groupOrder.indexOf(g) < 0) delete groupNodes[g];
    });
  }

  /* One delegated handler each, so re-rendering never rebinds listeners */
  (function bindListDelegation() {
    var list = document.getElementById('vehicleList');
    if (!list) return;
    list.addEventListener('click', function(e) {
      var hdr = e.target.closest('.vg-header');
      if (hdr) {
        var body = hdr.nextElementSibling;
        if (body && body.classList.contains('vg-body')) {
          hdr.classList.toggle('collapsed');
          body.classList.toggle('collapsed');
        }
        return;
      }
      var row = e.target.closest('.vrow');
      if (row && row.dataset.regno) selectVehicle(row.dataset.regno, true);
    });
  })();

  function isGroupSelected(name) {
    return selectedGroups.size === 0 || selectedGroups.has(name);
  }

  function updateGroupFilterLabel() {
    var label = document.getElementById('groupFilterLabel');
    if (!label) return;
    if (selectedGroups.size === 0) {
      label.textContent = 'All Groups (' + positions.length + ')';
      return;
    }
    var names = Array.from(selectedGroups);
    var count = 0;
    positions.forEach(function(v) {
      if (selectedGroups.has(v.GroupName || 'Unassigned')) count++;
    });
    if (names.length === 1) {
      label.textContent = names[0] + ' (' + count + ')';
    } else {
      label.textContent = names.length + ' groups (' + count + ')';
    }
  }

  function syncGroupFilterOptions(groupOrder, groups) {
    var box = document.getElementById('groupFilterOptions');
    if (!box) return;
    var prev = new Set(selectedGroups);
    var html = '';
    groupOrder.forEach(function(g) {
      var count = (groups[g] || []).length;
      var checked = prev.has(g) ? ' checked' : '';
      html += '<label class="ts-gf-option">'
        + '<input type="checkbox" value="' + escapeHtml(g) + '" data-group-check' + checked + '>'
        + '<span class="ts-gf-name">' + escapeHtml(g) + '</span>'
        + '<span class="ts-gf-count">' + count + '</span>'
        + '</label>';
    });
    box.innerHTML = html;
    // Drop selections for groups that no longer exist
    selectedGroups = new Set(Array.from(prev).filter(function(g) { return groupOrder.indexOf(g) >= 0; }));
    updateGroupFilterLabel();
  }

  function syncGroupHeaderState() {
    Object.keys(groupNodes).forEach(function(name) {
      var hdr = groupNodes[name].header;
      if (hdr) hdr.classList.toggle('active-group-filter', selectedGroups.size > 0 && selectedGroups.has(name));
    });
  }

  function updateStatCounts() {
    var search = document.getElementById('vehicleSearch').value.toLowerCase();
    var mv = 0, st = 0, id = 0, total = 0, task = 0, nogps = 0;
    positions.forEach(function(v) {
      var grp = v.GroupName || 'Unassigned';
      var matchGroup = isGroupSelected(grp);
      var matchSearch = vehicleMatchesSearch(v, search);
      if (!matchGroup || !matchSearch) return;
      total++;
      if (v.VehicleStatus === 'Moving') mv++;
      else if (v.VehicleStatus === 'Stopped') st++;
      else if (v.VehicleStatus === 'Idle') id++;
      if (activeUfoneTask(v.RegNo)) task++;
      if (isNoGps(v)) nogps++;
    });
    document.getElementById('statTotal').textContent = total;
    document.getElementById('statMoving').textContent = mv;
    document.getElementById('statStopped').textContent = st;
    document.getElementById('statIdle').textContent = id;
    var taskEl = document.getElementById('statTask');
    if (taskEl) taskEl.textContent = task;
    var nogpsEl = document.getElementById('statNoGps');
    if (nogpsEl) nogpsEl.textContent = nogps;
    var gripCount = document.getElementById('tsGripCount');
    if (gripCount) gripCount.textContent = total;
  }

  // ── Render ──
  function renderVehicles(vehicles) {
    positions = vehicles || [];
    var list = document.getElementById('vehicleList');

    // index by RegNo so lookups stay O(1) as the fleet grows
    posByReg = {};
    positions.forEach(function(v) { posByReg[v.RegNo] = v; });

    // group vehicles by GroupName; stable ordering keeps the diff a no-op
    var groups = {};
    positions.forEach(function(v) {
      var g = v.GroupName || 'Unassigned';
      if (!groups[g]) groups[g] = [];
      groups[g].push(v);
    });
    var groupOrder = Object.keys(groups).sort();
    groupOrder.forEach(function(g) {
      groups[g].sort(function(a, b) { return String(a.RegNo).localeCompare(String(b.RegNo)); });
    });

    syncGroupFilterOptions(groupOrder, groups);
    syncList(list, groupOrder, groups);

    // markers — car icons; change-detection avoids wasteful setIcon/setLatLng calls
    positions.forEach(function(v) {
      if (!v.LAT || !v.LON) return;
      var lat = parseFloat(v.LAT), lon = parseFloat(v.LON);
      if (isNaN(lat) || isNaN(lon)) return;

      var cls = v.VehicleStatus || 'Idle';
      var color = colorFor(cls);
      var hasTask = !!activeUfoneTask(v.RegNo);
      var deg = parseFloat(v.Direction) || 0;
      var gpsSt = gpsStatusOf(v);

      var m = markers[v.RegNo];
      var prev = markerState[v.RegNo];
      var applied;

      if (m && prev) {
        applied = nextAngle(prev.applied, deg);
        var keys = iconKeys(color, hasTask, v.RegNo, applied, gpsSt);
        if (prev.lat !== lat || prev.lon !== lon) {
          moveMarker(v.RegNo, m, lat, lon);
        }
        if (prev.icon !== keys.full) {
          var car = (prev.iconBase === keys.base && m._icon) ? m._icon.querySelector('.vmarker-car') : null;
          /* Heading-only change: rotate the live node so its CSS transition runs */
          if (car) car.style.transform = 'rotate(' + applied + 'deg)';
          else m.setIcon(carIcon(color, applied, hasTask, v.RegNo, gpsSt));
        }
        if (m.getPopup()) m.setPopupContent(popupHtml(v));
        markerState[v.RegNo] = { lat: lat, lon: lon, icon: keys.full, iconBase: keys.base, applied: applied };
      } else {
        applied = deg;
        m = L.marker([lat, lon], { icon: carIcon(color, applied, hasTask, v.RegNo, gpsSt) });
        /* Mobile uses the bottom detail card instead of a cramped popup */
        if (!isMobile()) m.bindPopup(popupHtml(v), { maxWidth: 300 });
        var mReg = v.RegNo;
        m.on('click', function() { selectVehicle(mReg, isMobile()); });
        m.on('popupopen', function() { requestLastClosedTask(mReg); });
        markers[v.RegNo] = m;
        var newKeys = iconKeys(color, hasTask, v.RegNo, applied, gpsSt);
        markerState[v.RegNo] = { lat: lat, lon: lon, icon: newKeys.full, iconBase: newKeys.base, applied: applied };
        if (vehicleIsVisible(v)) m.addTo(map);
      }
    });

    // remove stale markers
    Object.keys(markers).forEach(function(reg) {
      if (!posByReg[reg]) {
        map.removeLayer(markers[reg]);
        delete markers[reg];
        delete markerState[reg];
      }
    });

    applyFilter();
    updateFreshnessUi();

    if (detailReg) {
      var dv = posByReg[detailReg];
      if (dv) renderDetail(dv); else closeDetail();
    }
    syncNearestMarkerPositions();
    syncParkingOverlay();
  }

  function selectVehicle(reg, pan) {
    Object.keys(rowNodes).forEach(function(r) {
      rowNodes[r].classList.toggle('active', r === reg);
    });
    var v = posByReg[reg];
    var m = markers[reg];
    if (!v || !m) return;
    if (isMobile()) {
      setSnap('peek', true);
      map.setView([parseFloat(v.LAT), parseFloat(v.LON)], Math.max(map.getZoom(), 15), { animate: true });
      openDetail(reg);
      return;
    }
      if (pan) map.setView([parseFloat(v.LAT), parseFloat(v.LON)], 14, { animate: true });
      m.openPopup();
  }

  function applyFilter() {
    var search = document.getElementById('vehicleSearch').value.toLowerCase();
    var hasSearch = search.length > 0;

    // track which groups have visible rows
    var visibleGroups = {};

    Object.keys(rowNodes).forEach(function(reg) {
      var r = rowNodes[reg];
      var v = posByReg[reg] || { RegNo: reg, GroupName: r.dataset.group, VehicleStatus: r.dataset.status };
      var show = vehicleIsVisible(v);
      var want = show ? '' : 'none';
      if (r.style.display !== want) r.style.display = want;
      if (show) visibleGroups[r.dataset.group] = true;
    });

    // show/hide whole group sections when group filter is active
    Object.keys(groupNodes).forEach(function(name) {
      var hdr = groupNodes[name].header;
      var body = groupNodes[name].body;
      if (!hdr || !body) return;
      var groupMatches = isGroupSelected(name);
      var want = groupMatches ? '' : 'none';
      if (hdr.style.display !== want) hdr.style.display = want;
      if (body.style.display !== want) body.style.display = want;
      if (!groupMatches) return;
      if (hasSearch || nearbyState || currentFilter === 'Task' || currentFilter === 'NoGPS') {
        if (visibleGroups[hdr.dataset.group]) {
          hdr.classList.remove('collapsed');
          body.classList.remove('collapsed');
        } else {
          hdr.classList.add('collapsed');
          body.classList.add('collapsed');
        }
      } else if (selectedGroups.size > 0 && selectedGroups.has(hdr.dataset.group)) {
        hdr.classList.remove('collapsed');
        body.classList.remove('collapsed');
      }
    });

    syncGroupHeaderState();

    // filter map markers too
    Object.keys(markers).forEach(function(reg) {
      var v = posByReg[reg];
      if (!v) return;
      if (vehicleIsVisible(v)) {
        if (!map.hasLayer(markers[reg])) markers[reg].addTo(map);
      } else {
        if (map.hasLayer(markers[reg])) map.removeLayer(markers[reg]);
      }
    });

    syncNearbyTips();
    if (nearbyState) {
      var nearbyCount = 0;
      positions.forEach(function(v) { if (vehicleIsVisible(v)) nearbyCount++; });
      setNearbyHint(nearbyCount + ' vehicle' + (nearbyCount === 1 ? '' : 's') + ' within ' + nearbyState.km + ' km');
    }

    updateGroupFilterLabel();
    updateStatCounts();
  }

  function fitMapToVisibleMarkers() {
    var latlngs = [];
    Object.keys(markers).forEach(function(reg) {
      if (!map.hasLayer(markers[reg])) return;
      var ll = markers[reg].getLatLng();
      latlngs.push([ll.lat, ll.lng]);
    });
    if (latlngs.length === 1) {
      map.setView(latlngs[0], 13, { animate: true });
    } else if (latlngs.length > 1) {
      map.fitBounds(L.latLngBounds(latlngs), { padding: [40, 40], animate: true });
    }
  }

  function setFilter(filter) {
    currentFilter = filter;
    // sync sidebar filter buttons
    document.querySelectorAll('.ts-filters button').forEach(function(b) {
      b.classList.toggle('active', b.dataset.filter === filter);
    });
    // sync stat badge highlight (Task has no top stat chip)
    document.querySelectorAll('.tb-stat').forEach(function(s) {
      s.classList.toggle('active-filter', s.dataset.statFilter === filter);
    });
    applyFilter();
    if (filter === 'Task' || filter === 'NoGPS') fitMapToVisibleMarkers();
  }

  /* ═══════════════════════════════════════════════════════════════
     Mobile experience: draggable bottom sheet, vehicle detail card,
     follow mode and floating map controls.
     ═══════════════════════════════════════════════════════════════ */
  var trackingWrap = document.querySelector('.tracking-wrap');
  var sheet = document.getElementById('trackingSidebar');
  var grip = document.getElementById('tsGrip');
  var detailEl = document.getElementById('tkDetail');
  var layerPop = document.getElementById('tkLayerPop');
  var fabLayers = document.getElementById('tkFabLayers');
  var currentSnap = 'peek';
  var detailReg = null;
  var followReg = null;
  var suppressGripClick = 0;

  /* Closed state shows only the handle strip, so CSS offsets for the floating
     controls stay in sync with whatever the handle measures. */
  function peekHeight() {
    var px = grip ? grip.offsetHeight : 36;
    if (trackingWrap) trackingWrap.style.setProperty('--tk-peek', px + 'px');
    return px;
  }

  /* Two states only: fully closed (handle) or fully open */
  function snapOffsets() {
    var h = sheet.offsetHeight || 1;
    return { full: 0, peek: Math.max(0, h - peekHeight()) };
  }

  function setSnap(name, silent) {
    if (!isMobile()) return;
    currentSnap = (name === 'full') ? 'full' : 'peek';
    sheet.classList.remove('tk-peek', 'tk-full', 'tk-dragging');
    sheet.classList.add('tk-' + currentSnap);
    sheet.style.removeProperty('transform');
    /* The detail card lives in the handle gap — raising the sheet would bury it */
    if (currentSnap !== 'peek' && detailReg) closeDetail();
    if (!silent) haptic();
  }

  /* ── Sheet dragging (touch) ── */
  var drag = null;
  function dragStart(y, fromList) {
    if (!isMobile()) return;
    drag = { y0: y, base: snapOffsets()[currentSnap], last: y, lastT: Date.now(), v: 0, y1: null, fromList: fromList, active: false };
  }
  function dragMove(y, ev) {
    if (!drag) return;
    var dy = y - drag.y0;
    if (!drag.active) {
      /* From the list we only take over on a downward pull at scroll-top */
      if (drag.fromList ? dy > 10 : Math.abs(dy) > 6) drag.active = true;
      else return;
    }
    var now = Date.now();
    if (now > drag.lastT) drag.v = (y - drag.last) / (now - drag.lastT);
    drag.last = y; drag.lastT = now;
    var o = snapOffsets();
    drag.y1 = Math.min(o.peek, Math.max(0, drag.base + dy));
    sheet.classList.add('tk-dragging');
    sheet.style.transform = 'translate3d(0,' + drag.y1 + 'px,0)';
    if (ev && ev.cancelable) ev.preventDefault();
  }
  function dragEnd() {
    if (!drag) return;
    var d = drag;
    drag = null;
    sheet.classList.remove('tk-dragging');
    if (!d.active) { sheet.style.removeProperty('transform'); return; }
    suppressGripClick = Date.now();
    /* A flick decides direction outright; otherwise snap to the nearer end */
    if (d.v > 0.35) { setSnap('peek'); return; }
    if (d.v < -0.35) { setSnap('full'); return; }
    var o = snapOffsets();
    var pos = (d.y1 === null) ? o[currentSnap] : d.y1;
    setSnap(Math.abs(pos - o.full) <= Math.abs(pos - o.peek) ? 'full' : 'peek');
  }

  function bindDragSurface(el, fromList) {
    if (!el) return;
    el.addEventListener('touchstart', function(e) {
      if (!isMobile() || e.touches.length !== 1) return;
      if (fromList && el.scrollTop > 0) return;
      dragStart(e.touches[0].clientY, fromList);
    }, { passive: true });
    el.addEventListener('touchmove', function(e) {
      if (!drag || e.touches.length !== 1) return;
      dragMove(e.touches[0].clientY, e);
    }, { passive: false });
    el.addEventListener('touchend', dragEnd);
    el.addEventListener('touchcancel', dragEnd);
  }
  bindDragSurface(grip, false);
  bindDragSurface(document.querySelector('.ts-search'), false);
  bindDragSurface(document.getElementById('vehicleList'), true);

  if (grip) {
    grip.addEventListener('click', function() {
      if (!isMobile() || (Date.now() - suppressGripClick) < 350) return;
      setSnap(currentSnap === 'peek' ? 'full' : 'peek');
    });
  }

  /* ── Vehicle detail card ── */
  function statusChip(cls) {
    var color = colorFor(cls);
    var bg = (cls === 'Moving') ? 'rgba(34,197,94,.16)'
           : (cls === 'Stopped') ? 'rgba(203,213,225,.14)'
           : (cls === 'Idle') ? 'rgba(59,130,246,.16)' : 'rgba(245,158,11,.16)';
    return '<span class="tk-chip" style="background:' + bg + ';color:' + (cls === 'Stopped' ? '#cbd5e1' : color) + ';">' + escapeHtml(String(cls).toUpperCase()) + '</span>';
  }

  function detailCell(k, v) {
    return '<div class="tk-detail-cell"><div class="k">' + k + '</div><div class="v">' + v + '</div></div>';
  }

  function renderDetail(v) {
    if (!detailEl) return;
    var cls = v.VehicleStatus || 'Idle';
    var spd = parseFloat(v.Speed || 0).toFixed(0);
    var lm = escapeHtml((v.LandMark || '').replace(/^0\|\|/, ''));
    var time = v.RDT ? String(v.RDT).substr(11, 5) : '--';
    var task = activeUfoneTask(v.RegNo);
    var closed = task ? null : lastClosedUfoneTask(v.RegNo);
    var info = parkingDistanceInfo(v);
    var parkingHtml = '';
    if (info) {
      parkingHtml =
        '<button type="button" class="tk-parking-card ' + (info.at ? 'at' : 'away') + '" data-tk="parking">' +
          '<div class="tk-parking-card-k">Parking</div>' +
          '<div class="tk-parking-card-v">' + (info.at ? 'At parking' : 'Away') +
            (info.label ? ' · ' + escapeHtml(info.label) : '') + '</div>' +
          '<div class="tk-parking-card-n">' + escapeHtml(info.parking.name) + '</div>' +
        '</button>';
    }
    var following = (followReg === v.RegNo);
    var shownTask = task || closed;
    var taskLabel = shownTask ? escapeHtml(shownTask.task_id_display || ('PHF-' + shownTask.task_id)) : '';
    var taskHtml = '';
    if (task) {
      taskHtml = '<a href="#" class="tk-detail-task task-detail-btn" data-id="' + escapeHtml(task.task_id) + '">' +
        '<i class="bi bi-exclamation-circle"></i> Active Ufone Task &middot; ' + taskLabel + '</a>';
    } else if (closed) {
      taskHtml = '<a href="#" class="tk-detail-task closed task-detail-btn" data-id="' + escapeHtml(closed.task_id) + '">' +
        '<i class="bi bi-check-circle"></i> Last Closed Task &middot; ' + taskLabel + '</a>';
    } else if (!lastClosedKnown(v.RegNo) && ufoneLastClosedPending[normalizeRegKey(v.RegNo)]) {
      taskHtml = '<div class="tk-detail-task closed">Checking last Ufone task...</div>';
    }
    detailEl.innerHTML =
      '<div class="tk-detail-head">' +
        '<div style="min-width:0;">' +
          '<div class="tk-detail-reg">' + escapeHtml(v.RegNo) + '</div>' +
          '<div class="tk-detail-sub">' + statusChip(cls) + ' ' + (lm || 'Location not available') + '</div>' +
        '</div>' +
        '<div class="tk-detail-close" data-tk="close" role="button" aria-label="Close"><i class="bi bi-x-lg"></i></div>' +
      '</div>' +
      '<div class="tk-detail-grid">' +
        detailCell('Speed', spd + ' km/h') +
        detailCell('Ignition', escapeHtml(v.IgnitionStatus || 'N/A')) +
        detailCell('Updated', escapeHtml(time)) +
        '<div class="tk-detail-cell"><div class="k">GPS</div><div class="v" data-gps-age="' + escapeHtml(v.RegNo) + '">' + formatGpsAge(displayGpsAgeSec(v)) + '</div></div>' +
        detailCell('Data', gpsStatusOf(v) === 'delayed' ? 'GPS Stale' : (gpsStatusOf(v) === 'offline' ? 'Offline' : (gpsStatusOf(v) === 'live' ? 'Live' : 'Unknown'))) +
      '</div>' +
      parkingHtml +
      '<div class="tk-detail-actions">' +
        '<button type="button" class="tk-act follow' + (following ? ' on' : '') + '" data-tk="follow">' +
          '<i class="bi bi-broadcast-pin"></i> ' + (following ? 'Following' : 'Follow') + '</button>' +
        '<button type="button" class="tk-act" data-tk="nearest">' +
          '<i class="bi bi-broadcast-pin"></i> Nearest</button>' +
        '<button type="button" class="tk-act" data-tk="route" data-lat="' + escapeHtml(v.LAT) + '" data-lon="' + escapeHtml(v.LON) + '">' +
          '<i class="bi bi-signpost-2"></i> Route</button>' +
      '</div>' +
      '<div class="tk-detail-actions">' +
        '<a class="tk-act primary" href="/tracking/vehicle/' + encodeURIComponent(v.RegNo) + '">' +
          '<i class="bi bi-graph-up"></i> Details</a>' +
      '</div>' +
      taskHtml;
    if (detailReg) syncFabOffset();
  }

  /* Float the map controls above the detail card instead of behind it */
  function syncFabOffset() {
    var fabsEl = document.getElementById('tkFabs');
    var legend = document.getElementById('mapLegend');
    var nearbyPop = document.getElementById('tkNearbyPop');
    if (!fabsEl) return;
    if (!isMobile()) {
      fabsEl.style.removeProperty('bottom');
      if (layerPop) layerPop.style.removeProperty('bottom');
      if (nearbyPop) nearbyPop.style.removeProperty('bottom');
      if (legend) legend.style.removeProperty('bottom');
      return;
    }
    var extra = (detailReg && detailEl) ? (detailEl.offsetHeight + 12) : 0;
    var offset = 'calc(var(--tk-peek) + ' + (12 + extra) + 'px)';
    fabsEl.style.bottom = offset;
    if (layerPop) layerPop.style.bottom = offset;
    if (nearbyPop) nearbyPop.style.bottom = offset;
    if (legend) legend.style.bottom = 'calc(var(--tk-peek) + ' + (64 + extra) + 'px)';
  }

  function openDetail(reg) {
    var v = posByReg[reg];
    if (!v || !detailEl) return;
    detailReg = reg;
    requestLastClosedTask(reg);
    renderDetail(v);
    detailEl.classList.add('open');
    closeLegend();
    syncFabOffset();
  }

  function closeDetail() {
    detailReg = null;
    if (detailEl) detailEl.classList.remove('open');
    syncFabOffset();
  }

  function closeLegend() {
    var legend = document.getElementById('mapLegend');
    var fab = document.getElementById('tkFabInfo');
    if (legend) legend.classList.remove('tk-open');
    if (fab) fab.classList.remove('active');
  }

  function openLegend() {
    var legend = document.getElementById('mapLegend');
    var fab = document.getElementById('tkFabInfo');
    if (legend) legend.classList.add('tk-open');
    if (fab) fab.classList.add('active');
  }

  /* Hand navigation off to the device's maps app when running natively */
  function openRoute(lat, lon) {
    if (!lat || !lon) return;
    var url = 'https://www.google.com/maps/dir/?api=1&destination=' + lat + ',' + lon;
    var Plugins = window.Capacitor && window.Capacitor.Plugins;
    if (Plugins && Plugins.App && typeof Plugins.App.openUrl === 'function') {
      Plugins.App.openUrl({ url: url }).catch(function() { window.open(url, '_blank'); });
    } else {
      window.open(url, '_blank');
    }
  }

  function toggleFollow(reg) {
    if (!reg) return;
    followReg = (followReg === reg) ? null : reg;
    haptic('Medium');
    var v = posByReg[reg];
    if (v) renderDetail(v);
    if (followReg && markers[followReg]) {
      map.setView(markers[followReg].getLatLng(), Math.max(map.getZoom(), 15), { animate: true });
    }
  }

  if (detailEl) {
    detailEl.addEventListener('click', function(e) {
      var hit = e.target.closest('[data-tk]');
      if (!hit) return;
      if (hit.dataset.tk === 'close') { closeDetail(); haptic(); }
      else if (hit.dataset.tk === 'follow') { toggleFollow(detailReg); }
      else if (hit.dataset.tk === 'nearest') { openNearest(detailReg); haptic(); }
      else if (hit.dataset.tk === 'parking') { openParking(detailReg); haptic(); }
      else if (hit.dataset.tk === 'route') { openRoute(hit.dataset.lat, hit.dataset.lon); }
    });
  }

  document.addEventListener('click', function(e) {
    var nearestButton = e.target.closest('.pop-nearest-btn');
    if (nearestButton) {
      e.preventDefault();
      e.stopPropagation();
      openNearest(decodeURIComponent(nearestButton.dataset.nearestReg || ''));
      haptic();
    }
    var parkingButton = e.target.closest('.pop-parking-btn');
    if (parkingButton) {
      e.preventDefault();
      e.stopPropagation();
      openParking(decodeURIComponent(parkingButton.dataset.parkingReg || ''));
      haptic();
    }
    var taskBtn = e.target.closest('.task-detail-btn');
    if (taskBtn) e.stopPropagation();
    var nearestRow = e.target.closest('.tk-nearest-row');
    if (nearestRow && nearestState) {
      var marker = nearestMarkers[nearestMarkerKey(nearestRow.dataset.nearestReg)];
      if (marker) {
        map.setView(marker.getLatLng(), Math.max(map.getZoom(), 14), { animate: true });
        marker.openTooltip();
      }
    }
  });

  document.getElementById('tkNearestClose').addEventListener('click', function() {
    clearNearestOverlay();
    haptic();
  });
  document.getElementById('tkNearestFreeOnly').addEventListener('change', function() {
    if (nearestState) {
      nearestState.onlyFree = this.checked;
      renderNearestPanel();
    }
  });

  /* ── Floating map controls ── */
  renderLayerList();
  var labelToggle = document.querySelector('.tracking-topbar .tb-check');
  var layerExtras = document.getElementById('tkLayerExtras');
  if (isMobile() && labelToggle && layerExtras) layerExtras.appendChild(labelToggle);

  function closeLayerPop() {
    if (!layerPop) return;
    layerPop.classList.remove('open');
    if (fabLayers) fabLayers.classList.remove('active');
  }

  var nearbyPop = document.getElementById('tkNearbyPop');
  var fabNearby = document.getElementById('tkFabNearby');
  function closeNearbyPop(opts) {
    if (nearbyPop) nearbyPop.classList.remove('open');
    if (opts && opts.restoreLegend && !isMobile()) openLegend();
  }

  if (fabLayers) {
    fabLayers.addEventListener('click', function(e) {
      e.stopPropagation();
      closeLegend();
      closeNearbyPop();
      var open = layerPop.classList.toggle('open');
      fabLayers.classList.toggle('active', open);
    });
  }
  var layerList = document.getElementById('tkLayerList');
  if (layerList) {
    layerList.addEventListener('click', function(e) {
      var item = e.target.closest('.tk-layer-item');
      if (!item) return;
      setBaseLayer(item.dataset.layer);
      haptic();
      closeLayerPop();
    });
  }

  document.getElementById('tkFabFit').addEventListener('click', function() {
    followReg = null;
    if (detailReg && posByReg[detailReg]) renderDetail(posByReg[detailReg]);
    fitMapToVisibleMarkers();
    haptic();
  });

  /* ── Fullscreen map: nothing but the map, a close button and zoom ── */
  var fullMap = false;
  function setFullMap(on) {
    fullMap = !!on;
    trackingWrap.classList.toggle('tk-fullmap', fullMap);
    document.documentElement.classList.toggle('tk-fullmap', fullMap);
    closeLayerPop();
    closeNearbyPop();
    var fab = document.getElementById('tkFabFull');
    if (fab) fab.classList.toggle('active', fullMap);
    /* Real browser fullscreen where it is available (desktop); harmless if it is not */
    try {
      if (fullMap && document.documentElement.requestFullscreen && !document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(function() {});
      } else if (!fullMap && document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(function() {});
      }
    } catch (e) {}
    haptic();
    resyncMap();
  }

  document.getElementById('tkFabFull').addEventListener('click', function() { setFullMap(!fullMap); });
  document.getElementById('tkFullExit').addEventListener('click', function() { setFullMap(false); });
  document.getElementById('tkZoomIn').addEventListener('click', function() { map.zoomIn(); });
  document.getElementById('tkZoomOut').addEventListener('click', function() { map.zoomOut(); });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && fullMap) setFullMap(false);
  });
  document.addEventListener('fullscreenchange', function() {
    if (fullMap && !document.fullscreenElement) setFullMap(false);
  });

  var legendEl = document.getElementById('mapLegend');
  document.getElementById('tkFabInfo').addEventListener('click', function(e) {
    e.stopPropagation();
    closeLayerPop();
    closeNearbyPop();
    if (!legendEl.classList.contains('tk-open') && detailReg) closeDetail();
    var open = legendEl.classList.toggle('tk-open');
    this.classList.toggle('active', open);
  });

  document.getElementById('tkFabLocate').addEventListener('click', function() {
    var fab = this;
    fab.classList.add('active');
    getMyLocation(function(lat, lon) {
      fab.classList.remove('active');
      var ll = [lat, lon];
      if (meMarker) meMarker.setLatLng(ll);
      else meMarker = L.circleMarker(ll, { radius: 7, weight: 3, color: '#ffffff', fillColor: '#3b82f6', fillOpacity: 1 }).addTo(map);
      map.setView(ll, Math.max(map.getZoom(), 14), { animate: true });
      haptic();
    }, function() { fab.classList.remove('active'); });
  });

  if (fabNearby && nearbyPop) {
    fabNearby.addEventListener('click', function(e) {
      e.stopPropagation();
      closeLayerPop();
      if (nearbyPop.classList.contains('open')) {
        closeNearbyPop({ restoreLegend: !isMobile() });
      } else {
        closeLegend();
        nearbyPop.classList.add('open');
      }
    });
    nearbyPop.addEventListener('click', function(e) { e.stopPropagation(); });
    nearbyPop.addEventListener('click', function(e) {
      var preset = e.target.closest('[data-nearby-km]');
      if (preset) startNearby(preset.getAttribute('data-nearby-km'));
    });
    document.getElementById('tkNearbyApply').addEventListener('click', function() {
      startNearby(document.getElementById('tkNearbyKm').value);
    });
    document.getElementById('tkNearbyKm').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        startNearby(this.value);
      }
    });
    document.getElementById('tkNearbyClear').addEventListener('click', function() {
      clearNearbyFilter();
      closeNearbyPop({ restoreLegend: !isMobile() });
      haptic();
    });
  }

  map.on('click', function(e) {
    var t = e.originalEvent && e.originalEvent.target;
    if (t && t.closest && (t.closest('.leaflet-popup') || t.closest('.modal') || t.closest('.tk-detail'))) {
      return;
    }
    var nearbyWasOpen = nearbyPop && nearbyPop.classList.contains('open');
    closeLayerPop();
    closeNearbyPop({ restoreLegend: nearbyWasOpen && !isMobile() });
    if (!(nearbyWasOpen && !isMobile())) closeLegend();
    if (isMobile() && detailReg) closeDetail();
  });
  /* Manual panning cancels follow mode, like every good tracking app */
  map.on('dragstart', function() {
    if (!followReg) return;
    var reg = followReg;
    followReg = null;
    if (detailReg === reg && posByReg[reg]) renderDetail(posByReg[reg]);
  });

  /* ── Keep Leaflet in sync with the layout (native shell is built after load) ── */
  var resyncTimer = null;
  function resyncMap() {
    clearTimeout(resyncTimer);
    resyncTimer = setTimeout(function() {
      try { map.invalidateSize({ animate: false }); } catch (e) {}
    }, 60);
  }
  if (window.ResizeObserver) {
    new ResizeObserver(resyncMap).observe(document.getElementById('trackingMap'));
  }
  window.addEventListener('load', function() { setTimeout(resyncMap, 120); });
  window.addEventListener('orientationchange', function() { setTimeout(resyncMap, 350); });

  function onViewportChange() {
    var mobile = isMobile();
    document.documentElement.classList.toggle('tk-mobile', mobile);
    if (labelToggle) {
      var host = mobile ? layerExtras : document.querySelector('.tracking-topbar');
      if (host && labelToggle.parentNode !== host) {
        if (mobile) host.appendChild(labelToggle);
        else host.insertBefore(labelToggle, document.getElementById('forceRefreshBtn'));
      }
    }
    if (mobile) {
      setSnap(currentSnap, true);
      closeLegend();
    } else {
      sheet.classList.remove('tk-peek', 'tk-full', 'tk-dragging');
      sheet.style.removeProperty('transform');
      closeDetail();
      closeLayerPop();
      closeNearbyPop();
      openLegend();
    }
    syncFabOffset();
    setTimeout(resyncMap, 260);
  }
  if (mq.addEventListener) mq.addEventListener('change', onViewportChange);
  else if (mq.addListener) mq.addListener(onViewportChange);
  if (isMobile()) setSnap('peek', true);
  else openLegend();

  // ── Events ──
  var searchDebounce = null;
  var searchInput = document.getElementById('vehicleSearch');
  searchInput.addEventListener('input', function() {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(applyFilter, 250);
  });
  searchInput.addEventListener('focus', function() {
    if (isMobile() && currentSnap !== 'full') setSnap('full', true);
  });

  document.querySelectorAll('.ts-filters button').forEach(function(btn) {
    btn.addEventListener('click', function() {
      setFilter(btn.dataset.filter);
    });
  });

  document.querySelectorAll('.tb-stat').forEach(function(stat) {
    stat.addEventListener('click', function() {
      setFilter(stat.dataset.statFilter);
      if (isMobile()) { haptic(); if (currentSnap === 'peek') setSnap('full', true); }
    });
  });

  function setGroupFilterPanelOpen(open) {
    var btn = document.getElementById('groupFilterBtn');
    var panel = document.getElementById('groupFilterPanel');
    if (!btn || !panel) return;
    btn.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    panel.classList.toggle('open', open);
    if (open) panel.removeAttribute('hidden');
    else panel.setAttribute('hidden', '');
  }

  function readGroupChecksIntoSelection() {
    selectedGroups = new Set();
    document.querySelectorAll('#groupFilterOptions input[data-group-check]:checked').forEach(function(cb) {
      if (cb.value) selectedGroups.add(cb.value);
    });
  }

  function applyGroupFilterFromUi(closePanel) {
    readGroupChecksIntoSelection();
    applyFilter();
    followReg = null;
    fitMapToVisibleMarkers();
    if (closePanel) setGroupFilterPanelOpen(false);
    if (isMobile()) setSnap('peek', true);
  }

  document.getElementById('groupFilterBtn').addEventListener('click', function(e) {
    e.stopPropagation();
    var panel = document.getElementById('groupFilterPanel');
    setGroupFilterPanelOpen(!(panel && panel.classList.contains('open')));
  });

  document.getElementById('groupFilterOptions').addEventListener('change', function(e) {
    if (!e.target || !e.target.matches('input[data-group-check]')) return;
    applyGroupFilterFromUi(false);
  });

  document.getElementById('groupFilterClear').addEventListener('click', function(e) {
    e.stopPropagation();
    document.querySelectorAll('#groupFilterOptions input[data-group-check]').forEach(function(cb) {
      cb.checked = false;
    });
    applyGroupFilterFromUi(true);
  });

  document.getElementById('groupFilterDone').addEventListener('click', function(e) {
    e.stopPropagation();
    applyGroupFilterFromUi(true);
  });

  document.addEventListener('click', function(e) {
    var wrap = document.getElementById('groupFilterWrap');
    if (!wrap || wrap.contains(e.target)) return;
    setGroupFilterPanelOpen(false);
  });

  // Show/hide vehicle labels on map markers
  document.getElementById('showLabelsChk').addEventListener('change', function() {
    showLabels = this.checked;
    // re-render markers with/without labels
    positions.forEach(function(v) {
      if (!markers[v.RegNo]) return;
      var color = colorFor(v.VehicleStatus || 'Idle');
      var hasTask = !!activeUfoneTask(v.RegNo);
      var state = markerState[v.RegNo];
      var applied = state ? state.applied : (parseFloat(v.Direction) || 0);
      markers[v.RegNo].setIcon(carIcon(color, applied, hasTask, v.RegNo, gpsStatusOf(v)));
      if (state) {
        var keys = iconKeys(color, hasTask, v.RegNo, applied, gpsStatusOf(v));
        state.icon = keys.full;
        state.iconBase = keys.base;
      }
    });
  });

  var accountSelect = document.getElementById('accountSelect');
  if (accountSelect) {
    accountSelect.addEventListener('change', function() {
      var url = new URL(window.location.href);
      url.searchParams.set('account_id', this.value);
      window.location.href = url.toString();
    });
  }

  document.getElementById('forceRefreshBtn').addEventListener('click', function() {
    haptic();
    refreshPositions(true);
  });

  // ── Auto refresh: one in-flight request, then wait 15s ──
  var REFRESH_MS = 15000;
  var UFONE_TASK_MS = 60000;
  var lastRefreshAt = Date.now();
  var positionsInFlight = false;
  var positionsRequestId = 0;
  var positionsAbort = null;
  var pollTimer = null;

  function setPositionsBusy(busy) {
    positionsInFlight = !!busy;
    var btn = document.getElementById('forceRefreshBtn');
    if (btn) btn.disabled = !!busy;
    var indicator = document.getElementById('refreshIndicator');
    if (indicator) indicator.style.display = busy ? 'block' : 'none';
  }

  function scheduleNextPoll() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(function() {
      pollTimer = null;
      if (document.hidden) {
        scheduleNextPoll();
        return;
      }
      refreshPositions(false);
    }, REFRESH_MS);
  }

  setInterval(function() {
    if (document.hidden) return;
    fetchUfoneTaskMap().then(function() { renderAfterTaskSync(); });
  }, UFONE_TASK_MS);

  document.addEventListener('visibilitychange', function() {
    if (!document.hidden && (Date.now() - lastRefreshAt) > REFRESH_MS) {
      refreshPositions(false);
    }
  });

  function refreshPositions(force) {
    if (positionsInFlight && !force) return;
    if (force && positionsAbort) {
      try { positionsAbort.abort(); } catch (e) {}
    }
    var requestId = ++positionsRequestId;
    var ctrl = new AbortController();
    positionsAbort = ctrl;
    setPositionsBusy(true);
    lastRefreshAt = Date.now();
    var url = force ? '/api/tracking/refresh' : '/api/tracking/positions';
    var opts = {
      method: force ? 'POST' : 'GET',
      headers: { 'X-CSRFToken': window.FleetConfig.csrfToken },
      signal: ctrl.signal
    };
    if (force) opts.headers['Content-Type'] = 'application/json';
    var timer = setTimeout(function() { ctrl.abort(); }, POSITIONS_TIMEOUT_MS);
    fetch(url, opts).then(function(r) { return r.json(); }).then(function(data) {
      if (requestId !== positionsRequestId) return;
      applyFeedMeta(data);
      if (data.vehicles && data.vehicles.length) {
        renderVehicles(data.vehicles);
      } else if (Object.keys(ufoneTasksByReg).length && positions.length) {
        renderVehicles(positions);
      } else {
        updateFreshnessUi();
      }
    }).catch(function() {
      if (requestId !== positionsRequestId) return;
      feedMeta.data_status = feedMeta.data_status === 'LIVE' ? 'DELAYED' : (feedMeta.data_status || 'OFFLINE');
      feedMeta.warning = 'refresh failed';
      updateFreshnessUi();
    }).then(function() {
      clearTimeout(timer);
      if (requestId !== positionsRequestId) return;
      positionsAbort = null;
      setPositionsBusy(false);
      scheduleNextPoll();
    });
  }

  setInterval(function() {
    if (document.hidden) return;
    updateFreshnessUi();
  }, 10000);

  // ── Initial load: draw markers from SSR immediately, then overlay Ufone tags. ──
  var initialVehicles = boot.vehicles || [];
  if (initialVehicles && initialVehicles.length) {
    renderVehicles(initialVehicles);
    var boundsVehicles = initialVehicles.filter(function(v) {
      if (!v.LAT || !v.LON) return false;
      return true;
    });
    if (boundsVehicles.length) {
      var bounds = L.latLngBounds(boundsVehicles.map(function(v) { return [parseFloat(v.LAT), parseFloat(v.LON)]; }));
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [40, 40] });
    }
  } else {
    updateStatCounts();
    syncGroupHeaderState();
    updateFreshnessUi();
  }
  scheduleNextPoll();
  fetchUfoneTaskMap().then(function() { renderAfterTaskSync(); });
})();
