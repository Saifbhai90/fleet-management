/**
 * Workspace Slip OCR v2 — Master Parser (anchor-based Hunter).
 * Bank-agnostic: PKR/Rs amounts, all date formats, TID/Ref#/Reference Number#.
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr;
  if (!Ws) return;

  var Parser = {};
  Ws.Parser = Parser;

  var MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
  var MONTH_FIX = {
    JUN: 'JUN', JUL: 'JUL', JAN: 'JAN', FEB: 'FEB', MAR: 'MAR', APR: 'APR', MAY: 'MAY',
    AUG: 'AUG', SEP: 'SEP', OCT: 'OCT', NOV: 'NOV', DEC: 'DEC', '1UN': 'JUN', IUN: 'JUN',
  };

  function pad2(n) { return Ws.pad2(n); }

  function fixOcrDigits(text) {
    return String(text || '')
      .replace(/([OoD])(?=[\d,])/g, '0')
      .replace(/(?<=[\d,])[OoD]/g, '0')
      .replace(/([lI|])(?=[\d,])/g, '1')
      .replace(/(?<=[\d,])[lI|]/g, '1');
  }

  function fixMonthToken(tok) {
    var t = String(tok || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
    return MONTH_FIX[t] || MONTH_FIX[t.slice(0, 3)] || t.slice(0, 3);
  }

  Parser.fixOcrTextForDate = function fixOcrTextForDate(text) {
    var t = String(text || '').replace(/\s+/g, ' ').replace(/—/g, '-').trim();
    t = t.replace(/\b(20[0-9O]{2})[\/.-]\s*([O0]?\d{1,2})[\/.-]\s*([O0]?\d{1,2})\b/gi, function (_, y, mo, d) {
      y = String(y).replace(/O/g, '0');
      mo = String(mo).replace(/O/g, '0');
      d = String(d).replace(/O/g, '0');
      return y + '-' + pad2(parseInt(mo, 10)) + '-' + pad2(parseInt(d, 10));
    });
    t = t.replace(/\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\b/gi, '').trim();
    t = t.replace(/\b(\d{1,2})[\/\-.]([A-Za-z]{3,9})[\/\-.](\d{2,4})\b/g, function (_, d, mon, y) {
      return d + ' ' + fixMonthToken(mon) + ' ' + y;
    });
    t = t.replace(/\b(\d{1,2})\s+([A-Za-z0-9]{2,9})\s+(\d{2,4})\b/g, function (_, d, mon, y) {
      return d + ' ' + fixMonthToken(mon) + ' ' + y;
    });
    return t.trim();
  };

  function normalizeAmount(val) {
    if (!val) return null;
    var cleaned = String(val).replace(/,/g, '').replace(/\.(?=.*\.)/g, '');
    var num = parseFloat(cleaned);
    if (!isFinite(num) || num < Ws.AMOUNT_MIN || num > Ws.AMOUNT_MAX) return null;
    return num % 1 === 0 ? String(Math.round(num)) : num.toFixed(2);
  }

  function scoreAmount(raw, bonus, fullText) {
    var val = normalizeAmount(fixOcrDigits(raw));
    if (!val) return null;
    var score = bonus || 80;
    if (/(?:RS\.|PKR\.?)/i.test(String(fullText || ''))) score += 8;
    return { val: val, score: score };
  }

  Parser.huntAmount = function huntAmount(text, opts) {
    opts = opts || {};
    var raw = fixOcrDigits(String(text || ''));
    if (!raw.trim()) return null;
    var candidates = [];
    var m;
    var patterns = [
      { re: /Rs\.\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d{2,12}(?:\.\d{2})?)/gi, bonus: 130 },
      { re: /(?:PKR|RS\.?)\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d{2,12}(?:\.\d{2})?)/gi, bonus: 120 },
      { re: /(?:TRANSFERRED\s*AMOUNT|AMOUNT\s*PAID|AMOUNT)\s*[:\-]?\s*(?:PKR|RS\.?)?\s*([\d,]+(?:\.\d{2})?)/gi, bonus: 115 },
      { re: /\b(\d{1,3}(?:,\d{3})+(?:\.\d{2})?)\b/g, bonus: 70 },
    ];
    patterns.forEach(function (p) {
      p.re.lastIndex = 0;
      while ((m = p.re.exec(raw)) !== null) {
        var c = scoreAmount(m[1], p.bonus, raw);
        if (c) candidates.push(c);
      }
    });
    if (!candidates.length && !opts.strict) {
      var plain = raw.match(/\b(\d{3,7}(?:\.\d{2})?)\b/);
      if (plain) {
        var loose = scoreAmount(plain[1], 45, raw);
        if (loose) candidates.push(loose);
      }
    }
    if (!candidates.length) return null;
    candidates.sort(function (a, b) { return b.score - a.score; });
    return candidates[0].val;
  };

  Parser.huntDate = function huntDate(text) {
    var raw = String(text || '');
    var t = Parser.fixOcrTextForDate(raw);
    var patterns = [
      /* YYYY-MM-DD — myABL / ISO */
      { re: /\b(20\d{2})-(\d{2})-(\d{2})\b/g, kind: 'ymd', bonus: 22 },
      { re: /\b(20\d{2})[\/.-](\d{1,2})[\/.-](\d{1,2})\b/g, kind: 'ymd', bonus: 18 },
      /* DD-MMM-YYYY / DD-Mon-YYYY — HBL, Meezan */
      { re: /\b(\d{1,2})[\/\-.](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\/\-.](\d{4})\b/gi, kind: 'dmy4', bonus: 16 },
      { re: /\b(\d{1,2})[\/\-.](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\/\-.](\d{2})\b/gi, kind: 'dmy2', bonus: 14 },
      { re: /\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b/gi, kind: 'dmy4', bonus: 12 },
      /* DD/MM/YYYY — numeric */
      { re: /\b(\d{1,2})\/(\d{1,2})\/(\d{4})\b/g, kind: 'dmy', bonus: 10 },
      { re: /\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})\b/g, kind: 'dmy', bonus: 8 },
    ];
    var best = null;
    var bestScore = -1;
    var m;
    patterns.forEach(function (pat) {
      pat.re.lastIndex = 0;
      while ((m = pat.re.exec(t)) !== null) {
        var d, mo, y, score = 80 + (pat.bonus || 0);
        if (pat.kind === 'dmy4' || pat.kind === 'dmy2') {
          d = parseInt(m[1], 10);
          mo = MONTHS[String(m[2]).slice(0, 3).toLowerCase()] || 0;
          y = parseInt(m[3], 10);
          if (pat.kind === 'dmy2' && y < 100) y += 2000;
        } else if (pat.kind === 'dmy') {
          d = parseInt(m[1], 10);
          mo = parseInt(m[2], 10);
          y = parseInt(m[3], 10);
        } else {
          y = parseInt(String(m[1]).replace(/O/g, '0'), 10);
          mo = parseInt(String(m[2]).replace(/O/g, '0'), 10);
          d = parseInt(String(m[3]).replace(/O/g, '0'), 10);
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
  };

  function normalizeRefDigits(raw) {
    return fixOcrDigits(String(raw || '')).replace(/\s+/g, '').replace(/[^\d]/g, '');
  }

  Parser.isPlausibleReferenceId = function isPlausibleReferenceId(digits) {
    if (!digits || digits.length < 5 || digits.length > 20) return false;
    if (/^20\d{6}$/.test(digits)) return false;
    return true;
  };

  Parser.huntReference = function huntReference(text) {
    var raw = String(text || '');
    if (!raw.trim()) return null;
    var labelRes = [
      /* Allied Bank — "Reference Number# 527017" */
      /Reference\s*Number\s*#\s*(\d{5,})/gi,
      /REFERENCE\s*NUMBER\s*#\s*(\d{5,})/gi,
      /Reference\s*Number\s*#\s*(\d+)/gi,
      /* Compact Ref# anchor */
      /\bRef\s*#\s*(\d{5,})/gi,
      /\bREF\s*#\s*(\d{5,})/gi,
      /(?:Transaction\s*ID|TID|Txn)\s*#?\s*(\d{6,})/gi,
      /(?:TRANSACTION\s*ID|TRANSACTION\s*REFERENCE|TID|TXN|REF(?:ERENCE)?)\s*[:\-#]?\s*(\d{6,})/gi,
      /(?:ID\s*#)\s*(\d{6,})/gi,
    ];
    var m;
    var i;
    for (i = 0; i < labelRes.length; i++) {
      labelRes[i].lastIndex = 0;
      while ((m = labelRes[i].exec(raw)) !== null) {
        var digits = normalizeRefDigits(m[1]);
        if (Parser.isPlausibleReferenceId(digits)) return digits;
      }
    }
    var hash = raw.match(/#\s*(\d{5,})/);
    if (hash && hash[1]) {
      var fromHash = normalizeRefDigits(hash[1]);
      if (Parser.isPlausibleReferenceId(fromHash)) return fromHash;
    }
    var runs = raw.match(/\b\d{6,}\b/g);
    if (runs) {
      for (i = 0; i < runs.length; i++) {
        if (Parser.isPlausibleReferenceId(runs[i])) return runs[i];
      }
    }
    return null;
  };

  Parser.huntAll = function huntAll(text) {
    return {
      date: Parser.huntDate(text),
      amount: Parser.huntAmount(text),
      reference_no: Parser.huntReference(text),
    };
  };

  Parser.huntField = function huntField(fieldKey, text) {
    if (fieldKey === 'date') return Parser.huntDate(text);
    if (fieldKey === 'amount') return Parser.huntAmount(text, { strict: false });
    if (fieldKey === 'reference_no') return Parser.huntReference(text);
    return null;
  };

  Parser.slipTextHasMyAbl = function slipTextHasMyAbl(text) {
    var upper = String(text || '').toUpperCase();
    if (upper.indexOf('MYABL') !== -1) return true;
    if (/\bALLIED\s+BANK\b/.test(upper)) return true;
    return false;
  };

  Parser.validateAmountCandidate = function validateAmountCandidate(val, fullText) {
    if (!val) return false;
    var num = parseFloat(String(val).replace(/,/g, ''));
    if (!isFinite(num) || num < Ws.AMOUNT_MIN || num > Ws.AMOUNT_MAX) return false;
    var digits = String(val).replace(/\D/g, '');
    if (fullText && digits.length >= 6) {
      var ref = Parser.huntReference(fullText);
      if (ref && ref.replace(/\D/g, '') === digits) return false;
    }
    return true;
  };

  Parser.parseDateFromText = Parser.huntDate;
  Parser.parseAmountFromText = function (t, o) { return Parser.huntAmount(t, o); };
  Parser.parseReferenceFromText = Parser.huntReference;
  Parser.parseReferenceFromZone = Parser.huntReference;

})(window);
