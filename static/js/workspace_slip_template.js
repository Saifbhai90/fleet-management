/**
 * Template-Matching Zonal OCR for Workspace Transfer slips (Tesseract.js, no AI).
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

  var _tesseractWarm = null;
  var _ocrWorker = null;
  var _ocrWorkerReady = null;
  var _ocrJobChain = Promise.resolve();
  var _lastOcrEngineError = null;
  var TESSERACT_VERSION = '5.1.1';
  var FULL_OCR_WHITELIST = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .:/-#@$%&*()+_ RSrsPKRpkr,';

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

  function fixOcrTextForDate(text) {
    var t = String(text || '').replace(/\s+/g, ' ').replace(/—/g, '-').trim();
    t = t.split('|')[0].split(/\s+at\s+/i)[0].trim();
    t = t.replace(/^(?:date\s*(?:&\s*time)?|on|time)\s*[:\-]?\s*/i, '');
    t = t.replace(/\b([OolI|])(?=\d)/g, '0');
    t = t.replace(/(\d)[Oo](\d)/g, '$10$2');
    t = t.replace(/\b(\d{1,2})\s+([A-Za-z0-9]{2,9})\s+(\d{2,4})\b/g, function (_, d, mon, y) {
      return d + ' ' + fuzzyFixMonthToken(mon) + ' ' + y;
    });
    return t.trim();
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
        .replace(/[lI|]/g, '1')
        .replace(/[Ss$]/g, '5')
        .replace(/[Bb]/g, '8')
        .replace(/[Zz]/g, '2')
        .replace(/[Gg]/g, '6')
        .replace(/[^\w#-]/g, ' ')
        .replace(/\s+/g, '')
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
    var t = fixOcrTextForDate(text);
    var patterns = [
      /\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})\b/g,
      /\b(\d{4})[\/\-.](\d{1,2})[\/\-.](\d{1,2})\b/g,
      /\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b/gi,
      /\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{2})\b/gi,
    ];
    var months = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
    var best = null;
    var bestScore = -1;
    var m;
    patterns.forEach(function (re, idx) {
      re.lastIndex = 0;
      while ((m = re.exec(t)) !== null) {
        var d, mo, y, score = 80;
        if (idx === 2 || idx === 3) {
          d = parseInt(m[1], 10);
          mo = months[String(m[2]).slice(0, 3).toLowerCase()] || 0;
          y = parseInt(m[3], 10);
          score += 6;
          if (idx === 3 && y < 100) y += 2000;
        } else if (idx === 0) {
          d = parseInt(m[1], 10);
          mo = parseInt(m[2], 10);
          y = parseInt(m[3], 10);
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

  function parseAmountFromText(text) {
    var t = fixOcrText(text, 'amount');
    var candidates = [];
    var reRs = /(?:RS\.?|PKR\.?|AMOUNT\s*PAID|AMOUNT|TOTAL|SENT|TRANSFERRED)\s*[:\-]?\s*([\d,]+(?:\.\d{1,2})?)/gi;
    var m;
    while ((m = reRs.exec(t)) !== null) {
      candidates.push({ val: m[1], score: 100 });
    }
    var reNum = /\b([\d]{1,3}(?:,\d{3})+(?:\.\d{1,2})?)\b/g;
    while ((m = reNum.exec(t)) !== null) {
      candidates.push({ val: m[1], score: 75 });
    }
    var rePlain = /\b(\d{3,}(?:\.\d{1,2})?)\b/g;
    while ((m = rePlain.exec(t)) !== null) {
      candidates.push({ val: m[1], score: 55 });
    }
    if (!candidates.length) {
      var digits = t.replace(/[^\d.]/g, '');
      if (digits.length >= 3) candidates.push({ val: digits, score: 40 });
    }
    if (!candidates.length) return null;
    candidates.sort(function (a, b) { return b.score - a.score; });
    var raw = String(candidates[0].val).replace(/,/g, '').replace(/\.(?=.*\.)/g, '');
    var num = parseFloat(raw);
    if (!isFinite(num) || num <= 0) return null;
    return num % 1 === 0 ? String(Math.round(num)) : num.toFixed(2);
  }

  var REF_LABEL_RE = /(?:TID|TXN|TRANSACTION\s*ID|REFERENCE\s*NO?|REF\s*NO?|TRX\s*ID|RAAST\s*ID|TRANSACTION|REFERENCE|SUCCESSFUL|TRANSFER)\s*/gi;
  var REF_STOPWORDS = {
    TRANSACTION: 1, REFERENCE: 1, SUCCESSFUL: 1, TRANSFER: 1, SUCCESS: 1, PAYMENT: 1, AMOUNT: 1,
  };

  /** Zonal crop parser — prefer pure digit runs (e.g. JazzCash 66556000), not label garbage. */
  function parseReferenceFromZone(text) {
    var raw = String(text || '');
    if (!raw.trim()) return null;
    var t = fixOcrText(raw, 'reference_no');
    t = t.replace(REF_LABEL_RE, ' ').replace(/\bID\b\s*[:\-#]?\s*/gi, ' ');
    t = t.replace(/[#:\-]/g, ' ').replace(/\s+/g, ' ').trim();

    var candidates = [];
    function addDigitRuns(source, baseScore) {
      var re = /\d{6,}/g;
      var m;
      while ((m = re.exec(source)) !== null) {
        candidates.push({ val: m[0], score: baseScore + m[0].length * 5 });
      }
    }
    addDigitRuns(t, 140);
    addDigitRuns(fixOcrText(raw, 'reference_no'), 120);

    var alnumRe = /\b[A-Z0-9]{6,}\b/gi;
    var m;
    while ((m = alnumRe.exec(t)) !== null) {
      var val = String(m[0] || '').toUpperCase();
      if (val.length < 6 || /^\d+$/.test(val)) continue;
      if (REF_STOPWORDS[val]) continue;
      if (!/[A-Z]/.test(val) || !/[0-9]/.test(val)) continue;
      candidates.push({ val: val, score: 55 + val.length * 2 });
    }

    if (!candidates.length) return null;
    candidates.sort(function (a, b) { return b.score - a.score; });
    return candidates[0].val;
  }

  function parseReferenceFromText(text) {
    var zoneVal = parseReferenceFromZone(text);
    if (zoneVal && String(text || '').length < 160) return zoneVal;

    var t = fixOcrText(text, 'reference_no');
    var patterns = [
      /(?:TID|TXN|TRANSACTION\s*ID|REFERENCE\s*NO?|REF\s*NO?|TRX\s*ID|RAAST\s*ID)\s*[:\-#]?\s*([0-9]{6,})/gi,
      /\b([0-9]{8,})\b/g,
      /\b([0-9]{6,})\b/g,
      /(?:TID|TXN|TRANSACTION\s*ID|REFERENCE\s*NO?|REF\s*NO?|TRX\s*ID|RAAST\s*ID)\s*[:\-#]?\s*([A-Z0-9]{6,})/gi,
      /\b([A-Z0-9]{8,})\b/g,
    ];
    var best = null;
    var bestScore = -1;
    patterns.forEach(function (re, idx) {
      re.lastIndex = 0;
      var m;
      while ((m = re.exec(t)) !== null) {
        var val = (m[1] || '').replace(/\s/g, '');
        if (val.length < 6) continue;
        if (REF_STOPWORDS[val]) continue;
        var score = 96 - idx * 11 + Math.min(val.length, 20);
        if (/^\d+$/.test(val)) score += 35;
        if (/^\d+$/.test(val) && val.length >= 10) score += 10;
        if (!/^\d+$/.test(val) && !/[A-Z]/.test(val)) score -= 20;
        if (score > bestScore) {
          bestScore = score;
          best = val;
        }
      }
    });
    return best || zoneVal;
  }

  function fieldValueRank(fieldKey, val, ocrConf) {
    if (!val) return 0;
    var rank = (ocrConf || 0.5) * 100;
    if (fieldKey === 'reference_no') {
      if (/^\d+$/.test(val)) rank += 90;
      else if (/[A-Z]/.test(val) && /[0-9]/.test(val)) rank += 25;
      else rank -= 30;
      rank += Math.min(val.length, 18) * 2;
    } else if (fieldKey === 'amount') {
      rank += 20;
    } else if (fieldKey === 'date') {
      if (/^\d{2}-\d{2}-\d{4}$/.test(val)) rank += 140;
      else if (/^\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}$/.test(val)) rank += 100;
      else rank -= 50;
    }
    return rank;
  }

  function fieldOcrVariants(fieldKey, fast) {
    if (fieldKey === 'date') {
      if (fast) {
        return [{ scale: 3.0, mode: 'normal', variant: 'date-fast', psm: '7', padPct: 0.8 }];
      }
      return [
        { scale: 3.2, mode: 'normal', variant: 'date-normal-3.2', psm: '7', padPct: 0.8 },
        { scale: 3.0, mode: 'gray-boost', variant: 'date-gray-3.0', psm: '7', padPct: 0.8 },
        { scale: 2.8, mode: 'normal', variant: 'date-normal-2.8', psm: '8', padPct: 1 },
        { scale: 3.4, mode: 'gray-boost', noWhitelist: true, variant: 'date-nowl-3.4', psm: '7', padPct: 0.6 },
      ];
    }
    if (fast) {
      if (fieldKey === 'reference_no') {
        return [{ scale: 2.8, mode: 'gray-boost', variant: 'ref-fast', digitsOnly: true, psm: '7', padPct: 0.8 }];
      }
      return [{ scale: 2.4, mode: 'gray-boost', variant: 'fast', padPct: 1.5 }];
    }
    if (fieldKey === 'reference_no') {
      return [
        { scale: 3.2, mode: 'gray-boost', variant: 'ref-digits-3.2', digitsOnly: true, psm: '7', padPct: 0.8 },
        { scale: 2.8, mode: 'gray-boost', variant: 'ref-digits-2.8', digitsOnly: true, psm: '8', padPct: 0.8 },
        { scale: 2.4, mode: 'normal', variant: 'ref-digits-2.4', digitsOnly: true, psm: '7', padPct: 1 },
        { scale: 3.0, mode: 'gray-boost', variant: 'ref-mixed-3.0', psm: '7', padPct: 1 },
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
    var margin = typeof options.margin === 'number' ? options.margin : 0.16;
    var maxTry = typeof options.maxTry === 'number' ? options.maxTry : 4;
    if (!ranked || !ranked.length) return [];
    var filtered = ranked.filter(function (r) { return r.score >= minScore; });
    if (!filtered.length) filtered = ranked.slice(0, 1);
    var top = filtered[0].score;
    var out = [filtered[0]];
    for (var i = 1; i < filtered.length && out.length < maxTry; i++) {
      if (top - filtered[i].score <= margin) out.push(filtered[i]);
      else break;
    }
    if (out.length === 1 && ranked.length > 1 && ranked[1].score >= minScore) {
      out.push(ranked[1]);
    }
    return out;
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

  function tryProfilesExtract(img, candidates, fullText, useFast) {
    if (!candidates || !candidates.length) return Promise.resolve(null);
    return Promise.all(candidates.map(function (c) {
      return extractWithProfile(img, c.profile, fullText, {
        fast: useFast,
        parallel: true,
      }).then(function (data) {
        attachProfileMeta(data, c.profile, c.score, fullText, detectProvider(fullText), img);
        data._quality = extractionQuality(data);
        return data;
      });
    })).then(function (results) {
      results.sort(function (a, b) {
        if (b._quality !== a._quality) return b._quality - a._quality;
        return (b.matchScore || 0) - (a.matchScore || 0);
      });
      return results[0] || null;
    });
  }

  function tryBestProfileExtract(img, ranked, fullText, useFast) {
    var candidates = selectProfileCandidates(ranked);
    return tryProfilesExtract(img, candidates, fullText, useFast).then(function (best) {
      if (best && extractionQuality(best) > 0) return best;
      if (useFast) {
        var retry = ranked.slice(0, Math.min(3, ranked.length));
        return tryProfilesExtract(img, retry, fullText, false);
      }
      return best;
    });
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

  function enhanceCanvas(ctx, canvas, mode) {
    if (mode !== 'gray-boost') return;
    var id = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var d = id.data;
    for (var i = 0; i < d.length; i += 4) {
      var g = (0.299 * d[i]) + (0.587 * d[i + 1]) + (0.114 * d[i + 2]);
      g = g > 150 ? 255 : (g < 70 ? 0 : Math.min(255, g * 1.28));
      d[i] = d[i + 1] = d[i + 2] = g;
    }
    ctx.putImageData(id, 0, 0);
  }

  /** Regions stored as 0–100 % of natural image width/height (resolution independent). */
  function imagePixelSize(img) {
    return {
      w: img.naturalWidth || img.width || 0,
      h: img.naturalHeight || img.height || 0,
    };
  }

  function ocrDebugEnabled() {
    return global.__wsSlipOcrDebug !== false;
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
  function regionToPixelRect(img, region, padPct) {
    var size = imagePixelSize(img);
    if (!size.w || !size.h) return null;
    region = padRegionPercent(region, typeof padPct === 'number' ? padPct : 2);
    var rx = Math.max(0, Math.floor(size.w * (region.region_x || 0) / 100));
    var ry = Math.max(0, Math.floor(size.h * (region.region_y || 0) / 100));
    var rw = Math.max(1, Math.floor(size.w * (region.region_w || 10) / 100));
    var rh = Math.max(1, Math.floor(size.h * (region.region_h || 10) / 100));
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

  function padRegionPercent(region, padPct) {
    padPct = typeof padPct === 'number' ? padPct : 2.5;
    var x = Math.max(0, (region.region_x || 0) - padPct);
    var y = Math.max(0, (region.region_y || 0) - padPct);
    var w = Math.min(100 - x, (region.region_w || 10) + padPct * 2);
    var h = Math.min(100 - y, (region.region_h || 10) + padPct * 2);
    return { region_x: x, region_y: y, region_w: w, region_h: h };
  }

  function makeRegionCanvas(img, region, scale, mode, padPct) {
    var px = regionToPixelRect(img, region, typeof padPct === 'number' ? padPct : 2);
    if (!px) {
      ocrLog('makeRegionCanvas: missing image pixels', { region: region });
      var c0 = document.createElement('canvas');
      c0.width = c0.height = 1;
      return c0;
    }
    var c = document.createElement('canvas');
    var targetW = Math.max(48, Math.round(px.w * scale));
    var targetH = Math.max(24, Math.round(px.h * scale));
    c.width = targetW;
    c.height = targetH;
    var ctx = c.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.imageSmoothingEnabled = true;
    try {
      ctx.drawImage(img, px.x, px.y, px.w, px.h, 0, 0, c.width, c.height);
    } catch (drawErr) {
      ocrLog('makeRegionCanvas: drawImage failed', {
        error: drawErr && drawErr.message ? drawErr.message : drawErr,
        crop: px,
        imgComplete: !!img.complete,
        imgSrc: img.src ? String(img.src).slice(0, 80) : '',
      });
    }
    enhanceCanvas(ctx, c, mode);
    ocrLog('makeRegionCanvas', {
      mode: mode,
      scale: scale,
      crop: { x: px.x, y: px.y, w: px.w, h: px.h },
      canvas: { w: c.width, h: c.height },
      natural: { w: px.naturalW, h: px.naturalH },
      regionPct: px.region,
    });
    return c;
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
      var cleaned = t.replace(/[^\d.,]/g, '').replace(/,/g, '');
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

  function ocrRegionField(img, region, fieldKey, opts) {
    opts = opts || {};
    ocrLog('ocrRegionField start', {
      field: fieldKey,
      fast: !!opts.fast,
      region: region,
      pixels: regionToPixelRect(img, region, 0),
    });
    var variants = fieldOcrVariants(fieldKey, !!opts.fast);
    var best = fieldResult(null, 0, 'zone');
    var bestRank = 0;
    var chain = Promise.resolve();
    variants.forEach(function (v) {
      chain = chain.then(function () {
        if (best.value && bestRank >= 175) return;
        var canvas = makeRegionCanvas(img, region, v.scale, v.mode, v.padPct);
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

  function fullTextFallback(fullText) {
    return {
      date: fieldResult(parseDateFromText(fullText), 0.62, 'full'),
      amount: fieldResult(parseAmountFromText(fullText), 0.6, 'full'),
      reference_no: fieldResult(parseReferenceFromText(fullText), 0.58, 'full'),
    };
  }

  function anchorFallback(fullText) {
    return {
      date: fieldResult(parseNearAnchor(fullText, ['DATE', 'ON', 'TIME'], parseDateFromText), 0.68, 'anchor'),
      amount: fieldResult(parseNearAnchor(fullText, ['AMOUNT', 'PKR', 'RS', 'SENT', 'PAID'], parseAmountFromText), 0.68, 'anchor'),
      reference_no: fieldResult(parseNearAnchor(fullText, ['TID', 'TRANSACTION', 'REFERENCE', 'RAAST', 'TRX'], parseReferenceFromText), 0.66, 'anchor'),
    };
  }

  function ocrFullImage(img) {
    var canvases = [];
    var size = imagePixelSize(img);
    var fullScale = size.w && size.w < 1600 ? (1600 / size.w) : 1.1;
    var c1 = document.createElement('canvas');
    c1.width = Math.round(size.w * fullScale);
    c1.height = Math.round(size.h * fullScale);
    c1.getContext('2d').drawImage(img, 0, 0, c1.width, c1.height);
    canvases.push(c1);
    canvases.push(makeRegionCanvas(img, { region_x: 0, region_y: 40, region_w: 100, region_h: 60 }, 1.9, 'gray-boost'));
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
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
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
    var fieldMap = {};
    (profile.fields || []).forEach(function (f) { fieldMap[f.field_key] = f; });
    var keys = ['date', 'amount', 'reference_no'];
    var fb = fullText ? fullTextFallback(fullText) : null;
    var ab = fullText ? anchorFallback(fullText) : null;

    function runKey(key) {
      var region = fieldMap[key];
      if (!region) {
        if (opts.fast || !fullText) {
          return Promise.resolve({ key: key, result: fieldResult(null, 0, 'none') });
        }
        return Promise.resolve({ key: key, result: mergeFieldResults(fb[key], ab[key], 0.5) });
      }
      return ocrRegionField(img, region, key, { fast: opts.fast }).then(function (zoneRes) {
        if (zoneRes && zoneRes.value) return { key: key, result: zoneRes };
        if (opts.fast || !fullText) return { key: key, result: zoneRes };
        return {
          key: key,
          result: mergeFieldResults(zoneRes, mergeFieldResults(ab[key], fb[key], 0.5), 0.48),
        };
      });
    }

    var runAll = opts.parallel
      ? Promise.all(keys.map(runKey))
      : keys.reduce(function (chain, key) {
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
      var flat = flattenResults(out);
      flat.profileName = profile.name;
      return flat;
    });
  }

  function extractGeneric(img, fullTextOptional) {
    var chain = fullTextOptional
      ? Promise.resolve(fullTextOptional)
      : ocrFullImage(img);
    return chain.then(function (text) {
      var fb = fullTextFallback(text);
      var ab = anchorFallback(text);
      var out = {
        date: mergeFieldResults(ab.date, fb.date, 0.5),
        amount: mergeFieldResults(ab.amount, fb.amount, 0.5),
        reference_no: mergeFieldResults(ab.reference_no, fb.reference_no, 0.5),
      };
      var flat = flattenResults(out);
      flat.profileName = null;
      flat.ocrText = text;
      return flat;
    });
  }

  function extractFromSlip(file, profiles, options) {
    options = options || {};
    profiles = profiles || [];
    var useFast = options.fast !== false;
    var t0 = (typeof performance !== 'undefined' && performance.now) ? performance.now() : 0;
    return prewarmWorker().then(function () {
      return loadImageFromFile(file).then(function (img) {
        if (profiles.length === 1) {
          return extractWithProfile(img, profiles[0], '', {
            fast: useFast,
            parallel: true,
          }).then(function (data) {
            attachProfileMeta(data, profiles[0], 1, '', detectProvider(''), img);
            if (t0) {
              ocrLog('extractFromSlip single-profile', {
                ms: Math.round(performance.now() - t0),
                profile: profiles[0].name,
              });
            }
            return data;
          });
        }
        if (!profiles.length) {
          return ocrFullImage(img).then(function (fullText) {
            return extractGeneric(img, fullText).then(function (data) {
              data.ocrText = fullText;
              data.img = img;
              return data;
            });
          });
        }

        function finishExtract(data, label) {
          if (data && t0) {
            ocrLog(label || 'extractFromSlip', {
              ms: Math.round(performance.now() - t0),
              profile: data.profileName || null,
              quality: extractionQuality(data),
              score: data.matchScore,
            });
          }
          return data;
        }

        return matchProfileFromImage(img, profiles).then(function (match) {
          var fullText = match.fullText || '';
          var ranked = rankProfiles(profiles, fullText);
          return tryBestProfileExtract(img, ranked, fullText, useFast).then(function (data) {
            if (data && extractionQuality(data) > 0) {
              return finishExtract(data, 'extractFromSlip matched');
            }
            return ocrFullImage(img).then(function (fullText2) {
              var ranked2 = rankProfiles(profiles, fullText2);
              return tryBestProfileExtract(img, ranked2, fullText2, false).then(function (data2) {
                if (data2 && extractionQuality(data2) > 0) {
                  data2.ocrText = fullText2;
                  data2.img = img;
                  return finishExtract(data2, 'extractFromSlip full-ocr');
                }
                var top = ranked2[0];
                if (top && top.score >= 0.22) {
                  return extractWithProfile(img, top.profile, fullText2, {
                    fast: false,
                    parallel: true,
                  }).then(function (data3) {
                    attachProfileMeta(data3, top.profile, top.score, fullText2, detectProvider(fullText2), img);
                    if (extractionQuality(data3) > 0) {
                      return finishExtract(data3, 'extractFromSlip top-score');
                    }
                    return extractGeneric(img, fullText2).then(function (generic) {
                      generic.matchScore = top.score;
                      generic.provider = detectProvider(fullText2) ? detectProvider(fullText2).id : null;
                      generic.ocrText = fullText2;
                      generic.img = img;
                      return generic;
                    });
                  });
                }
                return extractGeneric(img, fullText2).then(function (generic) {
                  generic.matchScore = top ? top.score : 0;
                  generic.provider = detectProvider(fullText2) ? detectProvider(fullText2).id : null;
                  generic.ocrText = fullText2;
                  generic.img = img;
                  return generic;
                });
              });
            });
          });
        });
      });
    });
  }

  function previewRegions(img, regionsByKey) {
    ocrLog('previewRegions start', { keys: Object.keys(regionsByKey || {}) });
    return prewarmWorker().then(function () {
      var keys = ['date', 'amount', 'reference_no'];
      return Promise.all(keys.map(function (key) {
        var region = regionsByKey[key];
        if (!region) {
          return Promise.resolve({ key: key, result: fieldResult(null, 0, 'none') });
        }
        logRegionMapping('previewRegions:' + key, img, region);
        return ocrRegionField(img, region, key).then(function (res) {
          return { key: key, result: res };
        });
      })).then(function (rows) {
        var out = {};
        rows.forEach(function (row) { out[row.key] = row.result; });
        var flat = {
          date: out.date ? out.date.value : null,
          amount: out.amount ? out.amount.value : null,
          reference_no: out.reference_no ? out.reference_no.value : null,
          fieldMeta: out,
        };
        ocrLog('previewRegions done', flat);
        return flat;
      });
    });
  }

  function previewFieldRegion(img, fieldKey, region) {
    ocrLog('previewFieldRegion start', { field: fieldKey, region: region });
    logRegionMapping('previewFieldRegion:' + fieldKey, img, region);
    return prewarmWorker().then(function () {
      return ocrRegionField(img, region, fieldKey);
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
    canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);

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
    VERSION: '1.4.1',
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
    LOW_CONFIDENCE: 0.52,
  };
})(window);
