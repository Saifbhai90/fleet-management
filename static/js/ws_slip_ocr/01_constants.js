/**
 * Workspace Slip OCR v2 — shared constants & config.
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr = global.WsSlipOcr || {};

  Ws.VERSION = '2.0.7';

  /** OCR may ONLY write these element ids (+ payment mode). */
  Ws.OCR_FIELD_IDS = {
    date: 'wsTransferDateInput',
    amount: 'wsTransferAmountInput',
    reference_no: 'wsTransferRefInput',
    payment_mode: 'wsPaymentModeSelect',
  };
  Ws.TESSERACT_VERSION = '5.1.1';
  Ws.INSTANT_WORKER_COUNT = 3;
  Ws.LOW_CONFIDENCE = 0.6;
  Ws.FALLBACK_CONFIDENCE = 0.6;
  Ws.ZONE_PAD_PCT = 10;
  Ws.DIGITAL_MAX_WIDTH = 1000;
  Ws.UNIVERSAL_SCAN_MAX_WIDTH = 1000;
  Ws.AMOUNT_MIN = 10;
  Ws.AMOUNT_MAX = 10000000000;

  Ws.FIELD_LABELS = {
    date: 'Transfer Date',
    amount: 'Amount',
    reference_no: 'Reference No',
  };

  Ws.FIELD_COLORS = {
    date: '#0d6efd',
    amount: '#198754',
    reference_no: '#fd7e14',
  };

  Ws.FIELD_TINTS = {
    date: 'rgba(13,110,253,0.10)',
    amount: 'rgba(25,135,84,0.10)',
    reference_no: 'rgba(253,126,20,0.10)',
  };

  Ws.FIELD_KEYS = ['date', 'amount', 'reference_no'];

  /** Transfer form element id → policy key (auto-fill registry). */
  Ws.FIELD_ID_MAP = {
    wsTransferDateInput: 'date',
    wsTransferAmountInput: 'amount',
    wsTransferRefInput: 'reference_no',
    wsPaymentModeSelect: 'payment_mode',
    wsTransferCategorySelect: 'category',
    wsFromAccountSelect: 'from_account',
    wsToAccountSelect: 'to_account',
    wsTransferDesc: 'description',
  };

  Ws.SELECT_DEFAULTS = {
    payment_mode: 'Cash',
    category: '',
    from_account: '',
    to_account: '',
  };

  /** Navigation keys — do not mark field as user-touched. */
  Ws.NAV_KEYS = {
    Tab: 1, Shift: 1, Control: 1, Alt: 1, Meta: 1,
    ArrowUp: 1, ArrowDown: 1, ArrowLeft: 1, ArrowRight: 1,
    Escape: 1, Home: 1, End: 1, PageUp: 1, PageDown: 1,
  };

  Ws.pad2 = function pad2(n) {
    return ('0' + n).slice(-2);
  };

  Ws.detectProviderFromText = function detectProviderFromText(ocrText) {
    var upper = String(ocrText || '').toUpperCase();
    var best = null;
    var bestScore = 0;
    Ws.PROVIDER_TEMPLATES.forEach(function (p) {
      var hits = 0;
      p.keys.forEach(function (k) {
        if (upper.indexOf(k) !== -1) hits++;
      });
      var score = p.keys.length ? hits / p.keys.length : 0;
      if (score > bestScore) {
        bestScore = score;
        best = p;
      }
    });
    return bestScore >= 0.34 ? best : null;
  };

  Ws.STOP_WORDS = {
    THE: 1, AND: 1, FOR: 1, FROM: 1, WITH: 1, YOUR: 1, THIS: 1, THAT: 1,
    HAVE: 1, WILL: 1, ARE: 1, WAS: 1, HAS: 1, NOT: 1, BUT: 1, YOU: 1, ALL: 1,
    CAN: 1, OUT: 1, DAY: 1, GET: 1, MAY: 1, NEW: 1, NOW: 1, OLD: 1, SEE: 1,
    AM: 1, PM: 1, PKR: 1, RS: 1, PAID: 1, SEND: 1, MONEY: 1, TRANSFER: 1,
    SUCCESS: 1, SUCCESSFUL: 1,
  };

  /** Fingerprint hints only — extraction uses anchor keywords, not bank IDs. */
  Ws.PROVIDER_TEMPLATES = [
    { id: 'jazzcash', keys: ['JAZZCASH', 'JAZZ CASH'] },
    { id: 'easypaisa', keys: ['EASYPAISA', 'EASY PAISA'] },
    { id: 'hbl', keys: ['HBL', 'HABIB BANK'] },
    { id: 'meezan', keys: ['MEEZAN', 'MEEZAN BANK'] },
    { id: 'ubl', keys: ['UBL', 'UNITED BANK'] },
    { id: 'abl', keys: ['MYABL', 'ALLIED BANK', 'ALLIED'] },
    { id: 'mcb', keys: ['MCB'] },
    { id: 'raast', keys: ['RAAST'] },
    { id: 'sadapay', keys: ['SADAPAY'] },
    { id: 'nayapay', keys: ['NAYAPAY'] },
  ];

  Ws.FULL_OCR_WHITELIST =
    '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .:/-#@$%&*()+_ RSrsPKRpkr,';

  Ws.ocrConfig = function ocrConfig() {
    var cfg = global.__wsSlipOcrConfig || {};
    return {
      mode: cfg.mode || 'balanced',
      preprocess: cfg.preprocess !== false,
      debug: cfg.debug === true,
    };
  };

  Ws.ocrDebugEnabled = function ocrDebugEnabled() {
    if (global.__wsSlipOcrDebug === true) return true;
    if (global.__wsSlipOcrDebug === false) return false;
    return Ws.ocrConfig().debug;
  };

  Ws.ocrLog = function ocrLog(label, payload) {
    if (!Ws.ocrDebugEnabled()) return;
    try {
      if (payload !== undefined) console.log('[ws-ocr] ' + label, payload);
      else console.log('[ws-ocr] ' + label);
    } catch (e) { /* ignore */ }
  };

  Ws.fieldResult = function fieldResult(value, confidence, source) {
    return {
      value: value || null,
      confidence: typeof confidence === 'number' ? confidence : (value ? 0.7 : 0),
      source: source || 'unknown',
    };
  };

})(window);
