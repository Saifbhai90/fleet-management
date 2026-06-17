/**
 * Per-user/device diagnostics: slow page loads, JS errors, failed fetch.
 * Batched to /api/client-diagnostics — lightweight, rate-limited per session.
 */
(function(global) {
  'use strict';

  var MAX_EVENTS_PER_SESSION = 30;
  var SLOW_PAGE_MS = 8000;
  var queue = [];
  var flushTimer = null;
  var apiUrl = '';
  var csrfToken = '';
  var deviceMeta = null;

  function sessionCount() {
    try {
      return parseInt(sessionStorage.getItem('_fleetDiagCount') || '0', 10) || 0;
    } catch (e) {
      return 0;
    }
  }

  function bumpSessionCount(n) {
    try {
      sessionStorage.setItem('_fleetDiagCount', String(sessionCount() + n));
    } catch (e) { /* ignore */ }
  }

  function getDeviceId() {
    try {
      var key = 'fleet_device_id';
      var id = localStorage.getItem(key);
      if (!id) {
        id = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
          var r = Math.random() * 16 | 0;
          var v = c === 'x' ? r : (r & 0x3 | 0x8);
          return v.toString(16);
        });
        localStorage.setItem(key, id);
      }
      return id;
    } catch (e2) {
      return '';
    }
  }

  function networkType() {
    try {
      var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
      if (!conn) return '';
      return (conn.effectiveType || conn.type || '').toString().substring(0, 40);
    } catch (e) {
      return '';
    }
  }

  function loadDeviceMeta(cb) {
    if (deviceMeta) {
      cb(deviceMeta);
      return;
    }
    deviceMeta = { device_model: '', os_version: '', network_type: networkType() };
    try {
      var cap = global.Capacitor;
      var dev = cap && cap.Plugins && cap.Plugins.Device;
      if (!dev || !dev.getInfo) {
        cb(deviceMeta);
        return;
      }
      dev.getInfo().then(function(info) {
        deviceMeta.device_model = ((info && info.model) || (info && info.name) || '').substring(0, 120);
        deviceMeta.os_version = (((info && info.operatingSystem) || '') + ' ' + ((info && info.osVersion) || '')).trim().substring(0, 80);
        cb(deviceMeta);
      }).catch(function() { cb(deviceMeta); });
    } catch (e) {
      cb(deviceMeta);
    }
  }

  function enqueue(evt) {
    if (!apiUrl || sessionCount() >= MAX_EVENTS_PER_SESSION) return;
    evt.device_id = evt.device_id || getDeviceId();
    evt.page_path = evt.page_path || (global.location && global.location.pathname) || '';
    evt.network_type = evt.network_type || networkType();
    queue.push(evt);
    if (flushTimer) return;
    flushTimer = global.setTimeout(flush, 1200);
  }

  function flush() {
    flushTimer = null;
    if (!queue.length || !apiUrl) return;
    var batch = queue.splice(0, 8);
    bumpSessionCount(batch.length);
    loadDeviceMeta(function(meta) {
      batch.forEach(function(row) {
        row.device_model = row.device_model || meta.device_model;
        row.os_version = row.os_version || meta.os_version;
        if (!row.network_type) row.network_type = meta.network_type;
      });
      var headers = { 'Content-Type': 'application/json' };
      if (csrfToken) headers['X-CSRFToken'] = csrfToken;
      global.fetch(apiUrl, {
        method: 'POST',
        headers: headers,
        credentials: 'same-origin',
        body: JSON.stringify({ events: batch })
      }).catch(function() {});
    });
  }

  function reportSlowPageLoad() {
    try {
      var nav = performance.getEntriesByType && performance.getEntriesByType('navigation');
      var entry = nav && nav[0];
      if (!entry) return;
      var ms = Math.round(entry.duration || 0);
      if (ms < SLOW_PAGE_MS) return;
      enqueue({
        event_type: 'slow_page',
        duration_ms: ms,
        message: 'Page load ' + ms + 'ms'
      });
    } catch (e) { /* ignore */ }
  }

  global.fleetInitClientDiagnostics = function(url, csrf) {
    apiUrl = url || '';
    csrfToken = csrf || '';
    if (!apiUrl) return;

    global.addEventListener('load', function() {
      global.setTimeout(reportSlowPageLoad, 0);
    });

    global.addEventListener('error', function(ev) {
      var msg = (ev && ev.message) || 'Script error';
      var src = (ev && ev.filename) || '';
      enqueue({
        event_type: 'js_error',
        message: (msg + ' @ ' + src).substring(0, 900)
      });
    });

    global.addEventListener('unhandledrejection', function(ev) {
      var reason = ev && ev.reason;
      var text = reason && (reason.message || String(reason)) || 'Unhandled rejection';
      enqueue({
        event_type: 'js_error',
        message: ('Promise: ' + text).substring(0, 900)
      });
    });

    global.addEventListener('offline', function() {
      enqueue({ event_type: 'offline', message: 'Device went offline' });
    });
  };

  global.fleetReportClientDiagnostic = enqueue;
})(window);
