/**
 * Workspace Slip OCR v3 — server-side OCR fallback.
 *
 * When the browser Tesseract.js path + universal scan + OpenCV retry all leave
 * one or more fields below FALLBACK_CONFIDENCE, this module POSTs the slip
 * image to the in-house server endpoint (/api/workspace-slip-server-ocr) which
 * runs PaddleOCR / EasyOCR / Tesseract.
 *
 * 100% in-house: the image goes to OUR server only, never to a third party.
 *
 * Integration: hooked from 05_extract.js applyUniversalFallback as the final
 * tier, and exposed on window.WorkspaceSlipTemplate.serverOcrFallback.
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr;
  if (!Ws) return;

  var SERVER_ENDPOINT = '/api/workspace-slip-server-ocr';

  /** Compress an image to JPEG bytes for upload (keeps payload small + fast). */
  function imageToCompressedBlob(img, maxW) {
    return new Promise(function (resolve, reject) {
      try {
        var target = Ws.slipDrawTarget ? Ws.slipDrawTarget(img) : img;
        var size = Ws.imagePixelSize(img);
        var scale = (maxW && size.w > maxW) ? maxW / size.w : 1;
        var c = document.createElement('canvas');
        c.width = Math.max(1, Math.round(size.w * scale));
        c.height = Math.max(1, Math.round(size.h * scale));
        var ctx = c.getContext('2d');
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, c.width, c.height);
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(target, 0, 0, c.width, c.height);
        if (c.toBlob) {
          c.toBlob(function (blob) {
            if (blob) resolve(blob);
            else reject(new Error('toBlob empty'));
          }, 'image/jpeg', 0.85);
        } else {
          var dataUrl = c.toDataURL('image/jpeg', 0.85);
          var b64 = dataUrl.split(',')[1];
          var bin = atob(b64);
          var arr = new Uint8Array(bin.length);
          for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
          resolve(new Blob([arr], { type: 'image/jpeg' }));
        }
      } catch (e) {
        reject(e);
      }
    });
  }

  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.getAttribute('content');
    var cookie = (document.cookie || '').match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return cookie ? decodeURIComponent(cookie[1]) : null;
  }

  /**
   * Run server OCR on a slip image. Returns a fieldResult-shaped object:
   *   { date, amount, reference_no, fieldMeta, serverEngine, confidence }
   * Never throws — on any failure resolves to a null result so the caller's
   * existing browser result is preserved.
   *
   * @param img       loaded Image / wrapped canvas (from loadImageFromFile)
   * @param opts      { dateFormat, maxW }
   */
  Ws.serverOcrFallback = function serverOcrFallback(img, opts) {
    opts = opts || {};
    if (!Ws.serverOcrEnabled || Ws.serverOcrEnabled() === false) {
      return Promise.resolve(null);
    }
    var prepared;
    try {
      prepared = Ws.prepareSlipImage(img);
    } catch (e) {
      return Promise.resolve(null);
    }
    return imageToCompressedBlob(prepared, opts.maxW || 1280).then(function (blob) {
      var fd = new FormData();
      fd.append('image', blob, 'slip.jpg');
      if (opts.dateFormat) fd.append('date_format', opts.dateFormat);
      var headers = {};
      var token = getCsrfToken();
      if (token) headers['X-CSRFToken'] = token;
      Ws.ocrLog('server OCR fallback — sending');
      return fetch(SERVER_ENDPOINT, {
        method: 'POST', body: fd, headers: headers, credentials: 'same-origin',
      });
    }).then(function (r) {
      if (!r || !r.ok) return null;
      return r.json();
    }).then(function (j) {
      if (!j || !j.ok) {
        Ws.ocrLog('server OCR not available', j && j.error);
        return null;
      }
      var fieldMeta = {};
      Ws.FIELD_KEYS.forEach(function (k) {
        var v = j[k];
        fieldMeta[k] = Ws.fieldResult(v || null, v ? (j.confidence || 0.72) : 0, 'server-' + (j.engine || 'unknown'));
      });
      return {
        date: j.date || null,
        amount: j.amount || null,
        reference_no: j.reference_no || null,
        fieldMeta: fieldMeta,
        serverEngine: j.engine || 'unknown',
        confidence: j.confidence || 0,
        ocrText: j.raw_text || '',
      };
    }).catch(function (err) {
      Ws.ocrLog('server OCR error', err && err.message);
      return null;
    });
  };

  /** Whether server fallback should be attempted. Default: enabled, can disable via config. */
  Ws.serverOcrEnabled = function serverOcrEnabled() {
    var cfg = global.__wsSlipOcrConfig || {};
    return cfg.serverFallback !== false;
  };

})(window);
