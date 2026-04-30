/* Fleet session sounds (classic Windows-style chimes) */
(function() {
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
    if (ctx.state === 'suspended') {
      return ctx.resume().catch(function() {}).then(function() {
        var start = ctx.currentTime + 0.01;
        tones.forEach(function(t) {
          playTone(ctx, t.f, t.d, t.g || 0.08, start + (t.o || 0), t.w);
        });
        return true;
      });
    }
    var start = ctx.currentTime + 0.01;
    tones.forEach(function(t) {
      playTone(ctx, t.f, t.d, t.g || 0.08, start + (t.o || 0), t.w);
    });
    return Promise.resolve(true);
  }

  function unlockOnGesture() {
    var once = function() {
      var ctx = getCtx();
      if (ctx && ctx.state === 'suspended') ctx.resume().catch(function() {});
      ['pointerdown', 'keydown', 'touchstart'].forEach(function(ev) {
        document.removeEventListener(ev, once, true);
      });
    };
    ['pointerdown', 'keydown', 'touchstart'].forEach(function(ev) {
      document.addEventListener(ev, once, true);
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
      return Promise.resolve(false);
    }
  };
})();
