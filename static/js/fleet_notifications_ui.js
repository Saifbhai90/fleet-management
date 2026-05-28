/**
 * Modern notification cards: swipe-to-dismiss (mobile) + delete button (web/mobile).
 */
(function (global) {
  'use strict';

  function csrfToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') || '' : '';
  }

  function isMobileUi() {
    if (global.FleetBridge && global.FleetBridge.isNative) return true;
    if (global.Capacitor && global.Capacitor.isNativePlatform && global.Capacitor.isNativePlatform()) return true;
    return global.matchMedia && global.matchMedia('(max-width: 768px)').matches;
  }

  function showUserMessage(msg) {
    if (global.Capacitor && global.Capacitor.Plugins && global.Capacitor.Plugins.Toast) {
      global.Capacitor.Plugins.Toast.show({ text: msg, duration: 'short', position: 'bottom' });
      return;
    }
    var host = document.getElementById('fleetNotifToastHost');
    if (!host) {
      host = document.createElement('div');
      host.id = 'fleetNotifToastHost';
      host.className = 'fleet-notif-toast-host';
      document.body.appendChild(host);
    }
    var el = document.createElement('div');
    el.className = 'fleet-notif-toast';
    el.textContent = msg;
    host.appendChild(el);
    setTimeout(function () {
      el.classList.add('fleet-notif-toast--out');
      setTimeout(function () { el.remove(); }, 320);
    }, 2800);
  }

  function confirmDelete(cb) {
    if (global.confirm('Are you sure delete this notification?')) cb();
  }

  function dismissNotification(id, cardEl) {
    var url = '/notification/' + encodeURIComponent(id) + '/dismiss';
    fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    }).then(function (r) {
      return r.json().catch(function () { return { ok: r.ok }; });
    }).then(function (data) {
      if (!data || !data.ok) {
        showUserMessage('Could not delete notification. Try again.');
        if (cardEl) {
          cardEl.classList.remove('fleet-notif-card--removing');
          cardEl.style.transform = '';
        }
        return;
      }
      if (cardEl) {
        cardEl.classList.add('fleet-notif-card--removed');
        setTimeout(function () { cardEl.remove(); }, 280);
      }
      showUserMessage(data.message || 'Notification deleted.');
      document.querySelectorAll('.navbar .badge.bg-danger, .more-notif-badge').forEach(function (badge) {
        var n = parseInt(badge.textContent, 10) || 0;
        if (n <= 1) badge.remove();
        else badge.textContent = String(n - 1);
      });
    }).catch(function () {
      showUserMessage('Network error — try again.');
      if (cardEl) {
        cardEl.classList.remove('fleet-notif-card--removing');
        cardEl.style.transform = '';
      }
    });
  }

  function bindSwipe(card) {
    var track = card.querySelector('.fleet-notif-card__track');
    if (!track) return;
    var startX = 0;
    var currentX = 0;
    var dragging = false;

    function onStart(x) {
      startX = x;
      currentX = 0;
      dragging = true;
      track.style.transition = 'none';
    }
    function onMove(x) {
      if (!dragging) return;
      currentX = Math.min(0, x - startX);
      if (currentX < -120) currentX = -120;
      track.style.transform = 'translateX(' + currentX + 'px)';
    }
    function onEnd() {
      if (!dragging) return;
      dragging = false;
      track.style.transition = 'transform 0.22s ease';
      if (currentX < -72) {
        track.style.transform = 'translateX(-100%)';
        card.classList.add('fleet-notif-card--removing');
        var id = card.getAttribute('data-notification-id');
        dismissNotification(id, card);
      } else {
        track.style.transform = '';
      }
    }

    track.addEventListener('touchstart', function (e) {
      if (!isMobileUi()) return;
      onStart(e.touches[0].clientX);
    }, { passive: true });
    track.addEventListener('touchmove', function (e) {
      if (!isMobileUi() || !dragging) return;
      onMove(e.touches[0].clientX);
    }, { passive: true });
    track.addEventListener('touchend', onEnd);
    track.addEventListener('touchcancel', onEnd);
  }

  function bindDeleteButtons(root) {
    (root || document).querySelectorAll('.fleet-notif-delete-btn').forEach(function (btn) {
      if (btn.getAttribute('data-bound') === '1') return;
      btn.setAttribute('data-bound', '1');
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var card = btn.closest('.fleet-notif-card');
        if (!card) return;
        var id = card.getAttribute('data-notification-id');
        confirmDelete(function () {
          card.classList.add('fleet-notif-card--removing');
          dismissNotification(id, card);
        });
      });
    });
  }

  function init() {
    document.querySelectorAll('.fleet-notif-card').forEach(function (card) {
      bindSwipe(card);
    });
    bindDeleteButtons(document);
    if (isMobileUi()) {
      document.body.classList.add('fleet-notif-mobile');
    }
  }

  global.FleetNotificationsUi = { init: init, dismiss: dismissNotification };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
