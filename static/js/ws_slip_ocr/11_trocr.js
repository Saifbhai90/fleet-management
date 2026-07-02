/**
 * Workspace Slip OCR v3 — Transformers.js TrOCR browser fallback.
 *
 * Optional LAST-RESORT tier: runs Microsoft TrOCR (Apache-2.0) entirely in
 * the browser via Transformers.js (WASM / WebGPU). Used only when:
 *   - server OCR is unavailable AND
 *   - browser Tesseract confidence is still low.
 *
 * The model (~100-300MB) is downloaded ONCE from HuggingFace and cached by
 * the browser. Disabled by default; enable via window.__wsSlipOcrConfig.trocr.
 *
 * Hooked into 05_extract.js as a final fallback after server OCR returns null.
 * If Transformers.js fails to load, this tier silently no-ops.
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr;
  if (!Ws) return;

  var _pipeline = null;       // Promise<pipeline>
  var _failed = false;

  /** TrOCR is opt-in (large download). */
  function isEnabled() {
    var cfg = global.__wsSlipOcrConfig || {};
    return cfg.trocr === true;
  }

  function loadTransformers() {
    if (global.transformers) return Promise.resolve(global.transformers);
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.0.0';
      s.async = true;
      s.onload = function () { resolve(global.transformers); };
      s.onerror = function () { reject(new Error('transformers.js load failed')); };
      document.head.appendChild(s);
    });
  }

  function ensurePipeline() {
    if (_failed) return Promise.resolve(null);
    if (_pipeline) return _pipeline;
    if (!isEnabled()) return Promise.resolve(null);
    _pipeline = loadTransformers().then(function (T) {
      return T.pipeline('image-to-text', 'Xenova/trocr-base-printed');
    }).then(function (pipe) {
      Ws.ocrLog('trocr pipeline ready');
      return pipe;
    }).catch(function (err) {
      Ws.ocrLog('trocr unavailable', err && err.message);
      _failed = true;
      _pipeline = null;
      return null;
    });
    return _pipeline;
  }

  /**
   * Recognise text on a canvas region. Returns the text string (maybe '').
   * Resolves to null when disabled or unavailable.
   */
  Ws.trocrRecognize = function trocrRecognize(canvas) {
    if (!isEnabled()) return Promise.resolve(null);
    return ensurePipeline().then(function (pipe) {
      if (!pipe) return null;
      return pipe(canvas, { callback_function: null });
    }).then(function (out) {
      if (!out) return null;
      if (Array.isArray(out) && out[0] && out[0].generated_text) {
        return out[0].generated_text;
      }
      return String(out || '');
    }).catch(function () { return null; });
  };

})(window);
