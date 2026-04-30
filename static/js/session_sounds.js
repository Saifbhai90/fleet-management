/* Fleet session sounds (classic Windows-style chimes) */
(function() {
  var _lastFeedbackAt = 0;
  var _feedbackGapMs = 700;
  var _observerInstalled = false;
  var _unlockHandlersInstalled = false;

  function getCtx() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!window.__fleetSessionAudioCtx) {
      window.__fleetSessionAudioCtx = new Ctx();
    }
    return window.__fleetSessionAudioCtx;
  }

  function playTone(ctx, freq, durationMs, gainValue, atTime, type) {
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = type || 'sine';
    osc.frequency.setValueAtTime(freq, atTime);
    gain.gain.setValueAtTime(0.0001, atTime);
    gain.gain.exponentialRampToValueAtTime(gainValue, atTime + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, atTime + (durationMs / 1000));
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(atTime);
    osc.stop(atTime + (durationMs / 1000) + 0.02);
  }

  function playPattern(tones) {
    var ctx = getCtx();
    if (!ctx) return Promise.resolve(false);
    var run = function() {
      if (ctx.state !== 'running') return false;
      var start = ctx.currentTime + 0.01;
      tones.forEach(function(t) {
        playTone(ctx, t.f, t.d, t.g || 0.08, start + (t.o || 0), t.w);
      });
      return true;
    };
    if (ctx.state === 'suspended') {
      return ctx.resume().catch(function() {}).then(run);
    }
    return Promise.resolve(run());
  }

  function unlockOnGesture() {
    if (_unlockHandlersInstalled) return;
    _unlockHandlersInstalled = true;

    var unlock = function() {
      var ctx = getCtx();
      if (ctx && ctx.state === 'suspended') ctx.resume().catch(function() {});
    };
    ['pointerdown', 'keydown', 'touchstart', 'click', 'submit'].forEach(function(ev) {
      document.addEventListener(ev, unlock, true);
    });
  }

  window.fleetSessionSounds = {
    init: function() {
      unlockOnGesture();
    },
    play: function(kind) {
      if (kind === 'login') {
        return playPattern([
          { f: 659.25, d: 110, o: 0.00, g: 0.055, w: 'sine' },
          { f: 830.61, d: 140, o: 0.10, g: 0.065, w: 'sine' },
          { f: 987.77, d: 220, o: 0.23, g: 0.072, w: 'triangle' }
        ]);
      }
      if (kind === 'logout-auto') {
        return playPattern([
          { f: 622.25, d: 130, o: 0.00, g: 0.055, w: 'sine' },
          { f: 493.88, d: 170, o: 0.11, g: 0.065, w: 'triangle' },
          { f: 369.99, d: 250, o: 0.25, g: 0.072, w: 'sine' }
        ]);
      }
      if (kind === 'logout-manual') {
        return playPattern([
          { f: 740.00, d: 120, o: 0.00, g: 0.055, w: 'sine' },
          { f: 622.25, d: 155, o: 0.10, g: 0.062, w: 'triangle' },
          { f: 466.16, d: 240, o: 0.22, g: 0.07, w: 'sine' }
        ]);
      }
      if (kind === 'workspace-load') {
        return playPattern([
          { f: 440.00, d: 90, o: 0.00, g: 0.052, w: 'triangle' },
          { f: 554.37, d: 120, o: 0.09, g: 0.06, w: 'sine' },
          { f: 698.46, d: 170, o: 0.20, g: 0.066, w: 'triangle' }
        ]);
      }
      if (kind === 'warning') {
        return playPattern([
          { f: 784.00, d: 110, o: 0.00, g: 0.052, w: 'triangle' },
          { f: 659.25, d: 130, o: 0.10, g: 0.058, w: 'sine' }
        ]);
      }
      if (kind === 'error') {
        return playPattern([
          { f: 392.00, d: 120, o: 0.00, g: 0.06, w: 'square' },
          { f: 329.63, d: 145, o: 0.11, g: 0.065, w: 'square' },
          { f: 261.63, d: 190, o: 0.24, g: 0.07, w: 'triangle' }
        ]);
      }
      return Promise.resolve(false);
    },
    playFeedback: function(level) {
      var now = Date.now();
      if (now - _lastFeedbackAt < _feedbackGapMs) return Promise.resolve(false);
      _lastFeedbackAt = now;
      if (level === 'error') return this.play('error');
      if (level === 'warning') return this.play('warning');
      return Promise.resolve(false);
    },
    installGlobalFeedbackSounds: function() {
      if (_observerInstalled) return;
      _observerInstalled = true;
      this.init();
      var self = this;

      function getLevel(el) {
        if (!el || !el.classList) return '';
        var cls = ' ' + (el.className || '') + ' ';
        if (cls.indexOf(' swal2-icon-error ') !== -1 || cls.indexOf(' swal2-validation-message ') !== -1) return 'error';
        if (cls.indexOf(' swal2-icon-warning ') !== -1 || cls.indexOf(' swal2-icon-question ') !== -1) return 'warning';
        if (cls.indexOf(' danger ') !== -1 || cls.indexOf(' alert-danger ') !== -1 || cls.indexOf(' error ') !== -1 || cls.indexOf(' alert-error ') !== -1) return 'error';
        if (cls.indexOf(' warning ') !== -1 || cls.indexOf(' alert-warning ') !== -1 || cls.indexOf(' message ') !== -1) return 'warning';
        return '';
      }

      function scanAndPlay(root) {
        if (!root || !root.querySelectorAll) return;
        var nodes = root.querySelectorAll('.alert, .lp-toast, .toast, .swal2-popup, .swal2-container');
        var hasError = false;
        var hasWarning = false;
        nodes.forEach(function(n) {
          var lvl = getLevel(n);
          if (lvl === 'error') hasError = true;
          if (lvl === 'warning') hasWarning = true;
        });
        if (hasError) { self.playFeedback('error'); return; }
        if (hasWarning) self.playFeedback('warning');
      }

      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { scanAndPlay(document); }, { once: true });
      } else {
        scanAndPlay(document);
      }

      var observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(m) {
          if (m.type === 'childList' && m.addedNodes && m.addedNodes.length) {
            m.addedNodes.forEach(function(node) {
              if (!node || node.nodeType !== 1) return;
              var lvl = getLevel(node);
              if (lvl) {
                self.playFeedback(lvl);
              } else {
                scanAndPlay(node);
              }
            });
          }
          if (m.type === 'attributes' && m.target && m.target.nodeType === 1) {
            var lvl2 = getLevel(m.target);
            if (lvl2) self.playFeedback(lvl2);
          }
        });
      });
      observer.observe(document.body || document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['class']
      });
    }
  };
})();
