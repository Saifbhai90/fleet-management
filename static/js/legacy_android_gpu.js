/**
 * Mark legacy/low-end Android WebViews where backdrop-filter causes foggy full-screen UI.
 */
(function () {
  'use strict';

  function applyLegacyGpuClass() {
    document.documentElement.classList.add('legacy-android-gpu');
    if (document.body) {
      document.body.classList.add('legacy-android-gpu');
    }
  }

  function uaLooksLegacyAndroid() {
    var ua = navigator.userAgent || '';
    if (!/Android/i.test(ua)) {
      return false;
    }
    if (/CPH1909|OPPO\s*A5s|OPPO\s*A5\b/i.test(ua)) {
      return true;
    }
    var m = ua.match(/Android\s+([\d.]+)/i);
    if (!m) {
      return false;
    }
    var parts = m[1].split('.');
    var major = parseInt(parts[0], 10);
    if (isNaN(major)) {
      return false;
    }
    /* Android 9 (Pie) and below — includes 8.1 (API 27) from activity log */
    return major <= 9;
  }

  if (uaLooksLegacyAndroid()) {
    applyLegacyGpuClass();
  }

  function checkCapacitorDevice() {
    if (!window.Capacitor || !window.Capacitor.Plugins || !window.Capacitor.Plugins.Device) {
      return;
    }
    window.Capacitor.Plugins.Device.getInfo()
      .then(function (info) {
        if (!info || String(info.platform || '').toLowerCase() !== 'android') {
          return;
        }
        var sdk = parseInt(info.androidSDKVersion, 10);
        if (!isNaN(sdk) && sdk <= 27) {
          applyLegacyGpuClass();
        }
      })
      .catch(function () {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkCapacitorDevice);
  } else {
    checkCapacitorDevice();
  }

  window.fleetIsLegacyAndroidGpu = function () {
    return document.documentElement.classList.contains('legacy-android-gpu');
  };
})();
