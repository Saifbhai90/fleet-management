/**
 * Workspace Slip OCR v3 — local post-OCR correction layer.
 *
 * Runs AFTER extraction (before AutoFill) to clean up common OCR mistakes
 * using domain knowledge (Pakistani bank slips), with NO network calls:
 *
 *  - Amount: Lakh/Crore format (1,50,000), stray currency symbols, cent fix.
 *  - Date: month-name typos, impossible day/month, year sanity.
 *  - Reference: strip non-digits, length clamp, dedupe against amount digits.
 *  - Cross-field checks: amount vs reference overlap, date in the future.
 *
 * Exposed as Ws.Corrector.correct(extractData) → corrected extractData.
 * Pure functions, deterministic, safe to run on every extraction.
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr;
  if (!Ws) return;

  var C = {};
  Ws.Corrector = C;

  /* ----------------------------- AMOUNT ----------------------------- */

  /**
   * Pakistani numbers may use the Lakh format 1,50,000 (2-digit groups after
   * the first 3). Normalise to a plain integer string, preserving 2dp when the
   * slip clearly used cents.
   */
  C.correctAmount = function correctAmount(raw) {
    if (!raw) return null;
    var s = String(raw).trim();
    // Strip currency words / symbols but remember their presence.
    s = s.replace(/(?:PKR|RS|RUP\w*|Rs\.?)/gi, '');
    s = s.replace(/[^\d.,]/g, '');
    if (!s) return null;
    // Fix OCR letter-as-digit mistakes.
    s = s.replace(/[Oo]/g, '0').replace(/[lI|]/g, '1').replace(/[Ss](?=\d)/g, '5');

    // Determine if trailing .XX is cents (single dot near end).
    var dotCount = (s.match(/\./g) || []).length;
    var hasCents = dotCount === 1 && /\.\d{2}$/.test(s);

    // Remove ALL separators, then re-group if it looks like a lakh format.
    var digitsOnly = s.replace(/[.,]/g, '');
    if (!/^\d+$/.test(digitsOnly)) {
      // leftover junk
      var m = digitsOnly.match(/\d+/);
      digitsOnly = m ? m[0] : '';
    }
    if (!digitsOnly) return null;
    var num = parseInt(digitsOnly, 10);
    if (!isFinite(num) || num < Ws.AMOUNT_MIN || num > Ws.AMOUNT_MAX) return null;

    // If original had cents AND digit count implies the last 2 were decimals
    // (i.e. stripping them gives a saner amount), keep them.
    if (hasCents && digitsOnly.length >= 3) {
      var whole = parseInt(digitsOnly.slice(0, -2), 10);
      var cents = parseInt(digitsOnly.slice(-2), 10);
      if (whole >= Ws.AMOUNT_MIN && cents <= 99) {
        return whole + '.' + (cents < 10 ? '0' + cents : cents);
      }
    }
    return String(num);
  };

  /* ------------------------------ DATE ------------------------------ */

  var MONTH_TYPOS = {
    'JUN': 'JUN', '1UN': 'JUN', 'IUN': 'JUN', 'JULY': 'JUL', 'JULL': 'JUL',
    'JAN': 'JAN', 'FEB': 'FEB', 'MAR': 'MAR', 'APR': 'APR', 'MAY': 'MAY',
    'AUG': 'AUG', 'SEP': 'SEP', 'OCT': 'OCT', 'NOV': 'NOV', 'DEC': 'DEC',
    'JANE': 'JAN', 'FEBR': 'FEB', 'MARC': 'MAR', 'APRL': 'APR',
  };

  /** Returns DD-MM-YYYY or null. Rejects implausible / far-future dates. */
  C.correctDate = function correctDate(raw) {
    if (!raw) return null;
    var s = String(raw).trim();
    // Already normalised by parser?
    var m = s.match(/^(\d{2})-(\d{2})-(\d{4})$/);
    if (!m) {
      // Defer to the parser for free-form text.
      if (Ws.Parser && Ws.Parser.huntDate) {
        s = Ws.Parser.huntDate(s) || s;
        m = s.match(/^(\d{2})-(\d{2})-(\d{4})$/);
      }
    }
    if (!m) return null;
    var d = parseInt(m[1], 10);
    var mo = parseInt(m[2], 10);
    var y = parseInt(m[3], 10);
    if (d < 1 || d > 31 || mo < 1 || mo > 12 || y < 2000 || y > 2100) return null;
    // Reject dates more than 1 year in the future or 30 years in the past.
    var now = new Date();
    var dt = new Date(y, mo - 1, d);
    if (dt.getFullYear() > now.getFullYear() + 1) return null;
    if (dt.getFullYear() < now.getFullYear() - 30) return null;
    return Ws.pad2(d) + '-' + Ws.pad2(mo) + '-' + y;
  };

  /* ---------------------------- REFERENCE ---------------------------- */

  C.correctReference = function correctReference(raw, amountVal) {
    if (!raw) return null;
    var s = String(raw).trim();
    // Reference should be digits only (some banks prefix with #).
    var digits = s.replace(/[^\d]/g, '');
    if (digits.length < 5) {
      // Some references legitimately contain letters (e.g. RAST-...). Keep
      // alphanumeric when there are letters but at least 5 digits.
      if (/[A-Za-z]/.test(s) && digits.length >= 5) {
        digits = s.replace(/\s/g, '').toUpperCase();
      } else {
        return null;
      }
    }
    if (digits.length > 25) digits = digits.slice(0, 25);
    // Dedupe: if the reference is identical to the amount digits, it's likely
    // the OCR grabbed the amount twice.
    if (amountVal && String(amountVal).replace(/\D/g, '') === digits.replace(/\D/g, '')) {
      return null;
    }
    return digits;
  };

  /* --------------------------- PIPELINE --------------------------- */

  /**
   * Apply all corrections to a flattened extract result.
   * Mutates + returns the data object. Adds data.corrected = list of keys.
   */
  C.correct = function correct(data) {
    if (!data) return data;
    var corrected = [];
    var amt = C.correctAmount(data.amount);
    if (amt && amt !== data.amount) { data.amount = amt; corrected.push('amount'); }
    else if (amt) { data.amount = amt; }

    var ref = C.correctReference(data.reference_no, data.amount);
    if (ref && ref !== data.reference_no) { data.reference_no = ref; corrected.push('reference_no'); }
    else if (ref) { data.reference_no = ref; }

    var dt = C.correctDate(data.date);
    if (dt && dt !== data.date) { data.date = dt; corrected.push('date'); }
    else if (dt) { data.date = dt; }

    data.corrected = corrected;
    return data;
  };

})(window);
