/**
 * Workspace Slip OCR v2 — Tesseract worker pool (1 main + 3 parallel slots).
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr;
  if (!Ws) return;

  var _tesseractWarm = null;
  var _ocrWorker = null;
  var _ocrWorkerReady = null;
  var _instantWorkers = [];
  var _instantWorkerReady = null;
  var _ocrJobChain = Promise.resolve();
  var _lastOcrEngineError = null;
  var _ocrWorkersHot = false;

  function tesseractBaseUrl() {
    var cfg = global.__wsSlipTesseractConfig || {};
    var base = cfg.baseUrl || global.__wsSlipTesseractBase || '/static/vendor/tesseract/';
    if (base.slice(-1) !== '/') base += '/';
    return base;
  }

  function tesseractLangPath() {
    var cfg = global.__wsSlipTesseractConfig || {};
    var lang = cfg.langUrl || cfg.langPath || (tesseractBaseUrl() + 'tessdata/');
    if (lang.slice(-1) !== '/') lang += '/';
    return lang;
  }

  Ws.tesseractWorkerOptions = function tesseractWorkerOptions(extra) {
    var base = tesseractBaseUrl();
    var opts = {
      workerPath: base + 'worker.min.js',
      corePath: base + 'tesseract-core.wasm.js',
      langPath: tesseractLangPath(),
      gzip: true,
    };
    if (extra) Object.keys(extra).forEach(function (k) { opts[k] = extra[k]; });
    return opts;
  };

  function tesseractScriptSources() {
    var base = tesseractBaseUrl();
    return [base + 'tesseract.min.js'].concat([
      'https://cdn.jsdelivr.net/npm/tesseract.js@' + Ws.TESSERACT_VERSION + '/dist/tesseract.min.js',
      'https://unpkg.com/tesseract.js@' + Ws.TESSERACT_VERSION + '/dist/tesseract.min.js',
    ]);
  }

  function loadScriptOnce(url) {
    return new Promise(function (resolve, reject) {
      if (global.Tesseract) {
        resolve(global.Tesseract);
        return;
      }
      var s = document.createElement('script');
      s.src = url;
      s.async = true;
      s.onload = function () {
        if (global.Tesseract) resolve(global.Tesseract);
        else reject(new Error('Tesseract missing: ' + url));
      };
      s.onerror = function () { reject(new Error('Script failed: ' + url)); };
      document.head.appendChild(s);
    });
  }

  Ws.ensureTesseract = function ensureTesseract() {
    if (global.Tesseract) return Promise.resolve(global.Tesseract);
    if (global.__wsSlipTesseractLoader) return global.__wsSlipTesseractLoader;
    var chain = Promise.reject(new Error('No sources'));
    tesseractScriptSources().forEach(function (url) {
      chain = chain.catch(function () { return loadScriptOnce(url); });
    });
    global.__wsSlipTesseractLoader = chain
      .then(function (T) {
        _lastOcrEngineError = null;
        Ws.ocrLog('engine ready');
        return T;
      })
      .catch(function (err) {
        global.__wsSlipTesseractLoader = null;
        _lastOcrEngineError = err && err.message ? err.message : String(err);
        throw err;
      });
    return global.__wsSlipTesseractLoader;
  };

  Ws.buildOcrParams = function buildOcrParams(fieldKey, opts) {
    opts = opts || {};
    var params = { preserve_interword_spaces: '1' };
    params.tessedit_pageseg_mode = String(opts.psm || '7');
    if (fieldKey && !opts.noWhitelist) {
      if (fieldKey === 'amount') params.tessedit_char_whitelist = '0123456789., RSrsPKRpkr';
      else if (fieldKey === 'reference_no') params.tessedit_char_whitelist = '0123456789# ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-';
      else if (fieldKey === 'date') params.tessedit_char_whitelist = '0123456789:/-. ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
      else params.tessedit_char_whitelist = Ws.FULL_OCR_WHITELIST;
    } else {
      params.tessedit_char_whitelist = Ws.FULL_OCR_WHITELIST;
    }
    return params;
  };

  function getOcrWorker() {
    if (_ocrWorkerReady) return _ocrWorkerReady;
    _ocrWorkerReady = Ws.ensureTesseract().then(function (T) {
      return T.createWorker('eng', 1, Ws.tesseractWorkerOptions({ gzip: true }));
    }).then(function (worker) {
      _ocrWorker = worker;
      return worker;
    }).catch(function (err) {
      _ocrWorker = null;
      _ocrWorkerReady = null;
      throw err;
    });
    return _ocrWorkerReady;
  }

  Ws.prewarmWorker = function prewarmWorker() {
    if (!_tesseractWarm) {
      _tesseractWarm = getOcrWorker().then(function () { return true; }).catch(function (err) {
        _tesseractWarm = null;
        throw err;
      });
      Ws.prewarmInstantWorkers().catch(function () { /* bg */ });
    }
    return _tesseractWarm;
  };

  Ws.prewarmInstantWorkers = function prewarmInstantWorkers() {
    if (_instantWorkerReady) return _instantWorkerReady;
    _instantWorkerReady = Ws.ensureTesseract().then(function (T) {
      var jobs = [];
      for (var i = 0; i < Ws.INSTANT_WORKER_COUNT; i++) {
        jobs.push(T.createWorker('eng', 1, Ws.tesseractWorkerOptions({ gzip: true })));
      }
      return Promise.all(jobs);
    }).then(function (workers) {
      _instantWorkers = workers;
      return workers;
    }).catch(function (err) {
      _instantWorkerReady = null;
      throw err;
    });
    return _instantWorkerReady;
  };

  function warmWorkerWithTinyOcr(worker) {
    var c = document.createElement('canvas');
    c.width = 48;
    c.height = 16;
    var ctx = c.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.fillStyle = '#000';
    ctx.font = '11px sans-serif';
    ctx.fillText('PKR 1,000', 2, 12);
    return worker.setParameters(Ws.buildOcrParams('amount', { psm: '7', noWhitelist: true }))
      .then(function () { return worker.recognize(c); })
      .catch(function () { /* best effort */ });
  }

  Ws.warmOcrWorkersOnce = function warmOcrWorkersOnce() {
    if (_ocrWorkersHot) return Promise.resolve(true);
    return Promise.all([Ws.prewarmWorker(), Ws.prewarmInstantWorkers()]).then(function () {
      return getOcrWorker().then(function (main) {
        var jobs = [warmWorkerWithTinyOcr(main)];
        _instantWorkers.forEach(function (w) { jobs.push(warmWorkerWithTinyOcr(w)); });
        return Promise.all(jobs);
      });
    }).then(function () {
      _ocrWorkersHot = true;
      return true;
    }).catch(function () { return false; });
  };

  Ws.prepareOcrEngine = function prepareOcrEngine() {
    return Ws.warmOcrWorkersOnce();
  };

  Ws.getLastOcrEngineError = function getLastOcrEngineError() {
    return _lastOcrEngineError;
  };

  Ws.getWorker = function getWorker() {
    return Ws.prewarmWorker();
  };

  Ws.recognizeCanvas = function recognizeCanvas(canvas, fieldKey, opts, slot) {
    opts = opts || {};
    fieldKey = fieldKey || 'amount';
    var params = Ws.buildOcrParams(fieldKey, opts);

    function run(worker) {
      return worker.setParameters(params).then(function () {
        return worker.recognize(canvas);
      });
    }

    if (typeof slot === 'number' && _instantWorkers[slot]) {
      return run(_instantWorkers[slot]);
    }

    return getOcrWorker().then(run);
  };

  Ws.ocrUniversalScan = function ocrUniversalScan(preparedCanvas) {
    return Ws.recognizeCanvas(preparedCanvas, null, { psm: '6', noWhitelist: true }).then(function (raw) {
      return (raw && raw.data && raw.data.text) ? raw.data.text : '';
    });
  };

})(window);
