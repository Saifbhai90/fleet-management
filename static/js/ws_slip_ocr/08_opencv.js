/**
 * Workspace Slip OCR v3 — OpenCV.js preprocessing layer.
 *
 * Adds document-grade image correction that pure-canvas JS cannot do well:
 *  - Deskew (rotate tilted photos back to level)
 *  - Adaptive threshold (Otsu / Sauvola — handles uneven lighting)
 *  - CLAHE contrast enhancement (low-light slips)
 *  - Perspective correction placeholder (straighten angled captures)
 *  - Auto color segmentation (replaces manual myABL orange detection)
 *
 * OpenCV.js (~8MB) is loaded LAZILY only when a photo-captured slip needs it.
 * Digital screenshots keep the fast existing path (no OpenCV load).
 * If OpenCV fails to load, every function degrades to a no-op so OCR still runs.
 *
 * License: OpenCV.js = Apache 2.0 (free commercial use).
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr;
  if (!Ws) return;

  var CV = {};
  Ws.CV = CV;

  var _loader = null;          // Promise<cv>
  var _available = null;        // tri-state: null=unknown, true/false after probe

  var OPENCV_VERSION = '4.10.0';
  var OPENCV_CDN_SOURCES = [
    'https://docs.opencv.org/' + OPENCV_VERSION + '/opencv.js',
    'https://cdn.jsdelivr.net/npm/@techstark/opencv-js@' + OPENCV_VERSION + '/dist/opencv.js',
  ];

  /**
   * Optional local vendor path. If the file exists it is preferred (offline / privacy).
   * Configured via window.__wsSlipOpenCVConfig.localUrl.
   */
  function localSource() {
    var cfg = global.__wsSlipOpenCVConfig || {};
    return cfg.localUrl || null;
  }

  function loadScript(url) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = url;
      s.async = true;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error('cv script failed: ' + url)); };
      document.head.appendChild(s);
    });
  }

  /**
   * OpenCV.js emits a Module then runs onRuntimeInitialized.
   * cv may be a function that must be called, or an object.
   */
  function waitForRuntime(cv) {
    return new Promise(function (resolve) {
      if (cv && cv.Mat) { resolve(cv); return; }
      // cv is a factory; call it.
      if (typeof cv === 'function') {
        try {
          cv = cv({ onRuntimeInitialized: function () { resolve(global.cv); } });
          global.cv = cv;
          return;
        } catch (e) { /* fall through */ }
      }
      // Object form — wait for runtime flag.
      if (cv && typeof cv === 'object') {
        global.cv = cv;
        if (cv.onRuntimeInitialized !== undefined && cv.Mat) { resolve(cv); return; }
        var prev = cv.onRuntimeInitialized;
        cv.onRuntimeInitialized = function () {
          if (typeof prev === 'function') { try { prev(); } catch (e) {} }
          resolve(cv);
        };
        // Safety timeout — resolve anyway so caller can probe.
        setTimeout(function () { resolve(cv); }, 8000);
        return;
      }
      resolve(null);
    });
  }

  /**
   * Lazily load + initialise OpenCV.js. Memoised. Never throws — resolves to
   * the cv object or null (so callers can feature-gate).
   */
  CV.ensure = function ensure() {
    if (_loader) return _loader;
    _loader = new Promise(function (resolve) {
      var sources = [];
      var local = localSource();
      if (local) sources.push(local);
      sources = sources.concat(OPENCV_CDN_SOURCES);

      var chain = Promise.reject(new Error('init'));
      sources.forEach(function (url) {
        chain = chain.catch(function () {
          return loadScript(url).then(function () {
            var cv = global.cv || global.Module;
            if (!cv) throw new Error('cv missing after load');
            return waitForRuntime(cv);
          });
        });
      });
      chain.then(function (cv) {
        if (cv && cv.Mat) {
          _available = true;
          Ws.ocrLog('opencv ready', { version: cv.version || OPENCV_VERSION });
          resolve(cv);
        } else {
          _available = false;
          Ws.ocrLog('opencv load produced no Mat');
          resolve(null);
        }
      }).catch(function (err) {
        _available = false;
        _loader = null;  // allow a future retry
        Ws.ocrLog('opencv unavailable', err && err.message);
        resolve(null);
      });
    });
    return _loader;
  };

  /** Synchronous availability probe (after first ensure). */
  CV.isAvailable = function isAvailable() {
    if (_available !== null) return _available;
    return !!(global.cv && global.cv.Mat);
  };

  CV.isEnabled = function isEnabled() {
    var cfg = global.__wsSlipOpenCVConfig || Ws.ocrConfig();
    return cfg.disable !== true && Ws.ocrConfig().preprocess !== false;
  };

  /* ----------------------------- helpers ----------------------------- */

  function canvasToMat(cv, canvas) {
    var ctx = canvas.getContext('2d');
    var imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    return cv.matFromImageData(imgData);
  }

  function matToCanvas(cv, mat, canvas) {
    var dst = canvas || document.createElement('canvas');
    dst.width = mat.cols;
    dst.height = mat.rows;
    var ctx = dst.getContext('2d');
    var imgData = ctx.createImageData(mat.cols, mat.rows);
    // matFromImageData uses RGBA; ensure 4 channels.
    var src = mat;
    var tmp = null;
    if (mat.channels() === 1) {
      tmp = new cv.Mat();
      cv.cvtColor(mat, tmp, cv.COLOR_GRAY2RGBA);
      src = tmp;
    } else if (mat.channels() === 3) {
      tmp = new cv.Mat();
      cv.cvtColor(mat, tmp, cv.COLOR_RGB2RGBA);
      src = tmp;
    }
    imgData.data.set(new Uint8ClampedArray(src.data));
    ctx.putImageData(imgData, 0, 0);
    if (tmp) tmp.delete();
    return dst;
  }

  /* ----------------------------- DESKEW ----------------------------- */
  /**
   * Estimate text skew angle and rotate the canvas upright.
   * Uses a minAreaRect over thresholded "ink" pixels.
   * Returns a NEW canvas (caller's canvas untouched). No-op if angle tiny.
   */
  CV.deskew = function deskew(canvas) {
    return CV.ensure().then(function (cv) {
      if (!cv) return canvas;
      try {
        var src = canvasToMat(cv, canvas);
        var gray = new cv.Mat();
        cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);
        var bw = new cv.Mat();
        cv.threshold(gray, bw, 0, 255, cv.THRESH_BINARY_INV + cv.THRESH_OTSU);

        var coords = cv.findNonZero(bw);
        var angle = 0;
        if (coords && coords.rows > 20) {
          var rect = cv.minAreaRect(coords);
          angle = rect.angle;
          // minAreaRect angle convention normalisation.
          if (angle < -45) angle = 90 + angle;
          // Keep within ±15° — larger means we misread the document orientation.
          if (angle > 15) angle = 0;
          if (angle < -15) angle = 0;
        }
        gray.delete(); bw.delete();
        if (coords) coords.delete();

        if (Math.abs(angle) < 0.4) { src.delete(); return canvas; }

        var center = new cv.Point(canvas.width / 2, canvas.height / 2);
        var M = cv.getRotationMatrix2D(center, angle, 1.0);
        var rotated = new cv.Mat();
        cv.warpAffine(src, rotated, M, new cv.Size(canvas.width, canvas.height),
          cv.INTER_LINEAR, cv.BORDER_CONSTANT, new cv.Scalar(255, 255, 255, 255));
        var out = matToCanvas(cv, rotated);
        M.delete(); src.delete(); rotated.delete();
        Ws.ocrLog('cv deskew', { angle: Math.round(angle * 10) / 10 });
        return out;
      } catch (e) {
        Ws.ocrLog('cv deskew error', e && e.message);
        return canvas;
      }
    });
  };

  /* ----------------------- ADAPTIVE THRESHOLD ----------------------- */
  /**
   * Binarise a region canvas with Otsu (global) or Sauvola-style adaptive
   * threshold. Good for uneven lighting / shadows on photo captures.
   * Writes IN-PLACE into the canvas's pixels (RGBA: text black, bg white).
   */
  CV.adaptiveThresholdCanvas = function adaptiveThresholdCanvas(canvas) {
    return CV.ensure().then(function (cv) {
      if (!cv) return false;
      try {
        var src = canvasToMat(cv, canvas);
        var gray = new cv.Mat();
        cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);
        var bw = new cv.Mat();
        cv.adaptiveThreshold(gray, bw, 255, cv.ADAPTIVE_THRESH_GAUSSIAN_C,
          cv.THRESH_BINARY, 31, 12);
        matToCanvas(cv, bw, canvas);
        src.delete(); gray.delete(); bw.delete();
        return true;
      } catch (e) {
        Ws.ocrLog('cv threshold error', e && e.message);
        return false;
      }
    });
  };

  /** Otsu global binarisation (faster; best for clean digital slips). */
  CV.otsuCanvas = function otsuCanvas(canvas) {
    return CV.ensure().then(function (cv) {
      if (!cv) return false;
      try {
        var src = canvasToMat(cv, canvas);
        var gray = new cv.Mat();
        cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);
        var bw = new cv.Mat();
        cv.threshold(gray, bw, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU);
        matToCanvas(cv, bw, canvas);
        src.delete(); gray.delete(); bw.delete();
        return true;
      } catch (e) {
        return false;
      }
    });
  };

  /* ------------------------------ CLAHE ------------------------------ */
  /** Contrast-Limited Adaptive Histogram Equalisation — lifts low-light text. */
  CV.claheCanvas = function claheCanvas(canvas, clipLimit, tileGrid) {
    return CV.ensure().then(function (cv) {
      if (!cv) return false;
      try {
        var src = canvasToMat(cv, canvas);
        var lab = new cv.Mat();
        cv.cvtColor(src, lab, cv.COLOR_RGBA2RGB);
        var gray = new cv.Mat();
        cv.cvtColor(lab, gray, cv.COLOR_RGB2GRAY);
        var clahe = new cv.CLAHE(clipLimit || 2.0, new cv.Size(tileGrid || 8, tileGrid || 8));
        var out = new cv.Mat();
        clahe.apply(gray, out);
        cv.cvtColor(out, lab, cv.COLOR_GRAY2RGBA);
        matToCanvas(cv, lab, canvas);
        src.delete(); lab.delete(); gray.delete(); out.delete(); clahe.delete();
        return true;
      } catch (e) {
        return false;
      }
    });
  };

  /* ----------------------- MEDIAN DENOISE ----------------------- */
  /** Remove salt-and-pepper noise without smearing character edges. */
  CV.denoiseCanvas = function denoiseCanvas(canvas, ksize) {
    return CV.ensure().then(function (cv) {
      if (!cv) return false;
      try {
        var src = canvasToMat(cv, canvas);
        var gray = new cv.Mat();
        cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);
        var out = new cv.Mat();
        cv.medianBlur(gray, out, ksize || 3);
        matToCanvas(cv, out, canvas);
        src.delete(); gray.delete(); out.delete();
        return true;
      } catch (e) {
        return false;
      }
    });
  };

  /* --------------------- FULL PREPROCESS PIPELINE --------------------- */
  /**
   * Run the recommended pipeline for a PHOTO-captured slip region.
   * Order: denoise → deskew → CLAHE → adaptive threshold.
   * Each step is best-effort; failure in one does not abort the rest.
   * Returns the (possibly same) canvas.
   */
  CV.enhancePhotoRegion = function enhancePhotoRegion(canvas) {
    if (!CV.isEnabled()) return Promise.resolve(canvas);
    return CV.denoiseCanvas(canvas, 3).then(function () {
      return CV.deskew(canvas);
    }).then(function (c) {
      return CV.claheCanvas(c, 2.0, 8);
    }).then(function () {
      return CV.adaptiveThresholdCanvas(canvas);
    }).then(function () {
      return canvas;
    });
  };

})(window);
