/**
 * Template-Matching Zonal OCR for Workspace Transfer slips (Tesseract.js).
 * Pipeline: preprocess → zonal multi-pass OCR → word-box parsing → anchor fallback.
 */
(function (global) {
  'use strict';

  var STOP_WORDS = {
    THE: 1, AND: 1, FOR: 1, FROM: 1, WITH: 1, YOUR: 1, THIS: 1, THAT: 1,
    HAVE: 1, WILL: 1, ARE: 1, WAS: 1, HAS: 1, NOT: 1, BUT: 1, YOU: 1, ALL: 1,
    CAN: 1, HER: 1, HIS: 1, ONE: 1, OUR: 1, OUT: 1, DAY: 1, GET: 1, MAY: 1,
    NEW: 1, NOW: 1, OLD: 1, SEE: 1, WAY: 1, WHO: 1, BOY: 1, DID: 1, ITS: 1,
    LET: 1, PUT: 1, SAY: 1, SHE: 1, TOO: 1, USE: 1, AM: 1, PM: 1, PKR: 1, RS: 1,
    PAID: 1, SEND: 1, MONEY: 1, TRANSFER: 1, SUCCESS: 1, SUCCESSFUL: 1,
  };

  var FIELD_LABELS = {
    date: 'Transfer Date',
    amount: 'Amount',
    reference_no: 'Reference No',
  };

  var FIELD_COLORS = {
    date: '#0d6efd',
    amount: '#198754',
    reference_no: '#fd7e14',
  };

  var FIELD_TINTS = {
    date: 'rgba(13,110,253,0.10)',
    amount: 'rgba(25,135,84,0.10)',
    reference_no: 'rgba(253,126,20,0.10)',
  };

  /** Built-in regex fallbacks when zonal OCR misses (matched by provider keywords). */
  var PROVIDER_TEMPLATES = [
    { id: 'jazzcash', keys: ['JAZZCASH', 'JAZZ CASH', 'JC'] },
    { id: 'easypaisa', keys: ['EASYPAISA', 'EASY PAISA', 'TELENOR'] },
    { id: 'hbl', keys: ['HBL', 'HABIB BANK', 'HABIB'] },
    { id: 'meezan', keys: ['MEEZAN', 'MEEZAN BANK'] },
    { id: 'ubl', keys: ['UBL', 'UNITED BANK'] },
    { id: 'mcb', keys: ['MCB', 'MCB BANK'] },
    { id: 'raast', keys: ['RAAST', 'RAAST ID', 'RAAST PAYMENT'] },
    { id: 'sadapay', keys: ['SADAPAY', 'SADA PAY'] },
    { id: 'nayapay', keys: ['NAYAPAY', 'NAYA PAY'] },
  ];

  /** Typical amount box placement (% of image) when saved design zones drift. */
  var PROVIDER_AMOUNT_REGIONS = {
    hbl: { region_x: 6, region_y: 16, region_w: 88, region_h: 20 },
    jazzcash: { region_x: 5, region_y: 22, region_w: 90, region_h: 18 },
    easypaisa: { region_x: 5, region_y: 22, region_w: 90, region_h: 18 },
    meezan: { region_x: 6, region_y: 18, region_w: 88, region_h: 20 },
    ubl: { region_x: 6, region_y: 18, region_w: 88, region_h: 20 },
    mcb: { region_x: 6, region_y: 18, region_w: 88, region_h: 20 },
    raast: { region_x: 6, region_y: 18, region_w: 88, region_h: 20 },
    sadapay: { region_x: 5, region_y: 20, region_w: 90, region_h: 18 },
    nayapay: { region_x: 5, region_y: 20, region_w: 90, region_h: 18 },
  };

  var AMOUNT_MIN = 10;
  var AMOUNT_MAX = 10000000000;

  var _tesseractWarm = null;
  var _ocrWorker = null;
  var _ocrWorkerReady = null;
  var _ocrJobChain = Promise.resolve();
  var _lastOcrEngineError = null;
  var _slipPrepCache = new WeakMap();
  var _fullTextCache = new WeakMap();
  var TESSERACT_VERSION = '5.1.1';
  var FULL_OCR_WHITELIST = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .:/-#@$%&*()+_ RSrsPKRpkr,';

  function ocrConfig() {
    var cfg = global.__wsSlipOcrConfig || {};
    return {
      mode: cfg.mode || 'balanced',
      preprocess: cfg.preprocess !== false,
      debug: cfg.debug === true,
      minImageWidth: cfg.minImageWidth || 1280,
    };
  }

  function ocrModeIsFast() {
    return ocrConfig().mode === 'fast';
  }

  function ocrModeIsAccurate() {
    return ocrConfig().mode === 'accurate';
  }

  function slipDrawTarget(img) {
    return img && img._slipCanvas ? img._slipCanvas : img;
  }

  function normalizeSlipImage(img) {
    if (!img) return img;
    if (img._slipReady) return img;
    var cfg = ocrConfig();
    if (!cfg.preprocess) {
      img._slipReady = true;
      _slipPrepCache.set(img, img);
      return img;
    }
    if (_slipPrepCache.has(img)) return _slipPrepCache.get(img);

    var size = {
      w: img.naturalWidth || img.width || 0,
      h: img.naturalHeight || img.height || 0,
    };
    var minW = cfg.minImageWidth || 1280;
    var scale = size.w && size.w < minW ? (minW / size.w) : 1;
    var needsEnhance = scale > 1.03 || (size.w && size.w < 1000);

    if (!needsEnhance) {
      img._slipReady = true;
      _slipPrepCache.set(img, img);
      return img;
    }

    var c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(size.w * scale));
    c.height = Math.max(1, Math.round(size.h * scale));
    var ctx = c.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, 0, 0, c.width, c.height);
    enhanceCanvas(ctx, c, 'photo-fix');

    var wrapped = {
      naturalWidth: c.width,
      naturalHeight: c.height,
      width: c.width,
      height: c.height,
      complete: true,
      _slipCanvas: c,
      _slipReady: true,
      _raw: img,
      src: img.src || '',
    };
    _slipPrepCache.set(img, wrapped);
    ocrLog('normalizeSlipImage', { from: size, to: { w: c.width, h: c.height }, scale: scale });
    return wrapped;
  }

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

  function tesseractWorkerOptions(extra) {
    var base = tesseractBaseUrl();
    var opts = {
      workerPath: base + 'worker.min.js',
      corePath: base + 'tesseract-core.wasm.js',
      langPath: tesseractLangPath(),
      gzip: true,
    };
    if (extra) {
      Object.keys(extra).forEach(function (k) { opts[k] = extra[k]; });
    }
    return opts;
  }

  function tesseractScriptSources() {
    var base = tesseractBaseUrl();
    return [
      base + 'tesseract.min.js',
      'https://cdn.jsdelivr.net/npm/tesseract.js@' + TESSERACT_VERSION + '/dist/tesseract.min.js',
      'https://unpkg.com/tesseract.js@' + TESSERACT_VERSION + '/dist/tesseract.min.js',
    ];
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
        else reject(new Error('Tesseract global missing after load: ' + url));
      };
      s.onerror = function () { reject(new Error('Script load failed: ' + url)); };
      document.head.appendChild(s);
    });
  }

  function loadScriptWithFallback(urls) {
    var chain = Promise.reject(new Error('No Tesseract sources'));
    urls.forEach(function (url) {
      chain = chain.catch(function () { return loadScriptOnce(url); });
    });
    return chain;
  }

  function ensureTesseract() {
    if (global.Tesseract) return Promise.resolve(global.Tesseract);
    if (global.__wsSlipTesseractLoader) return global.__wsSlipTesseractLoader;
    global.__wsSlipTesseractLoader = loadScriptWithFallback(tesseractScriptSources())
      .then(function (Tesseract) {
        _lastOcrEngineError = null;
        ocrLog('ensureTesseract ok', { baseUrl: tesseractBaseUrl(), langPath: tesseractLangPath() });
        return Tesseract;
      })
      .catch(function (err) {
        global.__wsSlipTesseractLoader = null;
        _lastOcrEngineError = err && err.message ? err.message : String(err);
        ocrLog('ensureTesseract failed', _lastOcrEngineError);
        throw new Error(_lastOcrEngineError || 'Tesseract load failed (offline?)');
      });
    return global.__wsSlipTesseractLoader;
  }

  function prewarmWorker() {
    if (!_tesseractWarm) {
      _tesseractWarm = getOcrWorker().then(function () {
        return global.Tesseract || true;
      }).catch(function (err) {
        _tesseractWarm = null;
        throw err;
      });
    }
    return _tesseractWarm;
  }

  function getOcrWorker() {
    if (_ocrWorkerReady) return _ocrWorkerReady;
    _ocrWorkerReady = ensureTesseract().then(function (Tesseract) {
      return Tesseract.createWorker('eng', 1, tesseractWorkerOptions({ gzip: true }));
    }).then(function (worker) {
      _ocrWorker = worker;
      ocrLog('getOcrWorker ready');
      return worker;
    }).catch(function (err) {
      _ocrWorker = null;
      _ocrWorkerReady = null;
      throw err;
    });
    return _ocrWorkerReady;
  }

  function runOcrJob(jobFn) {
    var job = _ocrJobChain.then(jobFn);
    _ocrJobChain = job.catch(function () { /* keep queue alive */ });
    return job;
  }

  function buildOcrParams(fieldKey, opts) {
    opts = opts || {};
    var params = { preserve_interword_spaces: '1' };
    if (opts.psm) params.tessedit_pageseg_mode = String(opts.psm);
    if (fieldKey && !opts.noWhitelist) {
      params.tessedit_char_whitelist = whitelistForField(fieldKey, { digitsOnly: !!opts.digitsOnly });
    } else {
      params.tessedit_char_whitelist = FULL_OCR_WHITELIST;
    }
    return params;
  }

  function recognizeCanvasOnce(canvas, fieldKey, opts) {
    opts = opts || {};
    return ensureTesseract().then(function (Tesseract) {
      var recognizeOpts = tesseractWorkerOptions(buildOcrParams(fieldKey, opts));
      return Tesseract.recognize(canvas, 'eng', recognizeOpts);
    });
  }

  function prepareOcrEngine() {
    return prewarmWorker();
  }

  function getLastOcrEngineError() {
    return _lastOcrEngineError;
  }

  function getWorker() {
    return prewarmWorker();
  }

  function whitelistForField(fieldKey, opts) {
    opts = opts || {};
    if (fieldKey === 'amount') return '0123456789., RSrsPKRpkr';
    if (fieldKey === 'reference_no') {
      if (opts.digitsOnly) return '0123456789#';
      return '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#-';
    }
    if (fieldKey === 'date') return '0123456789:/-.|& ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
    return '0123456789:/-. ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz# RSrsPKRpkr,';
  }

  function levenshtein(a, b) {
    var m = a.length;
    var n = b.length;
    if (!m) return n;
    if (!n) return m;
    var row = [];
    var i;
    for (i = 0; i <= n; i++) row[i] = i;
    for (i = 1; i <= m; i++) {
      var prev = i;
      for (var j = 1; j <= n; j++) {
        var val = a[i - 1] === b[j - 1] ? row[j - 1] : Math.min(row[j - 1], prev, row[j]) + 1;
        row[j - 1] = prev;
        prev = val;
      }
      row[n] = prev;
    }
    return row[n];
  }

  function stringSimilarity(a, b) {
    a = String(a || '').toUpperCase().replace(/\s+/g, '');
    b = String(b || '').toUpperCase().replace(/\s+/g, '');
    if (!a || !b) return 0;
    if (a === b) return 1;
    if (a.indexOf(b) !== -1 || b.indexOf(a) !== -1) return 0.93;
    var longer = a.length >= b.length ? a : b;
    var shorter = a.length >= b.length ? b : a;
    var dist = levenshtein(longer, shorter);
    return Math.max(0, (longer.length - dist) / longer.length);
  }

  function fuzzyKeywordInText(upperText, keyword) {
    var k = String(keyword || '').toUpperCase().trim();
    if (!k) return false;
    if (upperText.indexOf(k) !== -1) return true;
    if (k.length >= 4) {
      var parts = upperText.split(/\s+/);
      for (var i = 0; i < parts.length; i++) {
        if (stringSimilarity(parts[i], k) >= 0.84) return true;
      }
    }
    return false;
  }

  var MONTH_TOKENS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  var MONTH_OCR_FIXES = {
    '1UN': 'JUN', 'IUN': 'JUN', 'JUN': 'JUN', 'JUH': 'JUN', 'JUI': 'JUL', 'JUL': 'JUL',
    'IAN': 'JAN', 'JAN': 'JAN', 'FEB': 'FEB', 'MAR': 'MAR', 'APR': 'APR', 'MAY': 'MAY',
    'AUG': 'AUG', '5EP': 'SEP', 'SEP': 'SEP', 'OCT': 'OCT', 'NOV': 'NOV', 'DEC': 'DEC',
    '18AN': 'JUN', '8AN': 'JUN', '0CT': 'OCT', '5UN': 'JUN', 'JUM': 'JUN',
  };

  function fuzzyFixMonthToken(token) {
    var raw = String(token || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (!raw) return token;
    if (MONTH_OCR_FIXES[raw]) return MONTH_OCR_FIXES[raw];
    if (raw.length >= 3 && MONTH_OCR_FIXES[raw.slice(0, 3)]) return MONTH_OCR_FIXES[raw.slice(0, 3)];
    if (raw.length >= 4 && MONTH_OCR_FIXES[raw.slice(0, 4)]) return MONTH_OCR_FIXES[raw.slice(0, 4)];
    var best = 'JAN';
    var bestScore = 0;
    MONTH_TOKENS.forEach(function (m) {
      var s = stringSimilarity(raw.slice(0, 3), m);
      if (s > bestScore) {
        bestScore = s;
        best = m;
      }
    });
    return bestScore >= 0.55 ? best : raw.slice(0, 3);
  }

  function isMonthDayYearLead(text) {
    return /^(?:on\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}\b/i.test(
      String(text || '').trim()
    );
  }

  function fixOcrTextForDate(text) {
    var t = String(text || '').replace(/\s+/g, ' ').replace(/—/g, '-').trim();
    t = t.replace(/^0n\b/i, 'On');
    t = t.replace(/\b(?:transaction|posting)\s*date\s*[:\-]?\s*/gi, ' ').trim();
    var monthDayLead = isMonthDayYearLead(t);
    t = t.split('|')[0].split(/\s+at\s+/i)[0].trim();
    // Drop clock time — "27-Mar-2023 5:29 PM" / "23/12/2025 15:25:52"
    t = t.replace(/\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\b/gi, '').trim();
    monthDayLead = monthDayLead || isMonthDayYearLead(t);
    t = t.replace(/^(?:transaction\s*)?date\s*(?:&\s*time)?\s*[:\-]?\s*/i, '');
    t = t.replace(/^(?:on|time)\s*[:\-]?\s*/i, '');
    t = t.replace(/\b([OolI|])(?=\d)/g, '0');
    t = t.replace(/(\d)[Oo](\d)/g, '$10$2');
    // DD-Mon-YYYY — "27-Mar-2023"
    t = t.replace(
      /\b(\d{1,2})[\/\-.]([A-Za-z]{3,9})[\/\-.](\d{2,4})\b/g,
      function (_, d, mon, y) {
        return d + ' ' + fuzzyFixMonthToken(mon) + ' ' + y;
      }
    );
    if (monthDayLead) {
      // Month Day, Year — "June 11, 2026" / "Jun 11 2026"
      t = t.replace(
        /\b([A-Za-z]{3,9})\s+(\d{1,2})\s*,\s*(\d{2,4})\b/g,
        function (_, mon, d, y) {
          return fuzzyFixMonthToken(mon) + ' ' + d + ' ' + y;
        }
      );
      t = t.replace(
        /\b([A-Za-z]{3,9})\s+(\d{1,2})\s+((?:19|20)\d{2})\b/g,
        function (_, mon, d, y) {
          return fuzzyFixMonthToken(mon) + ' ' + d + ' ' + y;
        }
      );
    } else {
      // Day Month Year — "11 June 2026"
      t = t.replace(/\b(\d{1,2})\s+([A-Za-z0-9]{2,9})\s+(\d{2,4})\b/g, function (_, d, mon, y) {
        return d + ' ' + fuzzyFixMonthToken(mon) + ' ' + y;
      });
    }
    return t.trim();
  }

  function fixOcrAmountText(text) {
    var t = String(text || '').replace(/\s+/g, ' ').replace(/—/g, '-').trim();
    t = t.replace(/\b(?:transferred\s*)?amount\s*[:\-]?\s*/gi, '');
    t = t.replace(/(^|\s)-\s*(?=(?:RS\.?|PKR\.?|R\s*5))/gi, '$1');
    t = t.replace(/\bP\s*K\s*R\.?\s*/gi, 'PKR ');
    t = t.replace(/\bR\s*[5S]\s*\.?\s*/gi, 'Rs. ');
    // Merge split decimals before digit cleanup (Rs. 2000 00 / small superscript .00)
    t = t.replace(
      /(?:RS\.?|PKR\.?)\s*(\d{1,3}(?:,\d{3})+|\d{3,7})\s*(?:\.\s*)?(\d{2})\b/gi,
      '$1.$2'
    );
    t = t.replace(/\b(\d{3,7})\s*(?:\.\s*)?(\d{2})\b/g, '$1.$2');
    t = t.replace(/\b(\d{1,3}(?:,\d{3})+)\s*(?:\.\s*)?(\d{2})\b/g, '$1.$2');
    t = t.replace(/(\d)\s+(\d{3})(?:\s*\.\s*|\s+)(\d{2})\b/g, '$1,$2.$3');
    t = t.replace(/(\d{1,3})\s+(\d{3})(?:\s*\.\s*(\d{1,2}))?\b/g, function (_, a, b, dec) {
      return dec ? (a + ',' + b + '.' + dec) : (a + ',' + b);
    });
    t = t.replace(/(?:RS\.?|PKR\.?)\s*/gi, '');
    return fixOcrText(t, 'amount');
  }

  function expandAmountRegion(region) {
    if (!region) return region;
    var x = region.region_x || 0;
    var w = region.region_w || 10;
    var h = region.region_h || 8;
    var extraRight = Math.max(4.5, w * 0.24);
    return {
      region_x: Math.max(0, x - 0.4),
      region_y: Math.max(0, (region.region_y || 0) - 0.3),
      region_w: Math.min(100 - Math.max(0, x - 0.4), w + extraRight),
      region_h: Math.min(100 - Math.max(0, (region.region_y || 0) - 0.3), h + 1.2),
    };
  }

  function normalizeAmountWordDigits(text) {
    return fixOcrText(String(text || ''), 'amount').replace(/\s+/g, '');
  }

  function extractAmountFromWords(words, canvasWidth) {
    var sorted = (words || []).filter(function (w) {
      return w && w.bbox && String(w.text || '').trim();
    }).sort(function (a, b) {
      return a.bbox.x0 - b.bbox.x0;
    });
    if (!sorted.length) return null;

    var tokens = sorted.map(function (w) {
      return {
        raw: String(w.text || '').trim(),
        norm: normalizeAmountWordDigits(w.text),
        bbox: w.bbox,
        h: Math.max(1, w.bbox.y1 - w.bbox.y0),
      };
    });

    var candidates = [];
    function pushAmount(raw, score, conf, source) {
      var scored = scoreAmountCandidate(raw, score, '', { afterCurrency: true });
      if (!scored) scored = scoreAmountCandidate(raw, score - 8, '', {});
      if (!scored) return;
      candidates.push({
        val: scored.val,
        score: scored.score,
        conf: conf || 0.8,
        source: source || 'amount-words',
      });
    }

    tokens.forEach(function (tok, i) {
      var main = tok.norm.replace(/[^\d.,]/g, '');
      if (!/^\d{1,12}(?:\.\d{1,2})?$/.test(main) && !/^\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?$/.test(main)) return;
      var merged = main;
      var bonus = 0;

      for (var j = i + 1; j < tokens.length && j <= i + 2; j++) {
        var next = tokens[j];
        var gap = next.bbox.x0 - tok.bbox.x1;
        if (gap > 64) break;
        var nextNorm = next.norm.replace(/[^\d.]/g, '');
        var isSmall = next.h > 0 && tok.h > 0 && next.h < tok.h * 0.78;
        if (/^\.?\d{2}$/.test(nextNorm)) {
          var dec = nextNorm.replace(/^\./, '');
          if (dec.length === 2 && !/\.\d{2}$/.test(merged)) {
            merged = merged.replace(/,/g, '') + '.' + dec;
            bonus += isSmall ? 42 : 24;
            break;
          }
        }
        if (nextNorm === '.' && j + 1 < tokens.length) {
          var decTok = tokens[j + 1].norm.replace(/[^\d]/g, '');
          if (/^\d{2}$/.test(decTok) && !/\.\d{2}$/.test(merged)) {
            merged = merged.replace(/,/g, '') + '.' + decTok;
            bonus += 36;
            break;
          }
        }
      }

      var hasCurrencyBefore = tokens.slice(0, i).some(function (t) {
        return /^(?:RS|RS\.|PKR|PKR\.)$/i.test(t.raw.replace(/\s/g, ''));
      });
      pushAmount(
        merged,
        108 + bonus + (hasCurrencyBefore ? 18 : 0),
        0.84,
        'amount-words-merged'
      );
    });

    var lineText = tokens.map(function (t) { return t.raw; }).join(' ');
    var parsed = parseAmountFromText(lineText);
    if (parsed) {
      pushAmount(parsed, 96, 0.78, 'amount-words-line');
    }

    if (!candidates.length) return null;
    candidates.sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return (b.conf || 0) - (a.conf || 0);
    });
    return candidates[0];
  }

  function fixOcrText(text, mode) {
    var t = String(text || '').replace(/\s+/g, ' ').replace(/—/g, '-').trim();
    if (mode === 'amount') {
      return t
        .replace(/[OoQqD]/g, '0')
        .replace(/[lI|]/g, '1')
        .replace(/[Ss$]/g, '5')
        .replace(/[Bb]/g, '8')
        .replace(/[Zz]/g, '2')
        .replace(/[Gg]/g, '6')
        .replace(/[^\d.,]/g, ' ');
    }
    if (mode === 'reference_no') {
      return t
        .replace(/[OoQD]/g, '0')
        .replace(/[lI|!]/g, '1')
        .replace(/[Ss$]/g, '5')
        .replace(/[Bb]/g, '8')
        .replace(/[Zz]/g, '2')
        .replace(/[Gg]/g, '6')
        .replace(/[^\w#\- ]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .toUpperCase();
    }
    return t
      .replace(/[Oo]/g, '0')
      .replace(/[lI|]/g, '1')
      .replace(/[Ss]/g, '5')
      .replace(/[Bb]/g, '8')
      .replace(/[Zz]/g, '2');
  }

  function pad2(n) {
    return ('0' + n).slice(-2);
  }

  function parseDateFromText(text) {
    var raw = String(text || '');
    var t = fixOcrTextForDate(raw);
    var patterns = [
      {
        re: /\b(\d{1,2})[\/\-.](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\/\-.](\d{4})\b/gi,
        kind: 'dmy4',
        bonus: 14,
      },
      {
        re: /\b(\d{1,2})[\/\-.](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\/\-.](\d{2})\b/gi,
        kind: 'dmy2',
        bonus: 12,
      },
      { re: /\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})\b/g, kind: 'dmy', bonus: 8 },
      { re: /\b(\d{4})[\/\-.](\d{1,2})[\/\-.](\d{1,2})\b/g, kind: 'ymd' },
      {
        re: /\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})\b/gi,
        kind: 'mdy4',
        bonus: 10,
      },
      {
        re: /\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{2})\b/gi,
        kind: 'mdy2',
        bonus: 8,
      },
      { re: /\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b/gi, kind: 'dmy4', bonus: 10 },
      { re: /\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{2})\b/gi, kind: 'dmy2', bonus: 4 },
    ];
    var months = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
    var best = null;
    var bestScore = -1;
    var m;
    patterns.forEach(function (pat) {
      pat.re.lastIndex = 0;
      while ((m = pat.re.exec(t)) !== null) {
        var d, mo, y, score = 80 + (pat.bonus || 0);
        if (pat.kind === 'mdy4' || pat.kind === 'mdy2') {
          mo = months[String(m[1]).slice(0, 3).toLowerCase()] || 0;
          d = parseInt(m[2], 10);
          y = parseInt(m[3], 10);
          if (/\bon\b/i.test(raw)) score += 6;
          if (/\bat\b/i.test(raw)) score += 6;
          if (pat.kind === 'mdy2' && y < 100) y += 2000;
        } else if (pat.kind === 'dmy4' || pat.kind === 'dmy2') {
          d = parseInt(m[1], 10);
          mo = months[String(m[2]).slice(0, 3).toLowerCase()] || 0;
          y = parseInt(m[3], 10);
          if (pat.kind === 'dmy2' && y < 100) y += 2000;
        } else if (pat.kind === 'dmy') {
          d = parseInt(m[1], 10);
          mo = parseInt(m[2], 10);
          y = parseInt(m[3], 10);
          if (/\d{1,2}:\d{2}/.test(raw)) score += 6;
        } else {
          y = parseInt(m[1], 10);
          mo = parseInt(m[2], 10);
          d = parseInt(m[3], 10);
        }
        if (y < 100) y += 2000;
        if (d < 1 || d > 31 || mo < 1 || mo > 12 || y < 2000 || y > 2100) continue;
        if (score > bestScore) {
          bestScore = score;
          best = pad2(d) + '-' + pad2(mo) + '-' + y;
        }
      }
    });
    return best;
  }

  function normalizeAmountRaw(raw) {
    if (!raw) return null;
    var cleaned = String(raw).replace(/,/g, '').replace(/\.(?=.*\.)/g, '');
    var num = parseFloat(cleaned);
    if (!isFinite(num) || num <= 0) return null;
    return num % 1 === 0 ? String(Math.round(num)) : num.toFixed(2);
  }

  function amountValuesClose(a, b) {
    var na = parseFloat(String(a || '').replace(/,/g, ''));
    var nb = parseFloat(String(b || '').replace(/,/g, ''));
    if (!isFinite(na) || !isFinite(nb)) return false;
    if (na === nb) return true;
    return Math.abs(na - nb) <= Math.max(1, na * 0.02);
  }

  function isLikelyTransactionIdDigits(digits, fullText) {
    if (!digits || digits.length < 8) return false;
    var upper = String(fullText || '').toUpperCase();
    if (/(?:RS\.?|PKR\.?|AMOUNT|TRANSFERRED|PAID|SENT|TOTAL)/i.test(upper)) return false;
    if (/(?:TID|TXN|REFERENCE|REF)\s*(?:ID|NO)?\s*#?\s*\d*/i.test(upper) && upper.indexOf(digits) !== -1) {
      return true;
    }
    if (/\bID\s*#\s*\d*/i.test(upper) && upper.replace(/\D/g, '').indexOf(digits) !== -1) return true;
    return digits.length >= 9 && digits.length <= 16 && !/\d{1,3}(?:,\d{3})+/.test(upper);
  }

  function isLikelyTimeFragment(digits, fullText) {
    if (!digits || digits.length < 4) return false;
    var timeRe = /\b(\d{1,2})\s*:\s*(\d{2})\s*:\s*(\d{2})\b/g;
    var m;
    while ((m = timeRe.exec(String(fullText || ''))) !== null) {
      var compact = pad2(parseInt(m[1], 10)) + m[2] + m[3];
      if (digits === compact || compact.indexOf(digits) !== -1 || digits.indexOf(compact) !== -1) {
        return true;
      }
    }
    return false;
  }

  function isLikelyMaskedAccountSuffix(digits, fullText) {
    if (!digits || digits.length !== 4) return false;
    return new RegExp('\\*\\s*' + digits + '\\b').test(String(fullText || ''));
  }

  function isLikelyYearFragment(digits, fullText) {
    var y = parseInt(digits, 10);
    if (!isFinite(y) || y < 2000 || y > 2100) return false;
    var ctx = String(fullText || '');
    if (/(?:RS\.?|PKR\.?|AMOUNT|PAID|SENT|TRANSFERRED|TOTAL)/i.test(ctx)) return false;
    if (/\d{1,3}(?:,\d{3})*\.\d{1,2}|\d{3,7}\.\d{1,2}/.test(ctx)) return false;
    if (/\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b/i.test(ctx)) return true;
    return false;
  }

  function validateAmountCandidate(val, fullText, options) {
    options = options || {};
    var num = parseFloat(String(val || '').replace(/,/g, ''));
    if (!isFinite(num) || num <= 0) return false;
    if (!options.allowSmall && num < AMOUNT_MIN) return false;
    if (num > AMOUNT_MAX) return false;
    var digits = String(Math.round(num));
    if (isLikelyTransactionIdDigits(digits, fullText)) return false;
    if (isLikelyTimeFragment(digits, fullText)) return false;
    if (isLikelyMaskedAccountSuffix(digits, fullText)) return false;
    if (isLikelyYearFragment(digits, fullText)) return false;
    return true;
  }

  function scoreAmountCandidate(raw, score, fullText, context) {
    context = context || {};
    var val = normalizeAmountRaw(raw);
    if (!val || !validateAmountCandidate(val, fullText, context)) return null;
    var total = score;
    if (/,\d{3}/.test(String(raw))) total += 18;
    if (context.afterAmountLabel) total += 22;
    if (context.afterCurrency) total += 28;
    if (context.beforeDetails) total += 12;
    if (/^\d{1,3}(?:,\d{3})+$/.test(String(raw))) total += 10;
    if (/^\d{1,3}(?:,\d{3}){2,}$/.test(String(raw))) total += 14;
    var num = parseFloat(val);
    if (num >= 100 && num <= 500000) total += 8;
    if (num > 500000 && /(?:RS\.?|PKR\.?|TRANSFERRED\s*AMOUNT)/i.test(String(fullText || ''))) total += 12;
    return { val: val, score: total };
  }

  function parseProviderAmount(text, providerId) {
    if (!text || !providerId) return null;
    var upper = String(text).toUpperCase();
    var detailIdx = upper.search(/TRANSACTION\s*TYPE|FUND\s*TRANSFER|FROM\s*ACCOUNT|RECEIVER\s*NAME|DATE\s*&\s*TIME/);
    var head = detailIdx > 40 ? text.slice(0, detailIdx) : text;

    if (providerId === 'hbl') {
      var blockRe = /AMOUNT\b[\s\S]{0,72}?(?:PKR|RS\.?)\s*([\d,]+(?:\.\d{1,2})?)/i;
      var blockMatch = blockRe.exec(head);
      if (blockMatch) {
        var blockVal = scoreAmountCandidate(blockMatch[1], 118, text, {
          afterAmountLabel: true,
          afterCurrency: true,
          beforeDetails: true,
        });
        if (blockVal) return fieldResult(blockVal.val, 0.93, 'hbl-amount-block');
      }
      var pkrRe = /(?:PKR|RS\.?)\s*([\d]{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{3,7}(?:\.\d{1,2})?)/gi;
      var best = null;
      var bestScore = 0;
      var pm;
      while ((pm = pkrRe.exec(head)) !== null) {
        var scored = scoreAmountCandidate(pm[1], 102, text, {
          afterCurrency: true,
          beforeDetails: true,
        });
        if (scored && scored.score > bestScore) {
          bestScore = scored.score;
          best = scored.val;
        }
      }
      if (best) return fieldResult(best, 0.9, 'hbl-pkr-head');
    }

    if (providerId === 'jazzcash' || providerId === 'easypaisa') {
      var walletRe = /(?:AMOUNT\s*PAID|AMOUNT|SENT|TRANSFERRED|TOTAL)\s*[:\-]?\s*(?:RS\.?|PKR\.?)?\s*([\d,]+(?:\.\d{1,2})?)/gi;
      var wm;
      var walletBest = null;
      var walletScore = 0;
      while ((wm = walletRe.exec(text)) !== null) {
        var walletCand = scoreAmountCandidate(wm[1], 108, text, { afterAmountLabel: true });
        if (walletCand && walletCand.score > walletScore) {
          walletScore = walletCand.score;
          walletBest = walletCand.val;
        }
      }
      if (walletBest) return fieldResult(walletBest, 0.9, providerId + '-wallet');
    }

    return null;
  }

  function parseAmountFromText(text, options) {
    options = options || {};
    var rawText = String(text || '');
    var t = fixOcrAmountText(rawText);
    var candidates = [];
    var m;

    var reNegPkr = /-\s*(?:RS\.?|PKR\.?|R\s*5\.?)\s*([\d]{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{3,12}(?:\.\d{1,2})?)/gi;
    while ((m = reNegPkr.exec(rawText)) !== null) {
      var negCand = scoreAmountCandidate(m[1], 118, rawText, { afterCurrency: true, afterAmountLabel: true });
      if (negCand) candidates.push(negCand);
    }

    var reRsRaw = /(?:RS\.?|PKR\.?|R\s*5\.?)\s*([\d]{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{3,12}(?:\.\d{1,2})?)/gi;
    while ((m = reRsRaw.exec(rawText)) !== null) {
      var rsRawCand = scoreAmountCandidate(m[1], 114, rawText, { afterCurrency: true });
      if (!rsRawCand) {
        rsRawCand = scoreAmountCandidate(m[1], 108, rawText, { afterCurrency: true, allowSmall: true });
      }
      if (rsRawCand) candidates.push(rsRawCand);
    }

    var reRsSmall = /(?:RS\.?|PKR\.?)\s*(\d{1,2})(?!\d|[,.])/gi;
    while ((m = reRsSmall.exec(rawText)) !== null) {
      var smallCand = scoreAmountCandidate(m[1], 102, rawText, { afterCurrency: true, allowSmall: true });
      if (smallCand) candidates.push(smallCand);
    }

    var reRs = /(?:RS\.?|PKR\.?)\s*([\d]{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{3,12}(?:\.\d{1,2})?)/gi;
    while ((m = reRs.exec(t)) !== null) {
      var rsCand = scoreAmountCandidate(m[1], 112, rawText, { afterCurrency: true });
      if (!rsCand) {
        rsCand = scoreAmountCandidate(m[1], 106, rawText, { afterCurrency: true, allowSmall: true });
      }
      if (rsCand) candidates.push(rsCand);
    }

    var reTransferred = /TRANSFERRED\s*AMOUNT\s*(?:RS\.?|PKR\.?)?\s*([\d]{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{3,12}(?:\.\d{1,2})?)/gi;
    while ((m = reTransferred.exec(rawText)) !== null) {
      var xferCand = scoreAmountCandidate(m[1], 120, rawText, { afterAmountLabel: true, afterCurrency: true });
      if (xferCand) candidates.push(xferCand);
    }

    var rePkrStacked = /(?:RS\.?|PKR\.?)\s*([\d]{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{3,12}(?:\.\d{1,2})?)\s*TRANSFERRED/gi;
    while ((m = rePkrStacked.exec(rawText)) !== null) {
      var stackedCand = scoreAmountCandidate(m[1], 122, rawText, { afterCurrency: true, afterAmountLabel: true });
      if (stackedCand) candidates.push(stackedCand);
    }

    var reAmtBeforePkr = /([\d]{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{3,12}(?:\.\d{1,2})?)\s*(?:RS\.?|PKR\.?)/gi;
    while ((m = reAmtBeforePkr.exec(rawText)) !== null) {
      var suffixCand = scoreAmountCandidate(m[1], 104, rawText, { afterCurrency: true });
      if (suffixCand) candidates.push(suffixCand);
    }

    var reLabel = /(?:TRANSFERRED\s*AMOUNT|AMOUNT\s*PAID|AMOUNT|TOTAL|SENT|TRANSFERRED)\s*[:\-]?\s*(?:RS\.?|PKR\.?)?\s*([\d]{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{3,12}(?:\.\d{1,2})?)/gi;
    while ((m = reLabel.exec(t)) !== null) {
      var labelCand = scoreAmountCandidate(m[1], 96, rawText, { afterAmountLabel: true });
      if (labelCand) candidates.push(labelCand);
    }

    var reNum = /\b([\d]{1,3}(?:,\d{3})+(?:\.\d{1,2})?)\b/g;
    while ((m = reNum.exec(t)) !== null) {
      var commaCand = scoreAmountCandidate(m[1], 78, rawText);
      if (commaCand) candidates.push(commaCand);
    }

    if (!options.strict) {
      var rePlain = /\b(\d{3,7}(?:\.\d{1,2})?)\b/g;
      while ((m = rePlain.exec(t)) !== null) {
        var plainCand = scoreAmountCandidate(m[1], 48, rawText);
        if (plainCand) candidates.push(plainCand);
      }
    }

    if (!candidates.length) {
      var digits = t.replace(/[^\d.]/g, '');
      if (digits.length >= 3 && digits.length <= 8) {
        var looseCand = scoreAmountCandidate(digits, 34, rawText, { allowSmall: true });
        if (looseCand) candidates.push(looseCand);
      }
    }
    if (!candidates.length) return null;
    candidates.sort(function (a, b) { return b.score - a.score; });
    return candidates[0].val;
  }

  var REF_LABEL_RE = /(?:TID|TXN|TRANSACTION\s*REFERENCE\s*NO?\.?|TRANSACTION\s*ID|REFERENCE\s*NUMBER|REFERENCE\s*NO?\.?|REF\s*NO?|TRX\s*ID|RAAST\s*ID|TRANSACTION|REFERENCE|SUCCESSFUL|TRANSFER|VIA\s*IBT|NUMBER)\s*/gi;
  var REF_STOPWORDS = {
    TRANSACTION: 1, REFERENCE: 1, SUCCESSFUL: 1, TRANSFER: 1, SUCCESS: 1, PAYMENT: 1, AMOUNT: 1,
  };

  function mergeReferenceDigitTokens(text) {
    var tokens = String(text || '').split(/\s+/).filter(function (tok) {
      return /^\d{1,9}$/.test(tok);
    });
    if (!tokens.length) return null;
    var longTokens = tokens.filter(function (tok) { return tok.length >= 6; });
    if (longTokens.length === 1) return longTokens[0];
    if (longTokens.length > 1) return null;
    if (tokens.length < 2) return null;
    var joined = tokens.join('');
    if (joined.length >= 6 && joined.length <= 16) {
      return joined;
    }
    return null;
  }

  function scoreReferenceDigits(val, baseScore) {
    var score = baseScore + val.length * 6;
    if (/^\d+$/.test(val)) {
      score += 30;
      if (val.length >= 8 && val.length <= 24) score += 28;
      if (val.length >= 14 && val.length <= 20) score += 16;
      if (val.length === 7) score -= 18;
      if (val.length === 6) score -= 8;
    }
    return score;
  }

  function expandReferenceRegion(region) {
    var x = region.region_x || 0;
    var w = region.region_w || 10;
    var extraRight = Math.max(3.5, w * 0.18);
    return {
      region_x: Math.max(0, x - 0.6),
      region_y: region.region_y || 0,
      region_w: Math.min(100 - Math.max(0, x - 0.6), w + extraRight),
      region_h: region.region_h || 10,
    };
  }

  function mergeAdjacentDigitWords(words) {
    var sorted = (words || []).filter(function (w) {
      return w && w.bbox && /\d/.test(String(w.text || ''));
    }).sort(function (a, b) {
      return a.bbox.x0 - b.bbox.x0;
    });
    var groups = [];
    var current = null;
    sorted.forEach(function (w) {
      var digits = normalizeReferenceDigitRun(w.text);
      if (!digits) return;
      if (!current) {
        current = { digits: digits, bbox: { x0: w.bbox.x0, y0: w.bbox.y0, x1: w.bbox.x1, y1: w.bbox.y1 } };
        return;
      }
      var gap = w.bbox.x0 - current.bbox.x1;
      var lineOverlap = Math.min(current.bbox.y1, w.bbox.y1) - Math.max(current.bbox.y0, w.bbox.y0);
      var sameLine = lineOverlap > 0 || Math.abs((w.bbox.y0 + w.bbox.y1) - (current.bbox.y0 + current.bbox.y1)) < 18;
      if (sameLine && gap < 42) {
        current.digits += digits;
        current.bbox.x1 = Math.max(current.bbox.x1, w.bbox.x1);
        current.bbox.y0 = Math.min(current.bbox.y0, w.bbox.y0);
        current.bbox.y1 = Math.max(current.bbox.y1, w.bbox.y1);
      } else {
        groups.push(current);
        current = { digits: digits, bbox: { x0: w.bbox.x0, y0: w.bbox.y0, x1: w.bbox.x1, y1: w.bbox.y1 } };
      }
    });
    if (current) groups.push(current);
    return groups;
  }

  function extractReferenceFromWords(words, canvasWidth) {
    var candidates = [];
    function add(val, score, xNorm, source) {
      if (!val || val.length < 6 || !/^\d+$/.test(val)) return;
      candidates.push({
        val: val,
        score: score,
        xNorm: xNorm || 0,
        source: source || 'words',
        conf: 0.78,
      });
    }

    mergeAdjacentDigitWords(words).forEach(function (group) {
      var xCenter = (group.bbox.x0 + group.bbox.x1) / 2;
      var xNorm = canvasWidth ? xCenter / canvasWidth : 0;
      add(group.digits, scoreReferenceDigits(group.digits, 120) + xNorm * 35, xNorm, 'words-merged');
    });

    (words || []).forEach(function (w) {
      var raw = String(w.text || '').trim();
      if (!raw) return;
      var xCenter = w.bbox ? ((w.bbox.x0 + w.bbox.x1) / 2) : 0;
      var xNorm = canvasWidth ? xCenter / canvasWidth : 0;
      var direct = normalizeReferenceDigitRun(raw);
      if (/^\d{6,}$/.test(direct)) {
        add(direct, scoreReferenceDigits(direct, 108) + xNorm * 28, xNorm, 'words');
      }
      var re = /\d{5,}/g;
      var m;
      while ((m = re.exec(raw)) !== null) {
        var run = normalizeReferenceDigitRun(m[0]);
        if (run.length >= 6) add(run, scoreReferenceDigits(run, 100) + xNorm * 24, xNorm, 'words-run');
      }
    });

    if (!candidates.length) return null;
    candidates.sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return b.val.length - a.val.length;
    });
    return candidates[0];
  }

  function isPlausibleReferenceId(val) {
    if (!val) return false;
    var v = String(val).replace(/\s/g, '').toUpperCase();
    if (!v || v.length < 6) return false;
    if (/^\d{6,24}$/.test(v)) return true;
    var letters = (v.match(/[A-Z]/g) || []).length;
    var digits = (v.match(/[0-9]/g) || []).length;
    if (digits >= 6 && letters <= 1) return true;
    return false;
  }

  function pickBestReferenceCandidate(candidates) {
    if (!candidates || !candidates.length) return fieldResult(null, 0, 'none');
    var filtered = candidates.filter(function (c) {
      return c && c.val && isPlausibleReferenceId(c.val);
    });
    if (!filtered.length) filtered = candidates;
    var scored = filtered.map(function (c) {
      var total = c.score || scoreReferenceDigits(c.val, 80);
      if (c.rank) total += c.rank * 0.35;
      if (c.xNorm > 0.55) total += 22;
      if (c.source && c.source.indexOf('words') === 0) total += 18;
      if (c.conf) total += c.conf * 20;
      if (/^\d+$/.test(String(c.val))) total += 45;
      if (!/^\d+$/.test(String(c.val))) total -= 80;
      return { val: c.val, total: total, conf: c.conf || 0.7, source: c.source || 'zone' };
    });
    scored.sort(function (a, b) {
      if (b.total !== a.total) return b.total - a.total;
      return b.val.length - a.val.length;
    });

    var best = scored[0];
    var eightDigit = scored.filter(function (s) { return s.val.length === 8; });
    if (eightDigit.length) {
      eightDigit.sort(function (a, b) { return b.total - a.total; });
      if (!best || best.val.length < 8 || eightDigit[0].total >= best.total - 12) {
        best = eightDigit[0];
      }
    }

    if (best && best.val.length === 7 && scored.length > 1) {
      var prefixMatch = scored.find(function (s) {
        return s.val.length === 8 && s.val.indexOf(best.val) === 0;
      });
      if (prefixMatch) best = prefixMatch;
    }

    return fieldResult(best.val, Math.min(0.98, best.conf), best.source);
  }

  function normalizeReferenceDigitRun(raw) {
    return String(raw || '')
      .replace(/[OoQD]/g, '0')
      .replace(/[lI|!]/g, '1')
      .replace(/[Ss$]/g, '5')
      .replace(/[Bb]/g, '8')
      .replace(/[Zz]/g, '2')
      .replace(/[Gg]/g, '6')
      .replace(/\s+/g, '');
  }

  function extractReferenceIdFromRaw(raw) {
    var text = String(raw || '');
    if (!text.trim()) return null;
    var labelPatterns = [
      /TRANSACTION\s*ID\s*\(\s*TID\s*\)\s*:\s*([0-9OIl|!\s]{4,20})/i,
      /TRANSACTION\s*REFERENCE\s*NO\.?\s*([0-9OIl|!\s]{6,20})/i,
      /\bI[DL1l]\s*#\s*([0-9OIl|!\s]{6,20})/i,
      /(?:T[IL1l]D|TXN)\s*#\s*([0-9OIl|!\s]{6,20})/i,
      /(?:T[IL1l]D|TXN)\s*:\s*([0-9OIl|!\s]{6,20})/i,
      /REFERENCE\s*NUMBER\s*:\s*([0-9OIl|!\s]{6,24})/i,
      /REFERENCE\s*NUMBER\s*#\s*([0-9OIl|!\s]{6,24})/i,
      /(?:TRANSACTION\s*ID|TRANSACTION|REFERENCE\s*(?:NO|NUMBER)?|REF\s*(?:NO|NUMBER)?|RAAST\s*ID)\s*[:\-#.]?\s*([0-9OIl|!\s]{6,})/i,
    ];
    var i;
    for (i = 0; i < labelPatterns.length; i++) {
      var labeled = text.match(labelPatterns[i]);
      if (labeled && labeled[1]) {
        var fromLabel = normalizeReferenceDigitRun(labeled[1]);
        if (fromLabel.length >= 6) return fromLabel;
      }
    }
    var afterHash = text.match(/#\s*([0-9OIl|!\s]{6,})/);
    if (afterHash && afterHash[1]) {
      var fromHash = normalizeReferenceDigitRun(afterHash[1]);
      if (fromHash.length >= 6) return fromHash;
    }
    return null;
  }

  /** Zonal crop parser — prefer pure digit runs (e.g. JazzCash 66556000), not label garbage. */
  function parseReferenceFromZone(text) {
    var raw = String(text || '');
    if (!raw.trim()) return null;
    var direct = extractReferenceIdFromRaw(raw);
    if (direct) return direct;
    var t = raw.replace(/TRANSACTION\s*ID\s*\(\s*TID\s*\)\s*:\s*/gi, ' ');
    t = fixOcrText(t, 'reference_no');
    t = t.replace(/TRANSACTION\s*REFERENCE\s*NO\.?\s*/gi, ' ');
    t = t.replace(/REFERENCE\s*NUMBER\s*[:#]?\s*/gi, ' ');
    t = t.replace(/\bI[DL1l]\s*#\s*/gi, ' ');
    t = t.replace(/(?:T[IL1l]D|TXN)\s*#\s*/gi, ' ');
    t = t.replace(/(?:T[IL1l]D|TXN)\s*:\s*/gi, ' ');
    t = t.replace(REF_LABEL_RE, ' ').replace(/\bID\b\s*[:\-#]?\s*/gi, ' ');
    t = t.replace(/[#:\-]/g, ' ').replace(/\s+/g, ' ').trim();

    var candidates = [];
    function addDigitRuns(source, baseScore) {
      var re = /\d{6,}/g;
      var m;
      while ((m = re.exec(source)) !== null) {
        candidates.push({ val: m[0], score: scoreReferenceDigits(m[0], baseScore) });
      }
      var merged = mergeReferenceDigitTokens(source.replace(/[^\d\s]/g, ' ').replace(/\s+/g, ' ').trim());
      if (merged) {
        candidates.push({ val: merged, score: scoreReferenceDigits(merged, baseScore + 24) });
      }
    }
    addDigitRuns(t, 140);
    addDigitRuns(raw.replace(/[^\d\s]/g, ' ').replace(/\s+/g, ' ').trim(), 132);

    var afterHash = raw.match(/#\s*([\d\s]{6,})/);
    if (afterHash && afterHash[1]) {
      var hashDigits = afterHash[1].replace(/\s+/g, '');
      if (hashDigits.length >= 6) {
        candidates.push({ val: hashDigits, score: scoreReferenceDigits(hashDigits, 150) });
      }
      var hashMerged = mergeReferenceDigitTokens(afterHash[1]);
      if (hashMerged) {
        candidates.push({ val: hashMerged, score: scoreReferenceDigits(hashMerged, 165) });
      }
    }

    if (!candidates.length) return null;
    candidates.sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return b.val.length - a.val.length;
    });
    return candidates[0].val;
  }

  function parseReferenceFromText(text) {
    var direct = extractReferenceIdFromRaw(text);
    if (direct && isPlausibleReferenceId(direct)) return direct;
    var zoneVal = parseReferenceFromZone(text);
    if (zoneVal && isPlausibleReferenceId(zoneVal)) return zoneVal;

    var t = fixOcrText(text, 'reference_no');
    var patterns = [
      /TRANSACTION\s*ID\s*\(\s*TID\s*\)\s*:\s*([0-9]{4,20})/gi,
      /\bI[DL1l]\s*#\s*([0-9]{6,20})/gi,
      /(?:T[IL1l]D|TXN)\s*#\s*([0-9]{6,20})/gi,
      /(?:T[IL1l]D|TXN)\s*[:#\-\s]*([0-9]{6,20})/gi,
      /REFERENCE\s*NUMBER\s*:\s*([0-9]{6,24})/gi,
      /REFERENCE\s*NUMBER\s*#\s*([0-9]{6,24})/gi,
      /TRANSACTION\s*REFERENCE\s*NO\.?\s*([0-9]{6,24})/gi,
      /(?:TID|TXN|TRANSACTION\s*ID|REFERENCE\s*(?:NO|NUMBER)?|REF\s*(?:NO|NUMBER)?|TRX\s*ID|RAAST\s*ID)\s*[:\-#.]?\s*([0-9]{6,})/gi,
      /\b([0-9]{8,})\b/g,
      /\b([0-9]{6,})\b/g,
    ];
    var best = null;
    var bestScore = -1;
    patterns.forEach(function (re, idx) {
      re.lastIndex = 0;
      var m;
      while ((m = re.exec(t)) !== null) {
        var val = (m[1] || '').replace(/\s/g, '');
        if (val.length < 6) continue;
        if (!isPlausibleReferenceId(val)) continue;
        if (REF_STOPWORDS[val]) continue;
        var score = 96 - idx * 11 + Math.min(val.length, 20);
        if (/^\d+$/.test(val)) score += 35;
        if (/^\d+$/.test(val) && val.length >= 10) score += 10;
        if (/^\d+$/.test(val) && val.length >= 6 && val.length <= 7) score += 8;
        if (!/^\d+$/.test(val) && !/[A-Z]/.test(val)) score -= 20;
        if (score > bestScore) {
          bestScore = score;
          best = val;
        }
      }
    });
    if (best && isPlausibleReferenceId(best)) return best;
    if (zoneVal && isPlausibleReferenceId(zoneVal)) return zoneVal;
    return null;
  }

  function fieldValueRank(fieldKey, val, ocrConf) {
    if (!val) return 0;
    var rank = (ocrConf || 0.5) * 100;
    if (fieldKey === 'reference_no') {
      if (/^\d+$/.test(val)) {
        rank += 90;
        if (val.length >= 8 && val.length <= 14) rank += 30;
        if (val.length === 7) rank -= 12;
      } else if (/[A-Z]/.test(val) && /[0-9]/.test(val)) rank += 25;
      else rank -= 30;
      rank += Math.min(val.length, 18) * 2;
    } else if (fieldKey === 'amount') {
      rank += 20;
      if (!validateAmountCandidate(val, '', { allowSmall: true })) rank -= 120;
      if (/^\d{8,}$/.test(String(val).replace(/[.,]/g, ''))) rank -= 150;
    } else if (fieldKey === 'date') {
      if (/^\d{2}-\d{2}-\d{4}$/.test(val)) rank += 140;
      else if (/^\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}$/.test(val)) rank += 100;
      else rank -= 50;
    }
    return rank;
  }

  function isViableOcrCrop(px, fieldKey) {
    if (!px || !px.w || !px.h) return false;
    if (fieldKey === 'reference_no') return px.w >= 36 && px.h >= 10;
    return px.w >= 20 && px.h >= 8;
  }

  function referenceFromFullTextInline(fullText) {
    if (!fullText) return null;
    var direct = extractReferenceIdFromRaw(fullText);
    if (direct && isPlausibleReferenceId(direct)) return fieldResult(direct, 0.74, 'full-inline');
    var parsed = parseReferenceFromText(fullText);
    if (parsed && isPlausibleReferenceId(parsed)) return fieldResult(parsed, 0.68, 'full-parse');
    return null;
  }

  function fieldOcrVariants(fieldKey, fast, variantOpts) {
    variantOpts = variantOpts || {};
    if (fieldKey === 'date' && variantOpts.teachPreview) {
      return [
        {
          scale: 4.4,
          mode: 'invert',
          variant: 'date-teach-invert',
          psm: '7',
          padPct: 1,
          padAsym: { left: 0.4, right: 4, top: 1, bottom: 1 },
          noWhitelist: true,
        },
        { scale: 3.8, mode: 'photo-fix', variant: 'date-teach-photo', psm: '7', padPct: 0.8, noWhitelist: true },
        { scale: 3.6, mode: 'contrast', variant: 'date-teach-contrast', psm: '7', padPct: 1, noWhitelist: true },
        { scale: 3.4, mode: 'gray-boost', variant: 'date-teach-gray', psm: '7', padPct: 0.8 },
      ];
    }
    if (fieldKey === 'date') {
      if (fast) {
        return [
          { scale: 4.2, mode: 'invert', variant: 'date-fast-invert', psm: '7', padPct: 1, noWhitelist: true },
          { scale: 3.4, mode: 'photo-fix', variant: 'date-fast', psm: '7', padPct: 0.8, noWhitelist: true },
          { scale: 3.2, mode: 'contrast', variant: 'date-fast-contrast', psm: '7', padPct: 1, noWhitelist: true },
        ];
      }
      return [
        { scale: 4.2, mode: 'invert', variant: 'date-invert', psm: '7', padPct: 1, noWhitelist: true },
        { scale: 3.2, mode: 'photo-fix', variant: 'date-photo-3.2', psm: '7', padPct: 0.8 },
        { scale: 3.0, mode: 'gray-boost', variant: 'date-gray-3.0', psm: '7', padPct: 0.8 },
        { scale: 2.8, mode: 'contrast', variant: 'date-contrast-2.8', psm: '8', padPct: 1 },
        { scale: 3.4, mode: 'sharp', noWhitelist: true, variant: 'date-sharp-3.4', psm: '7', padPct: 0.6 },
      ];
    }
    if (fieldKey === 'amount' && variantOpts.teachPreview) {
      return [
        {
          scale: 4.8,
          mode: 'blue-ink',
          variant: 'amt-teach-blue',
          psm: '7',
          padPct: 1.6,
          padAsym: { left: 0.5, right: 6.5, top: 1.2, bottom: 1.4 },
          noWhitelist: true,
        },
        {
          scale: 4.6,
          mode: 'colored-ink',
          variant: 'amt-teach-colored',
          psm: '7',
          padPct: 1.6,
          padAsym: { left: 0.5, right: 6, top: 1.2, bottom: 1.4 },
          noWhitelist: true,
        },
        {
          scale: 4.8,
          mode: 'invert',
          variant: 'amt-teach-invert',
          psm: '7',
          padPct: 1.5,
          padAsym: { left: 0.5, right: 6, top: 1, bottom: 1.2 },
          noWhitelist: true,
        },
        {
          scale: 4.6,
          mode: 'warm-ink',
          variant: 'amt-teach-warm',
          psm: '7',
          padPct: 1.6,
          padAsym: { left: 0.5, right: 6, top: 1, bottom: 1.2 },
          noWhitelist: true,
        },
        {
          scale: 4.6,
          mode: 'photo-fix',
          variant: 'amt-teach-photo',
          psm: '6',
          padPct: 1.5,
          padAsym: { left: 0.6, right: 6, top: 1, bottom: 1.2 },
          noWhitelist: true,
        },
        {
          scale: 4.4,
          mode: 'contrast',
          variant: 'amt-teach-contrast',
          psm: '7',
          padPct: 1.5,
          padAsym: { left: 0.5, right: 5.5, top: 1, bottom: 1 },
          noWhitelist: true,
        },
      ];
    }
    if (fieldKey === 'amount') {
      if (fast) {
        return [
          {
            scale: 4.8,
            mode: 'blue-ink',
            variant: 'amt-fast-blue',
            psm: '7',
            padPct: 1.6,
            padAsym: { left: 0.5, right: 6.5, top: 1.2, bottom: 1.4 },
            noWhitelist: true,
          },
          {
            scale: 4.6,
            mode: 'colored-ink',
            variant: 'amt-fast-colored',
            psm: '7',
            padPct: 1.6,
            padAsym: { left: 0.5, right: 6, top: 1.2, bottom: 1.4 },
            noWhitelist: true,
          },
          {
            scale: 4.8,
            mode: 'invert',
            variant: 'amt-fast-invert',
            psm: '7',
            padPct: 1.5,
            padAsym: { left: 0.5, right: 6, top: 1, bottom: 1.2 },
            noWhitelist: true,
          },
          {
            scale: 4.8,
            mode: 'red-ink',
            variant: 'amt-fast-red',
            psm: '7',
            padPct: 1.6,
            padAsym: { left: 0.5, right: 6.5, top: 1, bottom: 1.2 },
            noWhitelist: true,
          },
          { scale: 4.6, mode: 'warm-ink', variant: 'amt-fast-warm', psm: '7', padPct: 1.6, padAsym: { left: 0.5, right: 6, top: 1, bottom: 1.2 }, noWhitelist: true },
          { scale: 4.4, mode: 'colored-ink', variant: 'amt-fast-colored', psm: '7', padPct: 1.6, padAsym: { left: 0.5, right: 5.5, top: 1, bottom: 1 }, noWhitelist: true },
          { scale: 4.4, mode: 'photo-fix', variant: 'amt-fast-photo-dec', psm: '6', padPct: 1.5, padAsym: { left: 0.6, right: 6, top: 1, bottom: 1.2 }, noWhitelist: true },
          { scale: 3.4, mode: 'photo-fix', variant: 'amt-fast-photo', psm: '7', padPct: 1.2, padAsym: { right: 3.5 } },
          { scale: 3.2, mode: 'contrast', variant: 'amt-fast-contrast', psm: '7', padPct: 1.5, padAsym: { right: 3.5 } },
        ];
      }
      return [
        {
          scale: 4.8,
          mode: 'red-ink',
          variant: 'amt-red-4.8',
          psm: '7',
          padPct: 1.6,
          padAsym: { left: 0.5, right: 6.5, top: 1, bottom: 1.2 },
          noWhitelist: true,
        },
        { scale: 4.6, mode: 'warm-ink', variant: 'amt-warm-4.6', psm: '7', padPct: 1.6, padAsym: { left: 0.5, right: 6, top: 1, bottom: 1.2 }, noWhitelist: true },
        { scale: 4.6, mode: 'colored-ink', variant: 'amt-colored-4.6', psm: '7', padPct: 1.6, padAsym: { left: 0.5, right: 5.5, top: 1, bottom: 1 }, noWhitelist: true },
        { scale: 4.6, mode: 'photo-fix', variant: 'amt-photo-dec-4.6', psm: '6', padPct: 1.5, padAsym: { left: 0.6, right: 6, top: 1, bottom: 1.2 }, noWhitelist: true },
        {
          scale: 4.8,
          mode: 'invert',
          variant: 'amt-invert',
          psm: '7',
          padPct: 1.5,
          padAsym: { left: 0.5, right: 7, top: 1, bottom: 1.2 },
          noWhitelist: true,
        },
        { scale: 4.0, mode: 'photo-fix', variant: 'amt-photo-4.0', psm: '7', padPct: 1.2, padAsym: { right: 3.5 } },
        { scale: 3.6, mode: 'contrast', variant: 'amt-contrast-3.6', psm: '7', padPct: 1.3, padAsym: { right: 3.5 } },
        { scale: 3.4, mode: 'gray-boost', variant: 'amt-gray-3.4', psm: '7', padPct: 1.5 },
        { scale: 3.0, mode: 'sharp', variant: 'amt-sharp-3.0', psm: '8', padPct: 2 },
      ];
    }
    if (fieldKey === 'reference_no' && variantOpts.teachPreview) {
      return [
        {
          scale: 4.8,
          mode: 'colored-ink',
          variant: 'teach-orange-ref',
          psm: '7',
          padPct: 1.2,
          padAsym: { left: 0.4, right: 6, top: 1, bottom: 1 },
          noWhitelist: true,
        },
        {
          scale: 4.6,
          mode: 'warm-ink',
          variant: 'teach-warm-ref',
          psm: '7',
          padPct: 1.2,
          padAsym: { left: 0.4, right: 6, top: 1, bottom: 1 },
          noWhitelist: true,
        },
        {
          scale: 4.6,
          mode: 'invert',
          variant: 'teach-invert-line',
          psm: '7',
          padPct: 1.2,
          padAsym: { left: 0.4, right: 6, top: 1, bottom: 1 },
          noWhitelist: true,
        },
        {
          scale: 4.2,
          mode: 'photo-fix',
          variant: 'teach-mixed-line',
          psm: '7',
          padPct: 1.2,
          padAsym: { left: 0.6, right: 5.5, top: 1, bottom: 1 },
          canvasMargin: { right: 0.24 },
        },
        {
          scale: 4.4,
          mode: 'gray-boost',
          variant: 'teach-block',
          noWhitelist: true,
          psm: '6',
          padPct: 1.4,
          padAsym: { left: 0.8, right: 5.5, top: 1.4, bottom: 1.4 },
          canvasMargin: { right: 0.2 },
        },
        {
          scale: 5.2,
          mode: 'contrast',
          variant: 'teach-tail35',
          digitsOnly: true,
          psm: '8',
          regionSlice: 'right35',
          padPct: 0.6,
          padAsym: { left: 0.3, right: 6, top: 1, bottom: 1 },
          canvasMargin: { left: 0.02, right: 0.32 },
        },
        {
          scale: 4.8,
          mode: 'gray-boost',
          variant: 'teach-tail40',
          digitsOnly: true,
          psm: '7',
          regionSlice: 'right40',
          padPct: 0.7,
          padAsym: { left: 0.4, right: 5.5, top: 1, bottom: 1 },
          canvasMargin: { left: 0.03, right: 0.28 },
        },
        {
          scale: 4.6,
          mode: 'binary',
          variant: 'teach-binary-line',
          psm: '7',
          padPct: 1.0,
          padAsym: { left: 0.6, right: 5.5, top: 1.2, bottom: 1.2 },
          canvasMargin: { right: 0.22 },
        },
        {
          scale: 5.0,
          mode: 'sharp',
          variant: 'teach-tail50',
          digitsOnly: true,
          psm: '7',
          regionSlice: 'right50',
          padPct: 0.8,
          padAsym: { left: 0.4, right: 5, top: 1.2, bottom: 1.2 },
          canvasMargin: { left: 0.03, right: 0.25 },
        },
      ];
    }
    if (fast) {
      if (fieldKey === 'reference_no') {
        return [
          {
            scale: 4.6,
            mode: 'invert',
            variant: 'ref-fast-invert',
            psm: '7',
            padPct: 1.2,
            padAsym: { left: 0.4, right: 6, top: 1, bottom: 1 },
            noWhitelist: true,
          },
          {
            scale: 4.8,
            mode: 'colored-ink',
            variant: 'ref-fast-orange',
            psm: '7',
            padPct: 1.2,
            padAsym: { left: 0.4, right: 6, top: 1, bottom: 1 },
            noWhitelist: true,
          },
          {
            scale: 4.6,
            mode: 'warm-ink',
            variant: 'ref-fast-warm',
            psm: '7',
            padPct: 1.2,
            padAsym: { left: 0.4, right: 6, top: 1, bottom: 1 },
            noWhitelist: true,
          },
          {
            scale: 4.6,
            mode: 'invert',
            variant: 'ref-fast-invert',
            psm: '7',
            padPct: 1.2,
            padAsym: { left: 0.4, right: 6, top: 1, bottom: 1 },
            noWhitelist: true,
          },
          {
            scale: 4.4,
            mode: 'contrast',
            variant: 'ref-fast-contrast-line',
            psm: '7',
            padPct: 1.3,
            padAsym: { left: 0.5, right: 5.5, top: 1, bottom: 1 },
            noWhitelist: true,
          },
          {
            scale: 5.2,
            mode: 'photo-fix',
            variant: 'ref-fast-tail30',
            digitsOnly: true,
            psm: '8',
            regionSlice: 'right30',
            padPct: 0.6,
            padAsym: { left: 0.3, right: 5.5, top: 1, bottom: 1 },
            canvasMargin: { left: 0.02, right: 0.32 },
          },
          {
            scale: 4.8,
            mode: 'normal',
            variant: 'ref-fast-tail40',
            digitsOnly: true,
            psm: '7',
            regionSlice: 'right40',
            padPct: 0.8,
            padAsym: { left: 0.4, right: 5, top: 1, bottom: 1 },
            canvasMargin: { left: 0.03, right: 0.28 },
          },
          {
            scale: 4,
            mode: 'normal',
            variant: 'ref-fast-mixed',
            psm: '7',
            padPct: 1.2,
            padAsym: { left: 0.8, right: 5, top: 1, bottom: 1 },
            canvasMargin: { right: 0.22 },
          },
        ];
      }
      return [{ scale: 2.4, mode: 'gray-boost', variant: 'fast', padPct: 1.5 }];
    }
    if (fieldKey === 'reference_no') {
      return [
        {
          scale: 4.8,
          mode: 'colored-ink',
          variant: 'ref-orange-line',
          psm: '7',
          padPct: 1.2,
          padAsym: { left: 0.4, right: 6, top: 1, bottom: 1 },
          noWhitelist: true,
        },
        {
          scale: 4.6,
          mode: 'warm-ink',
          variant: 'ref-warm-line',
          psm: '7',
          padPct: 1.2,
          padAsym: { left: 0.4, right: 6, top: 1, bottom: 1 },
          noWhitelist: true,
        },
        {
          scale: 4,
          mode: 'normal',
          variant: 'ref-mixed-line',
          psm: '7',
          padPct: 1.5,
          padAsym: { left: 0.8, right: 5.5, top: 1.2, bottom: 1.2 },
          canvasMargin: { right: 0.24 },
        },
        {
          scale: 5.4,
          mode: 'normal',
          variant: 'ref-tail-30',
          digitsOnly: true,
          psm: '8',
          regionSlice: 'right30',
          padPct: 0.6,
          padAsym: { left: 0.3, right: 6, top: 1.2, bottom: 1.2 },
          canvasMargin: { left: 0.02, right: 0.34 },
        },
        {
          scale: 5,
          mode: 'normal',
          variant: 'ref-tail-35',
          digitsOnly: true,
          psm: '8',
          regionSlice: 'right35',
          padPct: 0.7,
          padAsym: { left: 0.35, right: 5.5, top: 1.2, bottom: 1.2 },
          canvasMargin: { left: 0.02, right: 0.3 },
        },
        {
          scale: 4.8,
          mode: 'normal',
          variant: 'ref-tail-40',
          digitsOnly: true,
          psm: '7',
          regionSlice: 'right40',
          padPct: 0.8,
          padAsym: { left: 0.4, right: 5.2, top: 1.2, bottom: 1.2 },
          canvasMargin: { left: 0.03, right: 0.28 },
        },
        {
          scale: 4.6,
          mode: 'normal',
          variant: 'ref-tail-45',
          digitsOnly: true,
          psm: '7',
          regionSlice: 'right45',
          padPct: 0.8,
          padAsym: { left: 0.4, right: 5, top: 1.2, bottom: 1.2 },
          canvasMargin: { left: 0.03, right: 0.26 },
        },
        {
          scale: 4.2,
          mode: 'gray-boost',
          variant: 'ref-tail-55',
          digitsOnly: true,
          psm: '8',
          regionSlice: 'right55',
          padPct: 1,
          padAsym: { left: 0.5, right: 4.5, top: 1, bottom: 1 },
          canvasMargin: { left: 0.04, right: 0.22 },
        },
      ];
    }
    return [
      { scale: 2.2, mode: 'normal', variant: 'normal-2.2', padPct: 2 },
      { scale: 2.8, mode: 'gray-boost', variant: 'gray-2.8', padPct: 2 },
      { scale: 3.2, mode: 'gray-boost', noWhitelist: true, variant: 'gray-nowl-3.2', padPct: 2 },
    ];
  }

  function parseNearAnchor(fullText, anchors, parser) {
    var upper = String(fullText || '').toUpperCase();
    for (var i = 0; i < anchors.length; i++) {
      var idx = upper.indexOf(anchors[i]);
      if (idx === -1) continue;
      var slice = fullText.substr(Math.max(0, idx), 140);
      var val = parser(slice);
      if (val) return val;
    }
    return null;
  }

  function buildFingerprint(text) {
    var upper = String(text || '').toUpperCase().replace(/[^A-Z0-9\s]/g, ' ');
    var words = upper.split(/\s+/).filter(function (w) {
      return w.length >= 3 && !STOP_WORDS[w];
    });
    var seen = {};
    var out = [];
    words.forEach(function (w) {
      if (seen[w]) return;
      seen[w] = 1;
      out.push(w);
    });
    PROVIDER_TEMPLATES.forEach(function (p) {
      p.keys.forEach(function (k) {
        var kk = k.replace(/\s+/g, '');
        if (fuzzyKeywordInText(upper, k) && !seen[kk]) {
          seen[kk] = 1;
          out.unshift(kk);
        }
      });
    });
    return out.slice(0, 45);
  }

  function scoreProfile(profile, ocrText) {
    var upper = String(ocrText || '').toUpperCase();
    var keys = profile.fingerprint_keywords || [];
    var namePart = stringSimilarity(profile.name || '', upper) * 0.25;
    if (!keys.length) return namePart;
    var hits = 0;
    keys.forEach(function (k) {
      if (fuzzyKeywordInText(upper, k)) hits++;
    });
    var keyPart = (hits / keys.length) * 0.75;
    return namePart + keyPart;
  }

  function keywordSharedWithOtherProfiles(keyword, profile, allProfiles) {
    return (allProfiles || []).some(function (other) {
      if (!other || other.id === profile.id) return false;
      return (other.fingerprint_keywords || []).some(function (ok) {
        if (!ok || !keyword) return false;
        if (String(ok).toUpperCase() === String(keyword).toUpperCase()) return true;
        return fuzzyKeywordInText(ok, keyword) || fuzzyKeywordInText(keyword, ok);
      });
    });
  }

  /** Prefer keywords unique to one saved design (helps multiple HBL/JazzCash layouts). */
  function scoreProfileDistinct(profile, ocrText, allProfiles) {
    var base = scoreProfile(profile, ocrText);
    var upper = String(ocrText || '').toUpperCase();
    var keys = profile.fingerprint_keywords || [];
    if (!keys.length || !allProfiles || allProfiles.length < 2) return base;
    var uniqueHits = 0;
    var uniqueTotal = 0;
    keys.forEach(function (k) {
      if (keywordSharedWithOtherProfiles(k, profile, allProfiles)) return;
      uniqueTotal++;
      if (fuzzyKeywordInText(upper, k)) uniqueHits++;
    });
    if (uniqueTotal > 0) {
      base += (uniqueHits / uniqueTotal) * 0.4;
    }
    var nameTokens = String(profile.name || '').toUpperCase().split(/[^A-Z0-9]+/).filter(function (w) {
      return w.length >= 3;
    });
    nameTokens.forEach(function (tok) {
      if (fuzzyKeywordInText(upper, tok)) base += 0.08;
    });
    return base;
  }

  function rankProfiles(profiles, ocrText) {
    return (profiles || []).map(function (p) {
      return { profile: p, score: scoreProfileDistinct(p, ocrText, profiles) };
    }).sort(function (a, b) {
      return b.score - a.score;
    });
  }

  function extractionQuality(data) {
    if (!data) return 0;
    var filled = 0;
    var confSum = 0;
    ['date', 'amount', 'reference_no'].forEach(function (k) {
      var meta = data.fieldMeta && data.fieldMeta[k];
      var val = data[k] || (meta && meta.value);
      if (val && val !== '—') {
        filled++;
        confSum += (meta && typeof meta.confidence === 'number') ? meta.confidence : 0.55;
      }
    });
    return filled * 100 + confSum;
  }

  function selectProfileCandidates(ranked, options) {
    options = options || {};
    var minScore = typeof options.minScore === 'number' ? options.minScore : 0.16;
    var margin = typeof options.margin === 'number' ? options.margin : 0.14;
    var maxTry = typeof options.maxTry === 'number'
      ? options.maxTry
      : (ocrModeIsAccurate() ? 3 : (ocrModeIsFast() ? 1 : 2));
    if (!ranked || !ranked.length) return [];
    var filtered = ranked.filter(function (r) { return r.score >= minScore; });
    if (!filtered.length) filtered = ranked.slice(0, 1);
    var top = filtered[0].score;
    if (top >= 0.52) return [filtered[0]];
    if (top >= 0.38 && filtered.length > 1 && (top - filtered[1].score) >= 0.14) {
      return [filtered[0]];
    }
    var out = [filtered[0]];
    for (var i = 1; i < filtered.length && out.length < maxTry; i++) {
      if (top - filtered[i].score <= margin) out.push(filtered[i]);
      else break;
    }
    return out;
  }

  function isGoodEnoughExtract(data) {
    if (!data) return false;
    var filled = 0;
    ['date', 'amount', 'reference_no'].forEach(function (k) {
      if (data[k] && data[k] !== '—') filled++;
    });
    var q = extractionQuality(data);
    if (filled >= 3 && q >= 200) return true;
    if (q >= 235) return true;
    return filled >= 2 && q >= 175;
  }

  function isCompleteExtract(data) {
    if (!data) return false;
    if (!data.date || data.date === '—') return false;
    if (!data.amount || data.amount === '—') return false;
    if (!data.reference_no || data.reference_no === '—') return false;
    if (!isPlausibleReferenceId(data.reference_no)) return false;
    return isGoodEnoughExtract(data);
  }

  function attachProfileMeta(data, profile, score, fullText, provider, img) {
    data.profileName = profile.name;
    data.profileId = profile.id;
    data.profile = profile;
    data.matchScore = score;
    data.provider = provider ? provider.id : null;
    data.ocrText = fullText || '';
    if (img) data.img = img;
    return data;
  }

  function tryProfilesExtractSequential(img, candidates, fullText, useFast, options) {
    options = options || {};
    var skipIds = options.skipIds || {};
    if (!candidates || !candidates.length) return Promise.resolve(null);
    var best = null;
    var tried = 0;
    var chain = Promise.resolve();
    candidates.forEach(function (c) {
      if (skipIds[c.profile.id]) return;
      chain = chain.then(function () {
        if (best && isGoodEnoughExtract(best)) return;
        tried++;
        return extractWithProfile(img, c.profile, fullText, {
          fast: useFast,
          smart: true,
        }).then(function (data) {
          attachProfileMeta(data, c.profile, c.score, fullText, detectProvider(fullText), img);
          data._quality = extractionQuality(data);
          if (!best || data._quality > best._quality ||
              (data._quality === best._quality && (c.score || 0) > (best.matchScore || 0))) {
            best = data;
          }
          ocrLog('tryProfilesExtractSequential step', {
            profile: c.profile.name,
            quality: data._quality,
            tried: tried,
            goodEnough: isGoodEnoughExtract(data),
          });
        });
      });
    });
    return chain.then(function () { return best; });
  }

  function tryBestProfileExtract(img, ranked, fullText, useFast, options) {
    options = options || {};
    var candidates = selectProfileCandidates(ranked, options.selectOptions);
    return tryProfilesExtractSequential(img, candidates, fullText, useFast, options).then(function (best) {
      if (best && extractionQuality(best) > 0) return best;
      if (useFast && ranked.length) {
        var slowTop = ranked.slice(0, 1);
        return tryProfilesExtractSequential(img, slowTop, fullText, false, options);
      }
      return best;
    });
  }

  function findProfileById(profiles, id) {
    if (!id || !profiles || !profiles.length) return null;
    for (var i = 0; i < profiles.length; i++) {
      if (profiles[i].id === id) return profiles[i];
    }
    return null;
  }

  function detectProvider(ocrText) {
    var upper = String(ocrText || '').toUpperCase();
    var best = null;
    var bestScore = 0;
    PROVIDER_TEMPLATES.forEach(function (p) {
      var hits = 0;
      p.keys.forEach(function (k) {
        if (fuzzyKeywordInText(upper, k)) hits++;
      });
      var score = p.keys.length ? hits / p.keys.length : 0;
      if (score > bestScore) {
        bestScore = score;
        best = p;
      }
    });
    return bestScore >= 0.34 ? best : null;
  }

  function matchProfile(profiles, ocrText) {
    var best = null;
    var bestScore = 0;
    (profiles || []).forEach(function (p) {
      var s = scoreProfile(p, ocrText);
      if (s > bestScore) {
        bestScore = s;
        best = p;
      }
    });
    if (!best || bestScore < 0.22) return { profile: null, score: bestScore, provider: detectProvider(ocrText) };
    return { profile: best, score: bestScore, provider: detectProvider(ocrText) };
  }

  function fieldResult(value, confidence, source) {
    return {
      value: value || null,
      confidence: typeof confidence === 'number' ? confidence : (value ? 0.7 : 0),
      source: source || 'unknown',
    };
  }

  function mergeFieldResults(primary, fallback, minConf) {
    if (primary && primary.value && primary.confidence >= (minConf || 0.45)) return primary;
    if (fallback && fallback.value) {
      return fieldResult(fallback.value, Math.max(fallback.confidence || 0.5, primary ? primary.confidence : 0), fallback.source);
    }
    return primary && primary.value ? primary : fieldResult(null, 0, 'none');
  }

  function loadImageFromFile(file) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error('Image decode failed')); };
      img.src = URL.createObjectURL(file);
    });
  }

  function clamp255(v) {
    return v < 0 ? 0 : (v > 255 ? 255 : Math.round(v));
  }

  function applyGrayscalePixels(d) {
    for (var i = 0; i < d.length; i += 4) {
      var g = (0.299 * d[i]) + (0.587 * d[i + 1]) + (0.114 * d[i + 2]);
      d[i] = d[i + 1] = d[i + 2] = Math.round(g);
    }
  }

  function applyContrastPixels(d, factor) {
    factor = factor || 1.35;
    for (var i = 0; i < d.length; i += 4) {
      d[i] = clamp255((d[i] - 128) * factor + 128);
      d[i + 1] = clamp255((d[i + 1] - 128) * factor + 128);
      d[i + 2] = clamp255((d[i + 2] - 128) * factor + 128);
    }
  }

  function applyGrayBoostPixels(d, contrastFactor) {
    contrastFactor = contrastFactor || 1.28;
    for (var i = 0; i < d.length; i += 4) {
      var g = (0.299 * d[i]) + (0.587 * d[i + 1]) + (0.114 * d[i + 2]);
      g = g > 200 ? 255 : (g < 70 ? 0 : Math.min(255, g * contrastFactor));
      d[i] = d[i + 1] = d[i + 2] = g;
    }
  }

  /** Orange / terracotta slip amounts (e.g. Rs. 2,500.00) — gray-boost turns these white. */
  function applyWarmInkPixels(d) {
    for (var i = 0; i < d.length; i += 4) {
      var r = d[i];
      var g = d[i + 1];
      var b = d[i + 2];
      var warm = r - (g * 0.55) - (b * 0.3);
      var v = warm > 25 ? 0 : 255;
      d[i] = d[i + 1] = d[i + 2] = v;
    }
  }

  /** Dark red / maroon slip amounts (e.g. - PKR 20,000.00). */
  function applyRedInkPixels(d) {
    for (var i = 0; i < d.length; i += 4) {
      var r = d[i];
      var g = d[i + 1];
      var b = d[i + 2];
      var warm = r - (g * 0.55) - (b * 0.3);
      var maroon = r > 55 && r > g * 1.25 && r > b * 1.25 && (r - g) > 18;
      var v = (warm > 25 || maroon) ? 0 : 255;
      d[i] = d[i + 1] = d[i + 2] = v;
    }
  }

  /** Colored ink on white slips: orange Rs. amounts and green bank headers. */
  function applyColoredInkPixels(d) {
    for (var i = 0; i < d.length; i += 4) {
      var r = d[i];
      var gch = d[i + 1];
      var b = d[i + 2];
      var max = Math.max(r, gch, b);
      var min = Math.min(r, gch, b);
      var sat = max - min;
      var warm = r - (gch * 0.55) - (b * 0.3);
      var cool = gch - (r * 0.5) - (b * 0.2);
      var blue = b - (r * 0.42) - (gch * 0.28);
      var isInk = sat > 30 && max < 245 && (warm > 25 || cool > 20 || blue > 22);
      var v = isInk ? 0 : 255;
      d[i] = d[i + 1] = d[i + 2] = v;
    }
  }

  /** Bold blue slip amounts (e.g. PKR 1,000.00 TRANSFERRED). */
  function applyBlueInkPixels(d) {
    for (var i = 0; i < d.length; i += 4) {
      var r = d[i];
      var g = d[i + 1];
      var b = d[i + 2];
      var blue = b - (r * 0.45) - (g * 0.25);
      var isBlue = blue > 18 && b > 55 && b > r && b > g;
      var v = isBlue ? 0 : 255;
      d[i] = d[i + 1] = d[i + 2] = v;
    }
  }

  /** White text on dark slip bars (e.g. TID # 12345…). */
  function applyInvertPixels(d) {
    for (var i = 0; i < d.length; i += 4) {
      d[i] = 255 - d[i];
      d[i + 1] = 255 - d[i + 1];
      d[i + 2] = 255 - d[i + 2];
    }
  }

  function applyAdaptiveBinaryPixels(d) {
    var gray = [];
    var sum = 0;
    var i;
    for (i = 0; i < d.length; i += 4) {
      var g = (0.299 * d[i]) + (0.587 * d[i + 1]) + (0.114 * d[i + 2]);
      gray.push(g);
      sum += g;
    }
    var threshold = (sum / gray.length) * 0.9;
    for (i = 0; i < gray.length; i++) {
      var v = gray[i] > threshold ? 255 : 0;
      var j = i * 4;
      d[j] = d[j + 1] = d[j + 2] = v;
    }
  }

  function applySharpenCanvas(ctx, canvas) {
    try {
      var c2 = document.createElement('canvas');
      c2.width = canvas.width;
      c2.height = canvas.height;
      var ctx2 = c2.getContext('2d');
      ctx2.filter = 'contrast(1.22) brightness(1.04)';
      ctx2.drawImage(canvas, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(c2, 0, 0);
    } catch (e) { /* ignore */ }
  }

  function applyPhotoFix(ctx, canvas) {
    var id = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var d = id.data;
    applyGrayscalePixels(d);
    applyContrastPixels(d, 1.32);
    applyGrayBoostPixels(d, 1.15);
    ctx.putImageData(id, 0, 0);
    applySharpenCanvas(ctx, canvas);
  }

  function enhanceCanvas(ctx, canvas, mode) {
    if (!mode || mode === 'none') return;
    if (mode === 'normal') {
      applySharpenCanvas(ctx, canvas);
      return;
    }
    if (mode === 'photo-fix') {
      applyPhotoFix(ctx, canvas);
      return;
    }
    if (mode === 'contrast') {
      var idC = ctx.getImageData(0, 0, canvas.width, canvas.height);
      applyGrayscalePixels(idC.data);
      applyContrastPixels(idC.data, 1.45);
      ctx.putImageData(idC, 0, 0);
      applySharpenCanvas(ctx, canvas);
      return;
    }
    if (mode === 'sharp') {
      applySharpenCanvas(ctx, canvas);
      var idS = ctx.getImageData(0, 0, canvas.width, canvas.height);
      applyContrastPixels(idS.data, 1.18);
      ctx.putImageData(idS, 0, 0);
      return;
    }
    if (mode === 'binary') {
      var idB = ctx.getImageData(0, 0, canvas.width, canvas.height);
      applyGrayscalePixels(idB.data);
      applyAdaptiveBinaryPixels(idB.data);
      ctx.putImageData(idB, 0, 0);
      return;
    }
    if (mode === 'warm-ink') {
      var idW = ctx.getImageData(0, 0, canvas.width, canvas.height);
      applyWarmInkPixels(idW.data);
      ctx.putImageData(idW, 0, 0);
      applySharpenCanvas(ctx, canvas);
      return;
    }
    if (mode === 'red-ink') {
      var idR = ctx.getImageData(0, 0, canvas.width, canvas.height);
      applyRedInkPixels(idR.data);
      ctx.putImageData(idR, 0, 0);
      applySharpenCanvas(ctx, canvas);
      return;
    }
    if (mode === 'colored-ink') {
      var idCInk = ctx.getImageData(0, 0, canvas.width, canvas.height);
      applyColoredInkPixels(idCInk.data);
      ctx.putImageData(idCInk, 0, 0);
      applySharpenCanvas(ctx, canvas);
      return;
    }
    if (mode === 'blue-ink') {
      var idBlue = ctx.getImageData(0, 0, canvas.width, canvas.height);
      applyBlueInkPixels(idBlue.data);
      ctx.putImageData(idBlue, 0, 0);
      applySharpenCanvas(ctx, canvas);
      return;
    }
    if (mode === 'invert') {
      var idInv = ctx.getImageData(0, 0, canvas.width, canvas.height);
      applyInvertPixels(idInv.data);
      applyGrayscalePixels(idInv.data);
      applyContrastPixels(idInv.data, 1.35);
      applyAdaptiveBinaryPixels(idInv.data);
      ctx.putImageData(idInv, 0, 0);
      return;
    }
    var idG = ctx.getImageData(0, 0, canvas.width, canvas.height);
    applyGrayBoostPixels(idG.data, 1.28);
    ctx.putImageData(idG, 0, 0);
  }

  /** Regions stored as 0–100 % of natural image width/height (resolution independent). */
  function imagePixelSize(img) {
    return {
      w: img.naturalWidth || img.width || 0,
      h: img.naturalHeight || img.height || 0,
    };
  }

  function ocrDebugEnabled() {
    if (global.__wsSlipOcrDebug === true) return true;
    if (global.__wsSlipOcrDebug === false) return false;
    return ocrConfig().debug;
  }

  function ocrLog(label, payload) {
    if (!ocrDebugEnabled()) return;
    try {
      if (payload !== undefined) {
        console.log('[ws-slip-ocr] ' + label, payload);
      } else {
        console.log('[ws-slip-ocr] ' + label);
      }
    } catch (e) { /* ignore */ }
  }

  /** Convert % region → raw pixel crop rect on the source image. */
  function regionToPixelRect(img, region, padPct, padAsym) {
    var size = imagePixelSize(img);
    if (!size.w || !size.h) return null;
    region = padRegionPercent(region, typeof padPct === 'number' ? padPct : 2, padAsym);
    var rx = Math.max(0, Math.floor(size.w * (region.region_x || 0) / 100));
    var ry = Math.max(0, Math.floor(size.h * (region.region_y || 0) / 100));
    var rw = Math.max(24, Math.floor(size.w * (region.region_w || 10) / 100));
    var rh = Math.max(8, Math.floor(size.h * (region.region_h || 10) / 100));
    rw = Math.min(rw, size.w - rx);
    rh = Math.min(rh, size.h - ry);
    return {
      naturalW: size.w,
      naturalH: size.h,
      x: rx,
      y: ry,
      w: rw,
      h: rh,
      region: region,
    };
  }

  function logRegionMapping(tag, img, region) {
    var px = regionToPixelRect(img, region, 0);
    ocrLog(tag || 'region-map', px || { error: 'invalid image size', region: region });
    return px;
  }

  /** When user boxes full "Transaction ID # 12345" line, OCR only the numeric tail. */
  function sliceRegion(region, slice) {
    if (!slice || !region) return region;
    var x = region.region_x || 0;
    var y = region.region_y || 0;
    var w = region.region_w || 10;
    var h = region.region_h || 10;
    var keep = 0.45;
    if (slice === 'right30') keep = 0.3;
    else if (slice === 'right35') keep = 0.35;
    else if (slice === 'right40') keep = 0.4;
    else if (slice === 'right45') keep = 0.45;
    else if (slice === 'right50') keep = 0.5;
    else if (slice === 'right55') keep = 0.55;
    else return region;
    var start = Math.max(0, 1 - keep);
    return {
      region_x: x + w * start,
      region_y: y,
      region_w: Math.max(1, w * keep),
      region_h: h,
    };
  }

  function padRegionPercent(region, padPct, padAsym) {
    padPct = typeof padPct === 'number' ? padPct : 2.5;
    padAsym = padAsym || {};
    var left = typeof padAsym.left === 'number' ? padAsym.left : padPct;
    var right = typeof padAsym.right === 'number' ? padAsym.right : padPct;
    var top = typeof padAsym.top === 'number' ? padAsym.top : padPct;
    var bottom = typeof padAsym.bottom === 'number' ? padAsym.bottom : padPct;
    var x = Math.max(0, (region.region_x || 0) - left);
    var y = Math.max(0, (region.region_y || 0) - top);
    var w = Math.min(100 - x, (region.region_w || 10) + left + right);
    var h = Math.min(100 - y, (region.region_h || 10) + top + bottom);
    return { region_x: x, region_y: y, region_w: w, region_h: h };
  }

  function addCanvasMargin(canvas, margins) {
    margins = margins || {};
    var left = margins.left || 0;
    var right = margins.right || 0;
    var top = margins.top || 0;
    var bottom = margins.bottom || 0;
    if (!left && !right && !top && !bottom) return canvas;
    var leftPx = Math.max(0, Math.round(canvas.width * left));
    var rightPx = Math.max(0, Math.round(canvas.width * right));
    var topPx = Math.max(0, Math.round(canvas.height * top));
    var bottomPx = Math.max(0, Math.round(canvas.height * bottom));
    var out = document.createElement('canvas');
    out.width = canvas.width + leftPx + rightPx;
    out.height = canvas.height + topPx + bottomPx;
    var ctx = out.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(canvas, leftPx, topPx);
    return out;
  }

  function makeRegionCanvas(img, region, scale, mode, padPct, padAsym, canvasMargin) {
    var px = regionToPixelRect(img, region, typeof padPct === 'number' ? padPct : 2, padAsym);
    if (!px) {
      ocrLog('makeRegionCanvas: missing image pixels', { region: region });
      var c0 = document.createElement('canvas');
      c0.width = c0.height = 1;
      return c0;
    }
    var minCanvasW = 120;
    var minCanvasH = 48;
    var effScale = scale;
    if (px.w > 0) effScale = Math.max(effScale, minCanvasW / px.w);
    if (px.h > 0) effScale = Math.max(effScale, minCanvasH / px.h);
    var c = document.createElement('canvas');
    var targetW = Math.max(48, Math.round(px.w * effScale));
    var targetH = Math.max(24, Math.round(px.h * effScale));
    c.width = targetW;
    c.height = targetH;
    var ctx = c.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    try {
      ctx.drawImage(slipDrawTarget(img), px.x, px.y, px.w, px.h, 0, 0, c.width, c.height);
    } catch (drawErr) {
      ocrLog('makeRegionCanvas: drawImage failed', {
        error: drawErr && drawErr.message ? drawErr.message : drawErr,
        crop: px,
        imgComplete: !!img.complete,
        imgSrc: img.src ? String(img.src).slice(0, 80) : '',
      });
    }
    enhanceCanvas(ctx, c, mode);
    if (canvasMargin) c = addCanvasMargin(c, canvasMargin);
    ocrLog('makeRegionCanvas', {
      mode: mode,
      scale: scale,
      crop: { x: px.x, y: px.y, w: px.w, h: px.h },
      canvas: { w: c.width, h: c.height },
      natural: { w: px.naturalW, h: px.naturalH },
      regionPct: px.region,
      canvasMargin: canvasMargin || null,
    });
    return c;
  }

  function ocrCanvasRaw(canvas, fieldKey, opts) {
    opts = opts || {};
    return runOcrJob(function () {
      return getOcrWorker().then(function (worker) {
        return worker.setParameters(buildOcrParams(fieldKey, opts)).then(function () {
          return worker.recognize(canvas);
        });
      }).catch(function (err) {
        ocrLog('ocrCanvasRaw worker fallback', { error: err && err.message ? err.message : err });
        return recognizeCanvasOnce(canvas, fieldKey, opts);
      });
    });
  }

  function ocrCanvas(canvas, fieldKey, opts) {
    opts = opts || {};
    function parseRecognizeResult(r) {
      var text = (r && r.data && r.data.text) ? r.data.text : '';
      var conf = (r && r.data && typeof r.data.confidence === 'number') ? r.data.confidence / 100 : 0.55;
      ocrLog('ocrCanvas result', {
        field: fieldKey || 'any',
        variant: opts.variant || 'default',
        text: text,
        confidence: conf,
        canvas: { w: canvas.width, h: canvas.height },
      });
      return { text: text, confidence: conf };
    }
    return runOcrJob(function () {
      return getOcrWorker().then(function (worker) {
        return worker.setParameters(buildOcrParams(fieldKey, opts)).then(function () {
          return worker.recognize(canvas);
        }).then(parseRecognizeResult);
      }).catch(function (err) {
        ocrLog('ocrCanvas worker fallback', { error: err && err.message ? err.message : err });
        return recognizeCanvasOnce(canvas, fieldKey, opts).then(parseRecognizeResult);
      });
    }).catch(function (err) {
      ocrLog('ocrCanvas rejected', {
        field: fieldKey || 'any',
        variant: opts.variant || 'default',
        error: err && err.message ? err.message : err,
        canvas: canvas ? { w: canvas.width, h: canvas.height } : null,
      });
      return { text: '', confidence: 0 };
    });
  }

  function parseFieldLoose(fieldKey, text, opts) {
    opts = opts || {};
    if (fieldKey === 'reference_no' && (opts.zone || String(text || '').length < 120)) {
      var zoneRef = parseReferenceFromZone(text);
      if (zoneRef) return zoneRef;
    }
    var val = parseField(fieldKey, text);
    if (val) return val;
    var t = fixOcrText(String(text || ''), fieldKey === 'amount' ? 'amount' : (fieldKey === 'reference_no' ? 'reference_no' : null));
    if (fieldKey === 'date') {
      t = fixOcrTextForDate(text);
    }
    if (!t.trim()) return null;
    if (fieldKey === 'reference_no') {
      var digits = t.replace(/\D/g, '');
      if (digits.length >= 6) return digits;
      var alnum = t.replace(/\s/g, '').toUpperCase();
      if (alnum.length >= 6 && !REF_STOPWORDS[alnum]) return alnum;
    }
    if (fieldKey === 'amount') {
      var parsedAmt = parseAmountFromText(text, { strict: false });
      if (parsedAmt) return parsedAmt;
      var cleaned = fixOcrAmountText(text).replace(/,/g, '');
      var num = parseFloat(cleaned);
      if (isFinite(num) && num > 0) {
        return num % 1 === 0 ? String(Math.round(num)) : num.toFixed(2);
      }
    }
    if (fieldKey === 'date') {
      return parseDateFromText(t) || null;
    }
    return null;
  }

  function parseField(fieldKey, text) {
    if (fieldKey === 'date') return parseDateFromText(text);
    if (fieldKey === 'amount') return parseAmountFromText(text);
    if (fieldKey === 'reference_no') return parseReferenceFromText(text);
    return null;
  }

  function ocrHeaderReferenceScan(img) {
    var region = { region_x: 0, region_y: 0, region_w: 100, region_h: 30 };
    var modes = ocrModeIsFast()
      ? [{ scale: 2.8, mode: 'photo-fix', psm: '6', variant: 'header-fast' }]
      : [
        { scale: 3.2, mode: 'photo-fix', psm: '6', variant: 'header-photo' },
        { scale: 3.6, mode: 'contrast', psm: '7', variant: 'header-contrast' },
      ];
    if (ocrModeIsAccurate()) {
      modes.push({ scale: 3.8, mode: 'binary', psm: '7', variant: 'header-binary' });
    }
    var candidates = [];
    var chain = Promise.resolve();
    modes.forEach(function (m) {
      chain = chain.then(function () {
        var canvas = makeRegionCanvas(img, region, m.scale, m.mode, 0.5);
        return ocrCanvasRaw(canvas, 'reference_no', {
          psm: m.psm,
          noWhitelist: true,
          variant: m.variant,
        }).then(function (raw) {
          var text = (raw && raw.data && raw.data.text) ? raw.data.text : '';
          var words = (raw && raw.data && raw.data.words) ? raw.data.words : [];
          var conf = (raw && raw.data && typeof raw.data.confidence === 'number') ? raw.data.confidence / 100 : 0.55;
          var direct = extractReferenceIdFromRaw(text);
          if (direct && isPlausibleReferenceId(direct)) {
            candidates.push({
              val: direct,
              conf: Math.min(0.96, conf + 0.14),
              score: scoreReferenceDigits(direct, 132),
              source: 'header-inline',
            });
          }
          var wordHit = extractReferenceFromWords(words, canvas.width);
          if (wordHit) {
            candidates.push({
              val: wordHit.val,
              conf: wordHit.conf,
              score: wordHit.score,
              source: wordHit.source || 'header-words',
            });
          }
        });
      });
    });
    return chain.then(function () {
      var best = pickBestReferenceCandidate(candidates);
      ocrLog('ocrHeaderReferenceScan', { candidates: candidates, best: best });
      return best && best.value
        ? fieldResult(best.value, best.confidence, best.source || 'header-scan')
        : fieldResult(null, 0, 'none');
    });
  }

  function applyReferenceConsensus(candidates) {
    var counts = {};
    candidates.forEach(function (c) {
      if (!c || !c.val) return;
      counts[c.val] = (counts[c.val] || 0) + 1;
    });
    candidates.forEach(function (c) {
      if (!c || !c.val) return;
      var n = counts[c.val] || 0;
      if (n >= 2) {
        c.score = (c.score || scoreReferenceDigits(c.val, 80)) + 45 + (n - 2) * 25;
        c.conf = Math.min(0.98, (c.conf || 0.6) + 0.08 + (n - 2) * 0.04);
      }
    });
    return candidates;
  }

  function ocrReferenceRegionField(img, region, opts) {
    opts = opts || {};
    region = expandReferenceRegion(region);
    var variants = fieldOcrVariants('reference_no', !!opts.fast, opts);
    var candidates = [];
    var labeledHits = 0;
    var stopEarly = false;
    var chain = Promise.resolve();

    ocrLog('ocrReferenceRegionField start', {
      fast: !!opts.fast,
      teachPreview: !!opts.teachPreview,
      region: region,
      pixels: regionToPixelRect(img, region, 0),
    });

    variants.forEach(function (v) {
      chain = chain.then(function () {
        if (stopEarly) return;
        var cropRegion = v.regionSlice ? sliceRegion(region, v.regionSlice) : region;
        var cropPx = regionToPixelRect(img, cropRegion, v.padPct, v.padAsym);
        if (!isViableOcrCrop(cropPx, 'reference_no')) {
          ocrLog('ocrReferenceRegionField skip tiny crop', { variant: v.variant, cropPx: cropPx });
          return;
        }
        var canvas = makeRegionCanvas(img, cropRegion, v.scale, v.mode, v.padPct, v.padAsym, v.canvasMargin);
        return ocrCanvasRaw(canvas, 'reference_no', {
          noWhitelist: v.noWhitelist,
          digitsOnly: v.digitsOnly,
          psm: v.psm,
          variant: v.variant,
        }).then(function (raw) {
          var text = (raw && raw.data && raw.data.text) ? raw.data.text : '';
          var conf = (raw && raw.data && typeof raw.data.confidence === 'number') ? raw.data.confidence / 100 : 0.55;

          // Logic 1: labeled match ("Transaction ID # 65872871") — strongest signal
          var labeled = extractReferenceIdFromRaw(text);
          if (labeled && isPlausibleReferenceId(labeled)) {
            labeledHits++;
            candidates.push({
              val: labeled,
              conf: Math.min(0.97, conf + 0.18),
              score: scoreReferenceDigits(labeled, 160),
              source: v.variant + '-labeled',
            });
            if (conf >= 0.55 || labeledHits >= 2) {
              stopEarly = true;
            }
          }

          // Logic 2: loose zone parse (digit runs, merged tokens)
          var val = parseFieldLoose('reference_no', text, { zone: true });
          ocrLog('ocrReferenceRegionField parse', {
            variant: v.variant,
            rawText: text,
            parsed: val,
            labeled: labeled || null,
          });
          if (val) {
            var rank = fieldValueRank('reference_no', val, conf);
            candidates.push({
              val: val,
              conf: Math.min(0.98, conf + (v.digitsOnly ? 0.08 : 0)),
              rank: rank,
              source: v.variant,
            });
          }

          // Logic 3: word-box scan (positional digit groups)
          var wordHit = extractReferenceFromWords(
            (raw && raw.data && raw.data.words) ? raw.data.words : [],
            canvas.width
          );
          if (wordHit) {
            candidates.push({
              val: wordHit.val,
              conf: wordHit.conf,
              score: wordHit.score,
              xNorm: wordHit.xNorm,
              source: wordHit.source,
            });
          }

          // Logic 4: digits-only consensus early stop (2 passes same value)
          if (!stopEarly && candidates.length >= 2) {
            var seen = {};
            candidates.forEach(function (c) {
              if (c && c.val && /^\d{6,}$/.test(c.val)) seen[c.val] = (seen[c.val] || 0) + 1;
            });
            Object.keys(seen).forEach(function (k) {
              if (seen[k] >= 3) stopEarly = true;
            });
          }
        });
      });
    });

    return chain.then(function () {
      // Logic 5: consensus voting — same value in multiple passes wins
      applyReferenceConsensus(candidates);
      var best = pickBestReferenceCandidate(candidates);
      var needsHeader = !best || !best.value || (best.confidence || 0) < 0.68;
      if (needsHeader && opts.fullText && extractReferenceIdFromRaw(opts.fullText)) {
        needsHeader = false;
      }
      if (needsHeader && opts.fast && best && best.value && isPlausibleReferenceId(best.value) &&
          (best.confidence || 0) >= 0.52) {
        needsHeader = false;
      }
      if (opts.zoneOnly) {
        needsHeader = false;
      }
      var headerPromise = needsHeader ? ocrHeaderReferenceScan(img) : Promise.resolve(null);
      return headerPromise.then(function (headerRes) {
        if (headerRes && headerRes.value) {
          candidates.push({
            val: headerRes.value,
            conf: headerRes.confidence,
            score: scoreReferenceDigits(headerRes.value, 128),
            source: headerRes.source || 'header-scan',
          });
          best = pickBestReferenceCandidate(candidates);
        }
        if (opts.fullText) {
          best = reconcileReferencePreview(best, opts.fullText);
        } else if (best && best.value && !isPlausibleReferenceId(best.value)) {
          best = fieldResult(null, 0, 'none');
        } else if (!best || !best.value) {
          best = fieldResult(null, 0, 'none');
        }
        ocrLog('ocrReferenceRegionField done', { candidates: candidates, best: best });
        return best;
      });
    });
  }

  function ocrAmountRegionField(img, region, opts) {
    opts = opts || {};
    region = expandAmountRegion(region);
    var variants = fieldOcrVariants('amount', !!opts.fast, opts);
    var candidates = [];
    var best = fieldResult(null, 0, 'zone');
    var bestRank = 0;
    var chain = Promise.resolve();

    ocrLog('ocrAmountRegionField start', {
      fast: !!opts.fast,
      region: region,
      pixels: regionToPixelRect(img, region, 0),
    });

    variants.forEach(function (v) {
      chain = chain.then(function () {
        if (best.value && bestRank >= 175) return;
        var cropRegion = v.regionSlice ? sliceRegion(region, v.regionSlice) : region;
        var canvas = makeRegionCanvas(img, cropRegion, v.scale, v.mode, v.padPct, v.padAsym, v.canvasMargin);
        return ocrCanvasRaw(canvas, 'amount', {
          noWhitelist: v.noWhitelist,
          digitsOnly: v.digitsOnly,
          psm: v.psm,
          variant: v.variant,
        }).then(function (raw) {
          var text = (raw && raw.data && raw.data.text) ? raw.data.text : '';
          var conf = (raw && raw.data && typeof raw.data.confidence === 'number') ? raw.data.confidence / 100 : 0.55;
          var val = parseFieldLoose('amount', text, { zone: true });
          ocrLog('ocrAmountRegionField parse', {
            variant: v.variant,
            rawText: text,
            parsed: val,
          });
          if (val) {
            var rank = fieldValueRank('amount', val, conf);
            candidates.push({ val: val, conf: conf, rank: rank, source: v.variant });
            if (!best.value || rank > bestRank) {
              bestRank = rank;
              best = fieldResult(val, conf, 'zone');
            }
          }
          var wordHit = extractAmountFromWords(
            (raw && raw.data && raw.data.words) ? raw.data.words : [],
            canvas.width
          );
          if (wordHit) {
            candidates.push({
              val: wordHit.val,
              conf: wordHit.conf,
              rank: fieldValueRank('amount', wordHit.val, wordHit.conf) + 24,
              source: wordHit.source,
            });
            if (!best.value || fieldValueRank('amount', wordHit.val, wordHit.conf) + 24 > bestRank) {
              bestRank = fieldValueRank('amount', wordHit.val, wordHit.conf) + 24;
              best = fieldResult(wordHit.val, wordHit.conf, wordHit.source || 'amount-words');
            }
          }
        });
      });
    });

    return chain.then(function () {
      if (opts.fullText) {
        best = reconcileAmountResult(best, opts.fullText);
      }
      ocrLog('ocrAmountRegionField done', { candidates: candidates, best: best, bestRank: bestRank });
      return best;
    });
  }

  function ocrRegionField(img, region, fieldKey, opts) {
    opts = opts || {};
    if (fieldKey === 'reference_no') {
      return ocrReferenceRegionField(img, region, opts);
    }
    if (fieldKey === 'amount') {
      return ocrAmountRegionField(img, region, opts);
    }
    ocrLog('ocrRegionField start', {
      field: fieldKey,
      fast: !!opts.fast,
      region: region,
      pixels: regionToPixelRect(img, region, 0),
    });
    var variants = fieldOcrVariants(fieldKey, !!opts.fast, opts);
    var best = fieldResult(null, 0, 'zone');
    var bestRank = 0;
    var chain = Promise.resolve();
    variants.forEach(function (v) {
      chain = chain.then(function () {
        if (best.value && bestRank >= 175) return;
        var cropRegion = v.regionSlice ? sliceRegion(region, v.regionSlice) : region;
        var canvas = makeRegionCanvas(img, cropRegion, v.scale, v.mode, v.padPct, v.padAsym, v.canvasMargin);
        return ocrCanvas(canvas, fieldKey, {
          noWhitelist: v.noWhitelist,
          digitsOnly: v.digitsOnly,
          psm: v.psm,
          variant: v.variant,
        }).then(function (ocr) {
          var val = parseFieldLoose(fieldKey, ocr.text, { zone: true });
          ocrLog('ocrRegionField parse', {
            field: fieldKey,
            variant: v.variant,
            rawText: ocr.text,
            parsed: val,
          });
          if (!val) return;
          var conf = Math.min(0.98, (ocr.confidence || 0.5) + (v.mode === 'gray-boost' ? 0.05 : 0));
          if (v.digitsOnly && /^\d+$/.test(val)) conf = Math.min(0.99, conf + 0.12);
          if (v.noWhitelist) conf = Math.max(0.45, conf - 0.08);
          var rank = fieldValueRank(fieldKey, val, conf);
          if (!best.value || rank > bestRank) {
            bestRank = rank;
            best = fieldResult(val, conf, 'zone');
          }
        });
      });
    });
    return chain.then(function () {
      ocrLog('ocrRegionField done', { field: fieldKey, best: best, bestRank: bestRank });
      return best;
    });
  }

  function buildAmountFallbacks(fullText) {
    var provider = detectProvider(fullText);
    var providerAmt = provider ? parseProviderAmount(fullText, provider.id) : null;
    var anchorAmt = fieldResult(
      parseNearAnchor(fullText, ['TRANSFERRED AMOUNT', 'AMOUNT', 'PKR', 'RS', 'SENT', 'PAID'], function (slice) {
        return parseAmountFromText(slice, { strict: true });
      }),
      0.72,
      'anchor'
    );
    var fullAmt = fieldResult(parseAmountFromText(fullText), 0.64, 'full');
    var amount = mergeFieldResults(providerAmt, mergeFieldResults(anchorAmt, fullAmt, 0.55), 0.58);
    return { provider: provider, amount: amount };
  }

  function fullTextFallback(fullText) {
    var amountPack = buildAmountFallbacks(fullText);
    return {
      date: fieldResult(parseDateFromText(fullText), 0.62, 'full'),
      amount: amountPack.amount,
      reference_no: fieldResult(parseReferenceFromText(fullText), 0.58, 'full'),
    };
  }

  function anchorFallback(fullText) {
    var amountPack = buildAmountFallbacks(fullText);
    return {
      date: fieldResult(parseNearAnchor(fullText, ['POSTING DATE', 'TRANSACTION DATE', 'DATE & TIME', 'DATE', 'ON', 'TIME'], parseDateFromText), 0.7, 'anchor'),
      amount: amountPack.amount,
      reference_no: fieldResult(parseNearAnchor(fullText, ['TRANSACTION ID (TID)', 'TRANSACTION REFERENCE NO', 'ID#', 'ID #', 'REFERENCE NUMBER', 'TRANSACTION ID', 'TID', 'TXN', 'TRANSACTION', 'REFERENCE', 'RAAST', 'TRX'], parseReferenceFromText), 0.68, 'anchor'),
    };
  }

  function reconcileAmountResult(zoneRes, fullText) {
    if (!fullText) return zoneRes || fieldResult(null, 0, 'none');
    var pack = buildAmountFallbacks(fullText);
    var fallback = pack.amount;
    if (!zoneRes || !zoneRes.value) {
      return fallback && fallback.value ? fallback : (zoneRes || fieldResult(null, 0, 'none'));
    }
    if (!fallback || !fallback.value) return zoneRes;
    if (amountValuesClose(zoneRes.value, fallback.value)) {
      return fieldResult(
        zoneRes.value,
        Math.min(0.98, Math.max(zoneRes.confidence || 0.5, fallback.confidence || 0.5) + 0.06),
        'zone+verified'
      );
    }
    if ((fallback.confidence || 0) >= (zoneRes.confidence || 0) - 0.04) {
      ocrLog('reconcileAmountResult prefer fallback', {
        zone: zoneRes,
        fallback: fallback,
      });
      return fallback;
    }
    return fieldResult(zoneRes.value, Math.max(0.42, (zoneRes.confidence || 0.5) - 0.12), 'zone-uncertain');
  }

  function reconcileReferencePreview(zoneRes, fullText) {
    if (!fullText) return zoneRes || fieldResult(null, 0, 'none');
    var fb = fullTextFallback(fullText);
    var ab = anchorFallback(fullText);
    var fallback = mergeFieldResults(ab.reference_no, fb.reference_no, 0.55);
    var candidates = [];

    if (zoneRes && zoneRes.value) {
      candidates.push({
        val: zoneRes.value,
        conf: zoneRes.confidence,
        rank: fieldValueRank('reference_no', zoneRes.value, zoneRes.confidence),
        source: zoneRes.source || 'zone',
      });
    }
    if (fallback && fallback.value) {
      candidates.push({
        val: fallback.value,
        conf: fallback.confidence,
        score: scoreReferenceDigits(fallback.value, 112),
        source: 'full-fallback',
      });
    }
    if (!candidates.length) return fieldResult(null, 0, 'none');

    var best = pickBestReferenceCandidate(candidates);
    if (zoneRes && zoneRes.value && best.value === zoneRes.value) {
      return fieldResult(
        best.value,
        Math.min(0.98, Math.max(best.confidence || 0.5, zoneRes.confidence || 0.5) + 0.05),
        'zone+verified'
      );
    }
    if (fallback && fallback.value && best.value === fallback.value) {
      return fieldResult(
        best.value,
        Math.max(0.5, (fallback.confidence || 0.62) - 0.04),
        zoneRes && zoneRes.value ? 'full-fallback-picked' : 'full-fallback'
      );
    }
    return best;
  }

  function previewRegionFieldWithFallback(img, fieldKey, region, fullText, opts) {
    opts = opts || {};
    var zoneOnly = !!opts.zoneOnly;
    var fb = fullText ? fullTextFallback(fullText) : null;
    var ab = fullText ? anchorFallback(fullText) : null;

    if (!region) {
      if (zoneOnly || !fullText || !fb || !ab) return Promise.resolve(fieldResult(null, 0, 'none'));
      return Promise.resolve(mergeFieldResults(ab[fieldKey], fb[fieldKey], 0.5));
    }

    return ocrRegionField(img, region, fieldKey, {
      fast: false,
      teachPreview: true,
      zoneOnly: zoneOnly,
      fullText: zoneOnly ? '' : fullText,
    }).then(function (zoneRes) {
      if (zoneOnly) {
        return zoneRes || fieldResult(null, 0, 'zone');
      }
      if (fieldKey === 'reference_no') {
        return zoneRes;
      }
      if (fieldKey === 'amount') {
        return reconcileAmountResult(zoneRes, fullText);
      }
      if (zoneRes && zoneRes.value) return zoneRes;
      if (!fullText || !fb || !ab) return zoneRes;
      return mergeFieldResults(zoneRes, mergeFieldResults(ab[fieldKey], fb[fieldKey], 0.5), 0.48);
    });
  }

  function sanitizeFieldMap(fieldMap, fullText) {
    if (!fieldMap) return fieldMap;
    var refVal = fieldMap.reference_no && fieldMap.reference_no.value;
    var amtVal = fieldMap.amount && fieldMap.amount.value;
    if (refVal && amtVal) {
      var refNorm = String(refVal).replace(/\D/g, '');
      var amtNorm = String(amtVal).replace(/\D/g, '');
      if (refNorm && amtNorm && (refNorm === amtNorm || refNorm.indexOf(amtNorm) !== -1 || amtNorm.indexOf(refNorm) !== -1)) {
        var pack = buildAmountFallbacks(fullText || '');
        if (pack.amount && pack.amount.value && !amountValuesClose(pack.amount.value, refVal)) {
          fieldMap.amount = pack.amount;
        } else {
          fieldMap.amount = fieldResult(null, 0, 'conflict-ref');
        }
      }
    }
    if (fieldMap.amount && fieldMap.amount.value && fullText &&
        !validateAmountCandidate(fieldMap.amount.value, fullText)) {
      var repaired = buildAmountFallbacks(fullText).amount;
      if (repaired && repaired.value) fieldMap.amount = repaired;
      else fieldMap.amount = fieldResult(fieldMap.amount.value, 0.38, 'invalid-amount');
    }
    return fieldMap;
  }

  function ocrProviderAmountFallback(img, fullText) {
    var provider = detectProvider(fullText);
    if (!provider || !PROVIDER_AMOUNT_REGIONS[provider.id]) {
      return Promise.resolve(fieldResult(null, 0, 'none'));
    }
    return ocrRegionField(img, PROVIDER_AMOUNT_REGIONS[provider.id], 'amount', { fast: false }).then(function (res) {
      if (res && res.value) {
        res.source = (res.source || 'zone') + '+' + provider.id + '-layout';
        if (!validateAmountCandidate(res.value, fullText)) {
          return fieldResult(null, 0, 'layout-invalid');
        }
      }
      return res;
    });
  }

  function ocrFullImageCached(img) {
    img = normalizeSlipImage(img);
    var cacheKey = img._raw || img;
    if (_fullTextCache.has(cacheKey)) {
      return Promise.resolve(_fullTextCache.get(cacheKey));
    }
    return ocrFullImage(img).then(function (text) {
      _fullTextCache.set(cacheKey, text);
      return text;
    });
  }

  function scoreFullTextCoverage(text) {
    if (!text) return 0;
    var ab = anchorFallback(text);
    var fb = fullTextFallback(text);
    var score = 0;
    ['date', 'amount', 'reference_no'].forEach(function (k) {
      var m = mergeFieldResults(ab[k], fb[k], 0.5);
      if (!m || !m.value) return;
      if (k === 'reference_no' && !isPlausibleReferenceId(m.value)) return;
      if (k === 'amount' && !validateAmountCandidate(m.value, text)) return;
      score += fieldValueRank(k, m.value, m.confidence || 0.55);
    });
    return score;
  }

  function ocrFullImagePass(img, passId) {
    img = normalizeSlipImage(img);
    var size = imagePixelSize(img);
    var canvas;
    if (passId === 'full') {
      var fullScale = size.w && size.w < 1500 ? (1500 / size.w) : 1.05;
      canvas = document.createElement('canvas');
      canvas.width = Math.round(size.w * fullScale);
      canvas.height = Math.round(size.h * fullScale);
      var ctx = canvas.getContext('2d');
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(slipDrawTarget(img), 0, 0, canvas.width, canvas.height);
      enhanceCanvas(ctx, canvas, 'photo-fix');
    } else if (passId === 'header') {
      canvas = makeRegionCanvas(img, { region_x: 0, region_y: 0, region_w: 100, region_h: 30 }, 2.5, 'photo-fix', 0);
    } else if (passId === 'body') {
      canvas = makeRegionCanvas(img, { region_x: 0, region_y: 10, region_w: 100, region_h: 45 }, 2.2, 'contrast', 0);
    } else {
      canvas = makeRegionCanvas(img, { region_x: 0, region_y: 52, region_w: 100, region_h: 45 }, 2.0, 'gray-boost', 0);
    }
    return ocrCanvas(canvas, null, { variant: 'smart-' + passId }).then(function (ocr) {
      return ocr.text || '';
    });
  }

  function ocrFullImageSmart(img) {
    img = normalizeSlipImage(img);
    var parts = [];
    function combined() {
      return parts.filter(Boolean).join('\n');
    }
    function quality() {
      return scoreFullTextCoverage(combined());
    }
    ocrLog('ocrFullImageSmart start');
    return ocrFullImagePass(img, 'full').then(function (t1) {
      parts.push(t1);
      if (quality() >= 215) {
        ocrLog('ocrFullImageSmart stop after full', { quality: quality() });
        return combined();
      }
      return ocrFullImagePass(img, 'header').then(function (t2) {
        parts.push(t2);
        if (quality() >= 195) {
          ocrLog('ocrFullImageSmart stop after header', { quality: quality() });
          return combined();
        }
        return ocrFullImagePass(img, 'body').then(function (t3) {
          parts.push(t3);
          if (quality() >= 175) {
            ocrLog('ocrFullImageSmart stop after body', { quality: quality() });
            return combined();
          }
          return ocrFullImagePass(img, 'footer').then(function (t4) {
            parts.push(t4);
            ocrLog('ocrFullImageSmart done all passes', { quality: quality() });
            return combined();
          });
        });
      });
    });
  }

  function getSlipFullTextForExtract(img) {
    img = normalizeSlipImage(img);
    var cacheKey = img._raw || img;
    if (_fullTextCache.has(cacheKey)) {
      return Promise.resolve(_fullTextCache.get(cacheKey));
    }
    return ocrFullImageSmart(img).then(function (text) {
      _fullTextCache.set(cacheKey, text);
      return text;
    });
  }

  function seededFieldResult(key, ab, fb, fullText, minConf) {
    var merged = mergeFieldResults(ab[key], fb[key], 0.5);
    if (!merged || !merged.value) return null;
    if (key === 'reference_no' && !isPlausibleReferenceId(merged.value)) return null;
    if (key === 'amount' && !validateAmountCandidate(merged.value, fullText)) return null;
    if ((merged.confidence || 0) < (minConf || 0.58)) return null;
    return merged;
  }

  function shouldSkipZoneOcr(key, seed, fullText, region) {
    if (!region || !seed || !seed.value) return false;
    if (key === 'reference_no') {
      if (!isPlausibleReferenceId(seed.value)) return false;
      if (seed.source === 'anchor' && (seed.confidence || 0) >= 0.62) return true;
      return (seed.confidence || 0) >= 0.66;
    }
    if (key === 'amount') {
      return (seed.confidence || 0) >= 0.68 && validateAmountCandidate(seed.value, fullText);
    }
    if (key === 'date') {
      return (seed.confidence || 0) >= 0.6;
    }
    return false;
  }

  function profileHasAllZones(profile) {
    if (!profile || !profile.fields || !profile.fields.length) return false;
    var have = { date: false, amount: false, reference_no: false };
    profile.fields.forEach(function (f) {
      if (f && f.field_key && have.hasOwnProperty(f.field_key)) {
        have[f.field_key] = true;
      }
    });
    return have.date && have.amount && have.reference_no;
  }

  function profileRegionMap(profile) {
    var regions = {};
    ((profile && profile.fields) || []).forEach(function (f) {
      if (f && f.field_key) regions[f.field_key] = f;
    });
    return regions;
  }

  function extractZonesOnly(img, profile, opts) {
    opts = opts || {};
    img = normalizeSlipImage(img);
    var zoneOnly = !!opts.zoneOnly;
    var fieldRegions = {};
    (profile.fields || []).forEach(function (f) { fieldRegions[f.field_key] = f; });
    var keys = ['date', 'amount', 'reference_no'];
    var chain = Promise.resolve([]);

    keys.forEach(function (key) {
      chain = chain.then(function (rows) {
        var region = fieldRegions[key];
        if (!region) {
          rows.push({ key: key, result: fieldResult(null, 0, 'none') });
          return rows;
        }
        return ocrRegionField(img, region, key, {
          fast: true,
          zoneOnly: zoneOnly,
          teachPreview: zoneOnly,
          fullText: opts.fullText || '',
        }).then(function (zoneRes) {
          var result = zoneRes || fieldResult(null, 0, 'zone');
          if (key === 'amount' && result.value) {
            result = reconcileAmountResult(result, opts.fullText || '');
          }
          if (!zoneOnly && key === 'reference_no' && (!result || !result.value || !isPlausibleReferenceId(result.value))) {
            return ocrHeaderReferenceScan(img).then(function (headerRes) {
              if (headerRes && headerRes.value && isPlausibleReferenceId(headerRes.value)) {
                result = headerRes;
              }
              rows.push({ key: key, result: result });
              if (typeof opts.onProgress === 'function' && result.value) {
                opts.onProgress({
                  key: key,
                  value: result.value,
                  result: result,
                  profileName: profile.name,
                });
              }
              return rows;
            });
          }
          rows.push({ key: key, result: result });
          if (typeof opts.onProgress === 'function' && result.value) {
            opts.onProgress({
              key: key,
              value: result.value,
              result: result,
              profileName: profile.name,
            });
          }
          return rows;
        });
      });
    });

    return chain.then(function (rows) {
      var out = {};
      rows.forEach(function (row) { out[row.key] = row.result; });
      var pseudo = rows.map(function (r) {
        return r.result && r.result.value ? String(r.result.value) : '';
      }).filter(Boolean).join('\n');
      sanitizeFieldMap(out, pseudo);
      var flat = flattenResults(out);
      flat.profileName = profile.name;
      flat.ocrText = opts.fullText || pseudo;
      ocrLog('extractZonesOnly done', {
        profile: profile.name,
        quality: extractionQuality(flat),
        fields: { date: flat.date, amount: flat.amount, reference_no: flat.reference_no },
      });
      return flat;
    });
  }

  function reinforceExtract(img, profile, fullText, data) {
    var fieldRegions = {};
    (profile.fields || []).forEach(function (f) { fieldRegions[f.field_key] = f; });
    var keysNeeding = ['date', 'amount', 'reference_no'].filter(function (k) {
      var meta = data.fieldMeta && data.fieldMeta[k];
      if (!meta || !meta.value) return !!fieldRegions[k];
      if ((meta.confidence || 0) < 0.55) return true;
      if (k === 'reference_no' && !isPlausibleReferenceId(meta.value)) return true;
      if (k === 'amount' && !validateAmountCandidate(meta.value, fullText)) return true;
      return false;
    });
    if (!keysNeeding.length) return Promise.resolve(data);
    ocrLog('reinforceExtract', { profile: profile.name, keys: keysNeeding });
    var chain = Promise.resolve(data);
    keysNeeding.forEach(function (key) {
      chain = chain.then(function (current) {
        var region = fieldRegions[key];
        if (!region) return current;
        return ocrRegionField(img, region, key, { fast: false, fullText: fullText }).then(function (zoneRes) {
          var finalRes = key === 'amount' ? reconcileAmountResult(zoneRes, fullText) : zoneRes;
          if (finalRes && finalRes.value) {
            current.fieldMeta = current.fieldMeta || {};
            current.fieldMeta[key] = finalRes;
            current[key] = finalRes.value;
          }
          return current;
        });
      });
    });
    return chain.then(function (current) {
      var out = {};
      ['date', 'amount', 'reference_no'].forEach(function (k) {
        out[k] = current.fieldMeta && current.fieldMeta[k]
          ? current.fieldMeta[k]
          : fieldResult(current[k], current[k] ? 0.5 : 0, 'reinforce');
      });
      sanitizeFieldMap(out, fullText);
      var flat = flattenResults(out);
      flat.profileName = current.profileName || profile.name;
      flat.ocrText = fullText;
      flat.fieldMeta = out;
      return flat;
    });
  }

  function ocrFullImage(img) {
    img = normalizeSlipImage(img);
    var fast = ocrModeIsFast();
    var canvases = [];
    var size = imagePixelSize(img);
    var fullScale = size.w && size.w < 1600 ? (1600 / size.w) : 1.05;
    var c1 = document.createElement('canvas');
    c1.width = Math.round(size.w * fullScale);
    c1.height = Math.round(size.h * fullScale);
    var ctx1 = c1.getContext('2d');
    ctx1.fillStyle = '#ffffff';
    ctx1.fillRect(0, 0, c1.width, c1.height);
    ctx1.drawImage(slipDrawTarget(img), 0, 0, c1.width, c1.height);
    enhanceCanvas(ctx1, c1, 'photo-fix');
    canvases.push(c1);
    canvases.push(makeRegionCanvas(img, { region_x: 0, region_y: 0, region_w: 100, region_h: 28 }, fast ? 2.4 : 2.8, 'photo-fix'));
    canvases.push(makeRegionCanvas(img, { region_x: 0, region_y: 8, region_w: 100, region_h: 42 }, fast ? 2.0 : 2.4, 'contrast'));
    if (!fast) {
      canvases.push(makeRegionCanvas(img, { region_x: 0, region_y: 35, region_w: 100, region_h: 55 }, 2.0, 'gray-boost'));
    }
    if (ocrModeIsAccurate()) {
      canvases.push(makeRegionCanvas(img, { region_x: 0, region_y: 12, region_w: 100, region_h: 38 }, 2.6, 'binary'));
    }
    var texts = [];
    var chain = Promise.resolve();
    canvases.forEach(function (canvas) {
      chain = chain.then(function () {
        return ocrCanvas(canvas, null).then(function (ocr) {
          if (ocr.text) texts.push(ocr.text);
        });
      });
    });
    return chain.then(function () { return texts.join('\n'); });
  }

  function flattenResults(fieldMap) {
    return {
      date: fieldMap.date ? fieldMap.date.value : null,
      amount: fieldMap.amount ? fieldMap.amount.value : null,
      reference_no: fieldMap.reference_no ? fieldMap.reference_no.value : null,
      fieldMeta: fieldMap,
    };
  }

  function matchProfileFromImage(img, profiles) {
    img = normalizeSlipImage(img);
    profiles = profiles || [];
    if (!profiles.length) {
      return Promise.resolve({ profile: null, score: 0, provider: null, fullText: '' });
    }
    if (profiles.length === 1) {
      return Promise.resolve({
        profile: profiles[0],
        score: 1,
        provider: detectProvider(''),
        fullText: '',
      });
    }
    var size = imagePixelSize(img);
    var scale = size.w && size.w < 1000 ? (1000 / size.w) : 0.9;
    var c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(size.w * scale));
    c.height = Math.max(1, Math.round(size.h * scale));
    var mctx = c.getContext('2d');
    mctx.fillStyle = '#ffffff';
    mctx.fillRect(0, 0, c.width, c.height);
    mctx.drawImage(slipDrawTarget(img), 0, 0, c.width, c.height);
    enhanceCanvas(mctx, c, 'photo-fix');
    return ocrCanvas(c, null, { variant: 'match-light' }).then(function (ocr) {
      var match = matchProfile(profiles, ocr.text);
      return {
        profile: match.profile,
        score: match.score,
        provider: match.provider,
        fullText: ocr.text,
      };
    });
  }

  function extractWithProfile(img, profile, fullText, opts) {
    opts = opts || {};
    img = normalizeSlipImage(img);
    var useSmart = opts.smart !== false;
    var fieldRegions = {};
    (profile.fields || []).forEach(function (f) { fieldRegions[f.field_key] = f; });
    var keys = ['date', 'amount', 'reference_no'];

    return (fullText ? Promise.resolve(fullText) : getSlipFullTextForExtract(img)).then(function (resolvedText) {
      var fb = fullTextFallback(resolvedText);
      var ab = anchorFallback(resolvedText);

      function runKey(key) {
        var region = fieldRegions[key];
        if (!region) {
          return Promise.resolve({ key: key, result: mergeFieldResults(ab[key], fb[key], 0.5) });
        }
        var seed = useSmart
          ? seededFieldResult(key, ab, fb, resolvedText, key === 'amount' ? 0.68 : 0.62)
          : null;
        if (useSmart && shouldSkipZoneOcr(key, seed, resolvedText, region)) {
          ocrLog('extractWithProfile skip zone', { key: key, seed: seed.value, source: seed.source });
          return Promise.resolve({ key: key, result: seed });
        }
        return ocrRegionField(img, region, key, {
          fast: opts.fast,
          fullText: resolvedText,
        }).then(function (zoneRes) {
          if (key === 'amount') {
            var needLayout = !zoneRes || !zoneRes.value ||
              (zoneRes.confidence || 0) < 0.55 ||
              !validateAmountCandidate(zoneRes.value, resolvedText);
            if (useSmart && !needLayout) {
              return { key: key, result: reconcileAmountResult(zoneRes, resolvedText) };
            }
            return ocrProviderAmountFallback(img, resolvedText).then(function (layoutRes) {
              var mergedZone = zoneRes;
              if (layoutRes && layoutRes.value) {
                if (!mergedZone || !mergedZone.value ||
                    (layoutRes.confidence || 0) > (mergedZone.confidence || 0) + 0.05) {
                  mergedZone = layoutRes;
                } else if (mergedZone && mergedZone.value &&
                    !amountValuesClose(mergedZone.value, layoutRes.value) &&
                    (layoutRes.confidence || 0) >= (mergedZone.confidence || 0)) {
                  mergedZone = layoutRes;
                }
              }
              return {
                key: key,
                result: reconcileAmountResult(mergedZone, resolvedText),
              };
            });
          }
          if (zoneRes && zoneRes.value) return { key: key, result: zoneRes };
          if (seed && seed.value) return { key: key, result: seed };
          return {
            key: key,
            result: mergeFieldResults(zoneRes, mergeFieldResults(ab[key], fb[key], 0.5), 0.48),
          };
        });
      }

      var runAll = keys.reduce(function (chain, key) {
        return chain.then(function (rows) {
          return runKey(key).then(function (row) {
            rows.push(row);
            return rows;
          });
        });
      }, Promise.resolve([]));

      return runAll.then(function (rows) {
        var out = {};
        rows.forEach(function (row) { out[row.key] = row.result; });
        sanitizeFieldMap(out, resolvedText);
        var flat = flattenResults(out);
        flat.profileName = profile.name;
        flat.ocrText = resolvedText;
        return flat;
      });
    });
  }

  function extractGeneric(img, fullTextOptional) {
    img = normalizeSlipImage(img);
    var chain = fullTextOptional
      ? Promise.resolve(fullTextOptional)
      : getSlipFullTextForExtract(img);
    return chain.then(function (text) {
      return ocrProviderAmountFallback(img, text).then(function (layoutAmt) {
        var fb = fullTextFallback(text);
        var ab = anchorFallback(text);
        var amount = mergeFieldResults(layoutAmt, mergeFieldResults(ab.amount, fb.amount, 0.55), 0.52);
        amount = reconcileAmountResult(amount, text);
        var out = {
          date: mergeFieldResults(ab.date, fb.date, 0.5),
          amount: amount,
          reference_no: mergeFieldResults(ab.reference_no, fb.reference_no, 0.5),
        };
        sanitizeFieldMap(out, text);

        function finishGeneric() {
          var flat = flattenResults(out);
          flat.profileName = null;
          flat.ocrText = text;
          return flat;
        }

        if (out.reference_no && out.reference_no.value &&
            ((out.reference_no.confidence || 0) >= 0.62 || ocrModeIsFast())) {
          return finishGeneric();
        }
        return ocrHeaderReferenceScan(img).then(function (headerRef) {
          if (headerRef && headerRef.value) {
            out.reference_no = mergeFieldResults(headerRef, out.reference_no, 0.55);
            sanitizeFieldMap(out, text);
          }
          return finishGeneric();
        });
      });
    });
  }

  function extractFromSlip(file, profiles, options) {
    options = options || {};
    profiles = profiles || [];
    var useFast = options.fast !== false && !ocrModeIsAccurate();
    var preferredId = options.preferredProfileId || null;
    var t0 = (typeof performance !== 'undefined' && performance.now) ? performance.now() : 0;

    function finishExtract(data, label) {
      if (data && t0) {
        ocrLog(label || 'extractFromSlip', {
          ms: Math.round(performance.now() - t0),
          profile: data.profileName || null,
          quality: extractionQuality(data),
          score: data.matchScore,
          profiles: profiles.length,
        });
      }
      return data;
    }

    function runRankedExtract(img, fullText, ranked, tryOptions) {
      return tryBestProfileExtract(img, ranked, fullText, useFast, tryOptions || {}).then(function (data) {
        if (data && extractionQuality(data) > 0) {
          data.ocrText = fullText;
          data.img = img;
          return data;
        }
        if (!useFast) {
          return extractGeneric(img, fullText).then(function (generic) {
            generic.ocrText = fullText;
            generic.img = img;
            return generic;
          });
        }
        return extractWithProfile(img, ranked[0].profile, fullText, {
          fast: false,
          smart: true,
        }).then(function (slowData) {
          attachProfileMeta(slowData, ranked[0].profile, ranked[0].score, fullText, detectProvider(fullText), img);
          if (extractionQuality(slowData) > 0) {
            slowData.ocrText = fullText;
            slowData.img = img;
            return slowData;
          }
          return extractGeneric(img, fullText).then(function (generic) {
            generic.matchScore = ranked[0] ? ranked[0].score : 0;
            generic.provider = detectProvider(fullText) ? detectProvider(fullText).id : null;
            generic.ocrText = fullText;
            generic.img = img;
            return generic;
          });
        });
      });
    }

    var useZoneFirst = options.zoneFirst !== false;
    var zoneStrict = options.zoneStrict === true;
    var onProgress = typeof options.onProgress === 'function' ? options.onProgress : null;

    function resolvePreferred() {
      var preferred = findProfileById(profiles, preferredId);
      if (!preferred && profiles.length === 1) preferred = profiles[0];
      return preferred;
    }

    function packageProfileData(data, profile, score, fullText, slipImg) {
      attachProfileMeta(data, profile, score, fullText || data.ocrText || '', detectProvider(fullText || ''), slipImg);
      data.ocrText = fullText || data.ocrText || '';
      data.img = slipImg;
      return data;
    }

    function tryAlternateProfile(partialData, skipProfileId, fullText, ranked, slipImg) {
      var altList = selectProfileCandidates(ranked, { maxTry: 1 }).filter(function (c) {
        return c.profile.id !== skipProfileId;
      });
      if (!altList.length) return Promise.resolve(partialData);
      var alt = altList[0];
      return extractWithProfile(slipImg, alt.profile, fullText, {
        fast: useFast,
        smart: true,
      }).then(function (altData) {
        packageProfileData(altData, alt.profile, alt.score, fullText, slipImg);
        if (!partialData || extractionQuality(altData) >= extractionQuality(partialData)) {
          return altData;
        }
        return partialData;
      });
    }

    function finishProfileExtract(data, profile, score, fullText, ranked, label, slipImg) {
      packageProfileData(data, profile, score, fullText, slipImg);
      if (isGoodEnoughExtract(data)) {
        return finishExtract(data, label || 'extractFromSlip profile-ok');
      }
      return reinforceExtract(slipImg, profile, fullText, data).then(function (reinforced) {
        packageProfileData(reinforced, profile, score, fullText, slipImg);
        if (isGoodEnoughExtract(reinforced)) {
          return finishExtract(reinforced, (label || 'extract') + '-reinforced');
        }
        return tryAlternateProfile(reinforced, profile.id, fullText, ranked, slipImg).then(function (finalData) {
          return finishExtract(finalData, (label || 'extract') + '-alt');
        });
      });
    }

    function runFullExtract(slipImg, preferred) {
      return getSlipFullTextForExtract(slipImg).then(function (fullText) {
        var ranked = rankProfiles(profiles, fullText);
        if (preferred) {
          var prefRank = ranked.filter(function (r) { return r.profile.id === preferred.id; })[0];
          var prefScore = prefRank ? prefRank.score : 1;
          return extractWithProfile(slipImg, preferred, fullText, {
            fast: useFast,
            smart: true,
          }).then(function (data) {
            return finishProfileExtract(data, preferred, prefScore, fullText, ranked, 'extractFromSlip preferred', slipImg);
          });
        }
        return runRankedExtract(slipImg, fullText, ranked).then(function (data) {
          return finishExtract(data, 'extractFromSlip multi-profile');
        });
      });
    }

    // Sequential design gate (zone-strict): har design par pehle date zone check,
    // date na milay to next design; date milay to amount check, amount na milay
    // to next design; dono milein to usi design se reference utha kar finish.
    function runZoneStrictGate(slipImg, ordered) {
      ocrLog('extractFromSlip zone-strict gate', {
        designs: ordered.map(function (p) { return p.name; }),
      });
      var idx = 0;

      function tryNext() {
        if (idx >= ordered.length) {
          // Koi design gate pass nahi kar saka — pehle design par normal
          // zone-only read kar ke jo bhi mila woh de do.
          var pref = ordered[0];
          ocrLog('zone-strict gate: no design matched — fallback', { profile: pref.name });
          return extractZonesOnly(slipImg, pref, {
            fast: true,
            zoneOnly: true,
            onProgress: onProgress,
          }).then(function (zoneData) {
            packageProfileData(zoneData, pref, 1, '', slipImg);
            return finishExtract(zoneData, 'extractFromSlip zone-strict-fallback');
          });
        }
        var profile = ordered[idx++];
        var regions = profileRegionMap(profile);

        // Gate 1: date
        return ocrRegionField(slipImg, regions.date, 'date', {
          fast: true, zoneOnly: true, teachPreview: true, fullText: '',
        }).then(function (dateRes) {
          if (!dateRes || !dateRes.value) {
            ocrLog('zone-strict gate: date nahi mili — next design', { profile: profile.name });
            return tryNext();
          }
          // Gate 2: amount
          return ocrRegionField(slipImg, regions.amount, 'amount', {
            fast: true, zoneOnly: true, teachPreview: true, fullText: '',
          }).then(function (amtRes) {
            if (amtRes && amtRes.value) amtRes = reconcileAmountResult(amtRes, '');
            if (!amtRes || !amtRes.value) {
              ocrLog('zone-strict gate: amount nahi mila — next design', { profile: profile.name });
              return tryNext();
            }
            // Design matched — date + amount fill, phir isi design se reference
            if (onProgress) {
              onProgress({ key: 'date', value: dateRes.value, result: dateRes, profileName: profile.name });
              onProgress({ key: 'amount', value: amtRes.value, result: amtRes, profileName: profile.name });
            }
            var refPromise = regions.reference_no
              ? ocrRegionField(slipImg, regions.reference_no, 'reference_no', {
                  fast: true, zoneOnly: true, teachPreview: true, fullText: '',
                })
              : Promise.resolve(fieldResult(null, 0, 'none'));
            return refPromise.then(function (refRes) {
              refRes = refRes || fieldResult(null, 0, 'none');
              if (onProgress && refRes.value) {
                onProgress({ key: 'reference_no', value: refRes.value, result: refRes, profileName: profile.name });
              }
              var out = { date: dateRes, amount: amtRes, reference_no: refRes };
              var pseudo = [dateRes.value, amtRes.value, refRes.value].filter(Boolean).join('\n');
              sanitizeFieldMap(out, pseudo);
              var flat = flattenResults(out);
              flat.profileName = profile.name;
              flat.ocrText = pseudo;
              packageProfileData(flat, profile, 1, '', slipImg);
              return finishExtract(flat, 'extractFromSlip zone-strict-gate');
            });
          });
        });
      }

      return tryNext();
    }

    function runZoneFirst(slipImg, preferred) {
      ocrLog('extractFromSlip zone-first', { profile: preferred.name, strict: zoneStrict });
      return extractZonesOnly(slipImg, preferred, {
        fast: true,
        zoneOnly: zoneStrict,
        onProgress: onProgress,
      }).then(function (zoneData) {
        packageProfileData(zoneData, preferred, 1, '', slipImg);
        if (zoneStrict) {
          return finishExtract(zoneData, 'extractFromSlip zone-strict');
        }
        if (isCompleteExtract(zoneData)) {
          return finishExtract(zoneData, 'extractFromSlip zone-first');
        }
        return getSlipFullTextForExtract(slipImg).then(function (fullText) {
          zoneData.ocrText = fullText;
          return reinforceExtract(slipImg, preferred, fullText, zoneData).then(function (reinforced) {
            packageProfileData(reinforced, preferred, 1, fullText, slipImg);
            if (typeof onProgress === 'function' && reinforced.reference_no) {
              onProgress({
                key: 'reference_no',
                value: reinforced.reference_no,
                result: reinforced.fieldMeta && reinforced.fieldMeta.reference_no,
                profileName: preferred.name,
              });
            }
            if (isCompleteExtract(reinforced)) {
              return finishExtract(reinforced, 'extractFromSlip zone-reinforced');
            }
            var ranked = rankProfiles(profiles, fullText);
            return finishProfileExtract(reinforced, preferred, 1, fullText, ranked, 'extractFromSlip zone-fallback', slipImg);
          });
        });
      });
    }

    return Promise.all([prewarmWorker(), loadImageFromFile(file)]).then(function (parts) {
        var img = normalizeSlipImage(parts[1]);
        if (!profiles.length) {
          return getSlipFullTextForExtract(img).then(function (fullText) {
            return extractGeneric(img, fullText).then(function (data) {
              data.ocrText = fullText;
              data.img = img;
              return finishExtract(data, 'extractFromSlip generic');
            });
          });
        }

        var preferred = resolvePreferred();
        if (useZoneFirst && zoneStrict) {
          // Gate-eligible designs: jin mein date + amount dono zones hain.
          var gateList = profiles.filter(function (p) {
            var regions = profileRegionMap(p);
            return regions.date && regions.amount;
          });
          if (preferred) {
            gateList = gateList.filter(function (p) { return p.id !== preferred.id; });
            var prefRegions = profileRegionMap(preferred);
            if (prefRegions.date && prefRegions.amount) gateList.unshift(preferred);
          }
          if (gateList.length) {
            return runZoneStrictGate(img, gateList);
          }
        }
        var hasAnyZone = preferred && (preferred.fields || []).length > 0;
        if (useZoneFirst && preferred && (profileHasAllZones(preferred) || (zoneStrict && hasAnyZone))) {
          return runZoneFirst(img, preferred);
        }
        return runFullExtract(img, preferred);
    });
  }

  function previewRegions(img, regionsByKey, options) {
    options = options || {};
    img = normalizeSlipImage(img);
    var zoneOnly = options.zoneOnly !== false;
    ocrLog('previewRegions start', { keys: Object.keys(regionsByKey || {}), zoneOnly: zoneOnly });

    function runKeys(fullText) {
      var keys = ['date', 'amount', 'reference_no'];
      var chain = Promise.resolve([]);
      keys.forEach(function (key) {
        chain = chain.then(function (rows) {
          var region = regionsByKey ? regionsByKey[key] : null;
          if (region) logRegionMapping('previewRegions:' + key, img, region);
          return previewRegionFieldWithFallback(img, key, region, fullText, { zoneOnly: zoneOnly })
            .then(function (result) {
              rows.push({ key: key, result: result });
              return rows;
            });
        });
      });
      return chain.then(function (rows) {
        var out = {};
        rows.forEach(function (row) { out[row.key] = row.result; });
        sanitizeFieldMap(out, fullText || '');
        var flat = flattenResults(out);
        flat.ocrText = fullText || '';
        ocrLog('previewRegions done', flat);
        return flat;
      });
    }

    return prewarmWorker().then(function () {
      if (zoneOnly) {
        return runKeys('');
      }
      return ocrFullImageCached(img).then(runKeys);
    });
  }

  function previewFieldRegion(img, fieldKey, region, options) {
    options = options || {};
    img = normalizeSlipImage(img);
    var zoneOnly = options.zoneOnly !== false;
    ocrLog('previewFieldRegion start', { field: fieldKey, region: region, zoneOnly: zoneOnly });
    if (region) logRegionMapping('previewFieldRegion:' + fieldKey, img, region);
    return prewarmWorker().then(function () {
      if (zoneOnly) {
        return previewRegionFieldWithFallback(img, fieldKey, region, '', { zoneOnly: true });
      }
      return ocrFullImageCached(img).then(function (fullText) {
        return previewRegionFieldWithFallback(img, fieldKey, region, fullText);
      });
    });
  }

  function buildFingerprintFromFile(file) {
    return prewarmWorker().then(function () {
      return loadImageFromFile(file).then(function (img) {
        return ocrFullImage(img).then(function (text) {
          return {
            ocrText: text,
            keywords: buildFingerprint(text),
            img: img,
          };
        });
      });
    });
  }

  function buildFingerprintFromImage(img) {
    return prewarmWorker().then(function () {
      return ocrFullImage(img).then(function (text) {
        return {
          ocrText: text,
          keywords: buildFingerprint(text),
        };
      });
    });
  }

  function cacheProfiles(profiles) {
    try {
      global.localStorage.setItem('ws_slip_profiles_v1', JSON.stringify(profiles || []));
    } catch (e) { /* ignore */ }
  }

  function readCachedProfiles() {
    try {
      var raw = global.localStorage.getItem('ws_slip_profiles_v1');
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : null;
    } catch (e) {
      return null;
    }
  }

  function normalizeFieldValue(fieldKey, val) {
    var v = String(val || '').trim();
    if (!v) return '';
    if (fieldKey === 'amount') {
      var num = parseFloat(v.replace(/,/g, ''));
      if (!isFinite(num)) return v;
      return num % 1 === 0 ? String(Math.round(num)) : num.toFixed(2);
    }
    if (fieldKey === 'reference_no') return v.replace(/\s/g, '').toUpperCase();
    if (fieldKey === 'date') {
      var parsed = parseDateFromText(v);
      return parsed || v;
    }
    return v;
  }

  function fieldValuesMatch(fieldKey, a, b) {
    return normalizeFieldValue(fieldKey, a) === normalizeFieldValue(fieldKey, b);
  }

  function scoreTextForField(fieldKey, text, targetNorm) {
    if (!text || !targetNorm) return 0;
    if (fieldKey === 'amount') {
      var amt = parseAmountFromText(text);
      if (amt && normalizeFieldValue('amount', amt) === targetNorm) return 1;
      return stringSimilarity(normalizeFieldValue('amount', parseAmountFromText(text) || text), targetNorm);
    }
    if (fieldKey === 'date') {
      var dt = parseDateFromText(text);
      if (dt && dt === targetNorm) return 1;
      return stringSimilarity(parseDateFromText(text) || text, targetNorm);
    }
    if (fieldKey === 'reference_no') {
      var ref = parseReferenceFromText(text) || String(text).replace(/\s/g, '').toUpperCase();
      if (ref === targetNorm) return 1;
      return stringSimilarity(ref, targetNorm);
    }
    return 0;
  }

  function bboxToRegion(bbox, imgW, imgH, padRatio) {
    padRatio = padRatio || 0.18;
    var x0 = bbox.x0;
    var y0 = bbox.y0;
    var x1 = bbox.x1;
    var y1 = bbox.y1;
    var pw = Math.max(4, (x1 - x0) * padRatio);
    var ph = Math.max(4, (y1 - y0) * padRatio);
    x0 = Math.max(0, x0 - pw);
    y0 = Math.max(0, y0 - ph);
    x1 = Math.min(imgW, x1 + pw);
    y1 = Math.min(imgH, y1 + ph);
    return {
      region_x: Math.max(0, (x0 / imgW) * 100),
      region_y: Math.max(0, (y0 / imgH) * 100),
      region_w: Math.max(1, ((x1 - x0) / imgW) * 100),
      region_h: Math.max(1, ((y1 - y0) / imgH) * 100),
    };
  }

  function mergeBBoxList(items) {
    if (!items.length) return null;
    var x0 = items[0].bbox.x0;
    var y0 = items[0].bbox.y0;
    var x1 = items[0].bbox.x1;
    var y1 = items[0].bbox.y1;
    items.forEach(function (it) {
      x0 = Math.min(x0, it.bbox.x0);
      y0 = Math.min(y0, it.bbox.y0);
      x1 = Math.max(x1, it.bbox.x1);
      y1 = Math.max(y1, it.bbox.y1);
    });
    return { x0: x0, y0: y0, x1: x1, y1: y1 };
  }

  function findRegionForCorrectedValue(img, fieldKey, correctedValue, profile) {
    var size = imagePixelSize(img);
    var targetNorm = normalizeFieldValue(fieldKey, correctedValue);
    if (!targetNorm || !size.w || !size.h) {
      return Promise.resolve(null);
    }
    var existing = null;
    (profile && profile.fields || []).forEach(function (f) {
      if (f.field_key === fieldKey) existing = f;
    });
    var scale = size.w < 1200 ? (1200 / size.w) : 1;
    var canvas = document.createElement('canvas');
    canvas.width = Math.round(size.w * scale);
    canvas.height = Math.round(size.h * scale);
    var lctx = canvas.getContext('2d');
    lctx.fillStyle = '#ffffff';
    lctx.fillRect(0, 0, canvas.width, canvas.height);
    lctx.drawImage(slipDrawTarget(normalizeSlipImage(img)), 0, 0, canvas.width, canvas.height);
    enhanceCanvas(lctx, canvas, 'photo-fix');

    return ensureTesseract().then(function (Tesseract) {
      return Tesseract.recognize(canvas, 'eng', tesseractWorkerOptions({
        preserve_interword_spaces: '1',
      })).then(function (r) {
        var words = (r && r.data && r.data.words) ? r.data.words : [];
        var lines = (r && r.data && r.data.lines) ? r.data.lines : [];
        var best = null;
        var bestScore = 0.78;

        function consider(items, maxLen) {
          maxLen = maxLen || 4;
          for (var i = 0; i < items.length; i++) {
            for (var len = 1; len <= maxLen && i + len <= items.length; len++) {
              var chunk = items.slice(i, i + len);
              var text = chunk.map(function (w) { return w.text; }).join(' ');
              var score = scoreTextForField(fieldKey, text, targetNorm);
              if (score >= bestScore) {
                bestScore = score;
                var bb = mergeBBoxList(chunk);
                if (bb) {
                  best = bboxToRegion(
                    { x0: bb.x0 / scale, y0: bb.y0 / scale, x1: bb.x1 / scale, y1: bb.y1 / scale },
                    size.w,
                    size.h
                  );
                }
              }
            }
          }
        }

        consider(words, 5);
        if (!best) consider(lines, 2);

        if (!best && existing) {
          var ex = bboxToRegion({
            x0: size.w * (existing.region_x / 100),
            y0: size.h * (existing.region_y / 100),
            x1: size.w * ((existing.region_x + existing.region_w) / 100),
            y1: size.h * ((existing.region_y + existing.region_h) / 100),
          }, size.w, size.h, 0.35);
          best = {
            region_x: Math.max(0, ex.region_x - 5),
            region_y: Math.max(0, ex.region_y - 3),
            region_w: Math.min(100, ex.region_w + 10),
            region_h: Math.min(100, ex.region_h + 6),
          };
        }
        return best;
      });
    }).catch(function () { return null; });
  }

  /**
   * Learn from user correction: locate corrected value on slip image and return updated region.
   */
  function learnFieldCorrection(img, profile, fieldKey, correctedValue, ocrTextOptional) {
    if (!img || !profile || !fieldKey || !correctedValue) {
      return Promise.resolve(null);
    }
    return findRegionForCorrectedValue(img, fieldKey, correctedValue, profile).then(function (region) {
      if (!region) return null;
      var keywords = ocrTextOptional ? buildFingerprint(ocrTextOptional).slice(0, 12) : [];
      return {
        field_key: fieldKey,
        region: region,
        keywords: keywords,
      };
    });
  }

  global.WorkspaceSlipTemplate = {
    VERSION: '1.10.0',
    FIELD_LABELS: FIELD_LABELS,
    FIELD_COLORS: FIELD_COLORS,
    FIELD_TINTS: FIELD_TINTS,
    ensureTesseract: ensureTesseract,
    prewarmWorker: prewarmWorker,
    prepareOcrEngine: prepareOcrEngine,
    getLastOcrEngineError: getLastOcrEngineError,
    tesseractWorkerOptions: tesseractWorkerOptions,
    getWorker: getWorker,
    buildFingerprint: buildFingerprint,
    buildFingerprintFromFile: buildFingerprintFromFile,
    buildFingerprintFromImage: buildFingerprintFromImage,
    loadImageFromFile: loadImageFromFile,
    extractFromSlip: extractFromSlip,
    extractGeneric: extractGeneric,
    previewRegions: previewRegions,
    previewFieldRegion: previewFieldRegion,
    ocrRegionField: ocrRegionField,
    regionToPixelRect: regionToPixelRect,
    logRegionMapping: logRegionMapping,
    makeRegionCanvas: makeRegionCanvas,
    parseDateFromText: parseDateFromText,
    parseAmountFromText: parseAmountFromText,
    parseReferenceFromText: parseReferenceFromText,
    parseReferenceFromZone: parseReferenceFromZone,
    rankProfiles: rankProfiles,
    extractionQuality: extractionQuality,
    cacheProfiles: cacheProfiles,
    readCachedProfiles: readCachedProfiles,
    normalizeFieldValue: normalizeFieldValue,
    fieldValuesMatch: fieldValuesMatch,
    learnFieldCorrection: learnFieldCorrection,
    LOW_CONFIDENCE: 0.58,
    validateAmountCandidate: validateAmountCandidate,
    parseProviderAmount: parseProviderAmount,
    normalizeSlipImage: normalizeSlipImage,
    ocrConfig: ocrConfig,
    enhanceCanvas: enhanceCanvas,
  };
})(window);
