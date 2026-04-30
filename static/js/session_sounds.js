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

  function playTone(ctx, freq, durationMs, gainValue, atTime) {
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'sine';
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
          playTone(ctx, t.f, t.d, t.g || 0.08, start + (t.o || 0));
        });
        return true;
      });
    }
    var start = ctx.currentTime + 0.01;
    tones.forEach(function(t) {
      playTone(ctx, t.f, t.d, t.g || 0.08, start + (t.o || 0));
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
          { f: 523.25, d: 140, o: 0.00, g: 0.07 },
          { f: 659.25, d: 170, o: 0.12, g: 0.08 },
          { f: 783.99, d: 220, o: 0.25, g: 0.09 }
        ]);
      }
      if (kind === 'logout-auto') {
        return playPattern([
          { f: 523.25, d: 160, o: 0.00, g: 0.08 },
          { f: 392.00, d: 190, o: 0.13, g: 0.08 },
          { f: 261.63, d: 260, o: 0.28, g: 0.09 }
        ]);
      }
      if (kind === 'logout-manual') {
        return playPattern([
          { f: 587.33, d: 130, o: 0.00, g: 0.07 },
          { f: 493.88, d: 160, o: 0.11, g: 0.07 },
          { f: 349.23, d: 230, o: 0.23, g: 0.08 }
        ]);
      }
      return Promise.resolve(false);
    }
  };
})();
