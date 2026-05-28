/**
 * Global R2 pending upload queue (localStorage): GPS check-in/out + task odometer photos.
 * Auto-retry, top banner, per-record error lines only.
 */
(function (global) {
  'use strict';

  var CHECKIN_PREFIX = 'gps-attendance:checkin:';
  var CHECKOUT_PREFIX = 'gps-attendance:checkout:';
  var ODOMETER_PREFIX = 'task-odometer:';
  var RETRY_MS = 15000;
  var retryTimer = null;
  var retryInFlight = false;
  var debounceTimer = null;
  var successHideTimer = null;

  function cfg() {
    return global.__fleetGpsPendingConfig || {};
  }

  function currentDateDmy() {
    var now = new Date(Date.now() + (typeof global._pktOffset !== 'undefined' ? global._pktOffset : 0));
    var dd = String(now.getDate()).padStart(2, '0');
    var mm = String(now.getMonth() + 1).padStart(2, '0');
    var yyyy = String(now.getFullYear());
    return dd + '-' + mm + '-' + yyyy;
  }

  function gpsJsonPostHeaders() {
    var tok = '';
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) tok = meta.getAttribute('content') || '';
    var h = { 'Content-Type': 'application/json' };
    if (tok) h['X-CSRFToken'] = tok;
    return h;
  }

  function gpsApiJsonMessage(body) {
    if (!body || typeof body !== 'object') return '';
    return body.message || body.error || '';
  }

  function parseStorageKey(key) {
    var s = String(key || '');
    var m = s.match(/^gps-attendance:(checkin|checkout):(\d{2}-\d{2}-\d{4}):(.+)$/);
    if (m) {
      return { kind: m[1], date: m[2], entityId: m[3], driverId: m[3], key: key };
    }
    m = s.match(/^task-odometer:(\d{2}-\d{2}-\d{4}):(.+)$/);
    if (m) {
      return { kind: 'odometer', date: m[1], entityId: m[2], vehicleId: m[2], key: key };
    }
    return null;
  }

  function listAllPending() {
    var out = [];
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var key = localStorage.key(i);
        if (!key) continue;
        if (key.indexOf(CHECKIN_PREFIX) !== 0 && key.indexOf(CHECKOUT_PREFIX) !== 0 && key.indexOf(ODOMETER_PREFIX) !== 0) {
          continue;
        }
        var meta = parseStorageKey(key);
        if (!meta) continue;
        var raw = localStorage.getItem(key);
        if (!raw) continue;
        var payload;
        try {
          payload = JSON.parse(raw);
        } catch (e) {
          continue;
        }
        if (!payload || !payload.photo_base64) continue;
        out.push({
          kind: meta.kind,
          date: meta.date,
          driverId: meta.driverId,
          vehicleId: meta.vehicleId,
          entityId: meta.entityId,
          key: key,
          payload: payload,
        });
      }
    } catch (e) { /* private mode */ }
    return out;
  }

  function itemLabel(item) {
    var p = item.payload || {};
    if (item.kind === 'checkin') {
      return 'Check-in photo' + (p.driver_name ? ' — ' + p.driver_name : '');
    }
    if (item.kind === 'checkout') {
      return 'Check-out photo' + (p.driver_name ? ' — ' + p.driver_name : '');
    }
    if (item.kind === 'odometer') {
      return 'Odometer photo' + (p.vehicle_no ? ' — ' + p.vehicle_no : '');
    }
    return 'Record upload pending';
  }

  function pendingDetailHtml(items) {
    if (!items.length) return '';
    var lines = items.map(function (it) {
      return '<li>' + itemLabel(it) + ' — <strong>not uploaded yet</strong> (auto-retry active)</li>';
    });
    return '<ul class="fleet-gps-pending-banner__list mb-0 ps-3">' + lines.join('') + '</ul>';
  }

  function keepPendingOnFailure(res, kind) {
    if (!res || res.ok) return false;
    if (res.status >= 500) return true;
    var msg = (gpsApiJsonMessage(res.body) || '').toLowerCase();
    if (res.status === 400 || res.status === 404) {
      var block = ['maximum', 'pehle', 'ho chuka', 'allowed', 'duty off', 'pending'];
      if (kind === 'checkin') block.push('check-out');
      else if (kind === 'checkout') {
        block.push('check-in', 'nahi mila');
      } else if (kind === 'odometer') {
        block = ['permission', 'invalid', 'csrf'];
      }
      for (var j = 0; j < block.length; j++) {
        if (msg.indexOf(block[j]) >= 0) return false;
      }
    }
    return res.status === 0;
  }

  function postPayload(kind, payload) {
    var c = cfg();
    var url;
    if (kind === 'checkin') url = c.checkinUrl;
    else if (kind === 'checkout') url = c.checkoutUrl;
    else if (kind === 'odometer') url = c.odometerUploadUrl;
    if (!url) return Promise.reject(new Error('missing_url'));
    return fetch(url, {
      method: 'POST',
      headers: gpsJsonPostHeaders(),
      body: JSON.stringify(payload),
    }).then(function (r) {
      return r.text().then(function (text) {
        var body = {};
        if (text) {
          try {
            body = JSON.parse(text);
          } catch (e) {
            body = { message: 'Server response could not be parsed (HTTP ' + r.status + ').' };
          }
        }
        return { ok: r.ok, status: r.status, body: body };
      });
    });
  }

  function dispatchOdometerUploaded(vehicleId, url) {
    try {
      document.dispatchEvent(new CustomEvent('fleet-odometer-uploaded', {
        detail: { vehicleId: String(vehicleId), url: url },
      }));
    } catch (e) {
      var ev = document.createEvent('CustomEvent');
      ev.initCustomEvent('fleet-odometer-uploaded', true, true, { vehicleId: String(vehicleId), url: url });
      document.dispatchEvent(ev);
    }
  }

  function retryItem(item) {
    var body = item.payload;
    if (item.kind === 'odometer') {
      body = { photo_base64: item.payload.photo_base64 };
    }
    return postPayload(item.kind, body).then(function (res) {
      if (res.ok && res.body && res.body.ok) {
        localStorage.removeItem(item.key);
        if (item.kind === 'odometer' && res.body.url) {
          dispatchOdometerUploaded(item.vehicleId || item.entityId, res.body.url);
        }
        return { ok: true, kind: item.kind };
      }
      if (!keepPendingOnFailure(res, item.kind)) {
        localStorage.removeItem(item.key);
      }
      return { ok: false, kind: item.kind, res: res };
    }).catch(function () {
      return { ok: false, kind: item.kind, network: true };
    });
  }

  function dispatchChanged() {
    try {
      document.dispatchEvent(new CustomEvent('fleet-gps-pending-changed'));
    } catch (e) {
      var ev = document.createEvent('Event');
      ev.initEvent('fleet-gps-pending-changed', true, true);
      document.dispatchEvent(ev);
    }
  }

  function isDashboardPage() {
    var p = (global.location && global.location.pathname) || '';
    return p === '/' || p === '/dashboard' || document.body.getAttribute('data-fleet-page') === 'dashboard';
  }

  function pendingSummary(items) {
    var hasIn = false;
    var hasOut = false;
    var hasOdom = false;
    items.forEach(function (it) {
      if (it.kind === 'checkin') hasIn = true;
      else if (it.kind === 'checkout') hasOut = true;
      else hasOdom = true;
    });
    var parts = [];
    if (hasIn) parts.push('check-in');
    if (hasOut) parts.push('check-out');
    if (hasOdom) parts.push('odometer');
    var title = parts.length > 1
      ? 'Uploads pending (' + parts.join(', ') + ')'
      : (hasOdom ? 'Odometer photo not uploaded' : (hasIn ? 'Check-in photo not uploaded' : 'Check-out photo not uploaded'));
    return { title: title };
  }

  function getBannerEl() {
    return document.getElementById('fleetGpsPendingBanner');
  }

  function setBannerState(state, opts) {
    var el = getBannerEl();
    if (!el) return;
    opts = opts || {};
    el.setAttribute('data-state', state);
    el.classList.remove('d-none', 'fleet-gps-pending--success', 'fleet-gps-pending--warn', 'fleet-gps-pending--retry');

    var titleEl = el.querySelector('[data-role="title"]');
    var detailEl = el.querySelector('[data-role="detail"]');
    var actionEl = el.querySelector('[data-role="action"]');

    if (state === 'hidden') {
      el.classList.add('d-none');
      return;
    }
    el.classList.remove('d-none');

    if (state === 'success') {
      el.classList.add('fleet-gps-pending--success');
      if (titleEl) titleEl.textContent = 'All records uploaded successfully';
      if (detailEl) {
        detailEl.textContent = '';
        detailEl.innerHTML = '';
        detailEl.classList.add('d-none');
      }
      if (actionEl) actionEl.classList.add('d-none');
      return;
    }

    if (detailEl) detailEl.classList.remove('d-none');

    if (state === 'retrying') {
      el.classList.add('fleet-gps-pending--retry');
      if (titleEl) titleEl.textContent = opts.title || 'Uploading…';
      if (detailEl) {
        var retryItems = opts.items || listAllPending();
        if (retryItems.length) {
          detailEl.innerHTML = pendingDetailHtml(retryItems);
        } else {
          detailEl.textContent = opts.detail || 'Please keep mobile data or Wi‑Fi on.';
        }
      }
      if (actionEl) actionEl.classList.remove('d-none');
      return;
    }

    el.classList.add('fleet-gps-pending--warn');
    var items = opts.items || listAllPending();
    var summary = pendingSummary(items);
    if (titleEl) titleEl.textContent = opts.title || summary.title;
    if (detailEl) {
      detailEl.innerHTML = pendingDetailHtml(items);
    }
    if (actionEl) {
      actionEl.classList.remove('d-none');
      var linkIn = actionEl.querySelector('[data-link="checkin"]');
      var linkOut = actionEl.querySelector('[data-link="checkout"]');
      var linkTask = actionEl.querySelector('[data-link="task"]');
      var c = cfg();
      var hasIn = items.some(function (x) { return x.kind === 'checkin'; });
      var hasOut = items.some(function (x) { return x.kind === 'checkout'; });
      var hasOdom = items.some(function (x) { return x.kind === 'odometer'; });
      if (linkIn) {
        linkIn.classList.toggle('d-none', !hasIn || !c.checkinPageUrl);
        if (c.checkinPageUrl) linkIn.setAttribute('href', c.checkinPageUrl);
      }
      if (linkOut) {
        linkOut.classList.toggle('d-none', !hasOut || !c.checkoutPageUrl);
        if (c.checkoutPageUrl) linkOut.setAttribute('href', c.checkoutPageUrl);
      }
      if (linkTask) {
        linkTask.classList.toggle('d-none', !hasOdom || !c.taskEntryPageUrl);
        if (c.taskEntryPageUrl) linkTask.setAttribute('href', c.taskEntryPageUrl);
      }
    }
  }

  function refreshBanner() {
    var items = listAllPending();
    if (items.length) {
      if (successHideTimer) {
        clearTimeout(successHideTimer);
        successHideTimer = null;
      }
      setBannerState('pending', { items: items });
      return;
    }
    stopGlobalAutoRetry();
    if (isDashboardPage()) {
      setBannerState('success');
      if (successHideTimer) clearTimeout(successHideTimer);
      successHideTimer = setTimeout(function () {
        successHideTimer = null;
        if (!listAllPending().length) setBannerState('hidden');
      }, 8000);
    } else {
      setBannerState('hidden');
    }
  }

  function retryAllPending(isAuto) {
    var items = listAllPending();
    if (!items.length) {
      refreshBanner();
      return Promise.resolve([]);
    }
    if (retryInFlight) return Promise.resolve([]);
    retryInFlight = true;
    setBannerState('retrying', {
      title: isAuto ? 'Auto-retry: uploading…' : 'Retrying upload…',
      items: items,
    });

    var chain = Promise.resolve();
    var results = [];
    items.forEach(function (item) {
      chain = chain.then(function () {
        return retryItem(item).then(function (r) {
          results.push(r);
        });
      });
    });

    return chain.then(function () {
      retryInFlight = false;
      refreshBanner();
      dispatchChanged();
      if (listAllPending().length) startGlobalAutoRetry();
      return results;
    }).catch(function () {
      retryInFlight = false;
      refreshBanner();
      dispatchChanged();
      return results;
    });
  }

  function startGlobalAutoRetry() {
    if (retryTimer || !listAllPending().length) return;
    retryTimer = setInterval(function () {
      if (!listAllPending().length) {
        stopGlobalAutoRetry();
        refreshBanner();
        return;
      }
      retryAllPending(true);
    }, RETRY_MS);
  }

  function stopGlobalAutoRetry() {
    if (retryTimer) {
      clearInterval(retryTimer);
      retryTimer = null;
    }
  }

  function triggerSoon() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      debounceTimer = null;
      refreshBanner();
      if (!listAllPending().length) return;
      startGlobalAutoRetry();
      retryAllPending(true);
    }, 400);
  }

  function setupListeners() {
    global.addEventListener('online', triggerSoon);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) triggerSoon();
    });
    if (global.Capacitor && global.Capacitor.Plugins && global.Capacitor.Plugins.App) {
      global.Capacitor.Plugins.App.addListener('appStateChange', function (state) {
        if (state && state.isActive) triggerSoon();
      });
    }
    global.addEventListener('storage', function (e) {
      if (!e.key) return;
      if (e.key.indexOf('gps-attendance:') !== 0 && e.key.indexOf('task-odometer:') !== 0) return;
      refreshBanner();
      if (listAllPending().length) startGlobalAutoRetry();
      else stopGlobalAutoRetry();
    });
  }

  function odometerStorageKey(taskDate, vehicleId) {
    return ODOMETER_PREFIX + (taskDate || currentDateDmy()) + ':' + String(vehicleId || '');
  }

  function saveOdometerPending(vehicleId, taskDate, payload) {
    if (!vehicleId || !payload || !payload.photo_base64) return;
    localStorage.setItem(odometerStorageKey(taskDate, vehicleId), JSON.stringify(payload));
    triggerSoon();
  }

  function clearOdometerPending(vehicleId, taskDate) {
    if (!vehicleId) return;
    localStorage.removeItem(odometerStorageKey(taskDate, vehicleId));
    refreshBanner();
    dispatchChanged();
  }

  function init() {
    var el = getBannerEl();
    var c = cfg();
    if (!el || (!c.checkinUrl && !c.odometerUploadUrl)) return;
    setupListeners();
    refreshBanner();
    if (listAllPending().length) {
      startGlobalAutoRetry();
      retryAllPending(true);
    }
  }

  function refresh() {
    refreshBanner();
    if (listAllPending().length) startGlobalAutoRetry();
    else stopGlobalAutoRetry();
  }

  function retryDriver(kind, driverId, isAuto) {
    var id = String(driverId || '');
    var match = listAllPending().filter(function (it) {
      return it.kind === kind && String(it.driverId) === id;
    });
    if (!match.length) return Promise.resolve(false);
    if (retryInFlight) return Promise.resolve(false);
    retryInFlight = true;
    setBannerState('retrying', { items: match });
    var chain = Promise.resolve(false);
    match.forEach(function (item) {
      chain = chain.then(function (prevOk) {
        return retryItem(item).then(function (r) {
          return prevOk || r.ok;
        });
      });
    });
    return chain.then(function (ok) {
      retryInFlight = false;
      refreshBanner();
      dispatchChanged();
      if (listAllPending().length) startGlobalAutoRetry();
      return ok;
    }).catch(function () {
      retryInFlight = false;
      refreshBanner();
      dispatchChanged();
      return false;
    });
  }

  global.FleetGpsPendingUpload = {
    refresh: refresh,
    retryAll: retryAllPending,
    retryDriver: retryDriver,
    listPending: listAllPending,
    saveOdometerPending: saveOdometerPending,
    clearOdometerPending: clearOdometerPending,
    init: init,
    stop: stopGlobalAutoRetry,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
