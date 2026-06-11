/**
 * Workspace Slip OCR v2 — hybrid zonal + universal fallback extraction.
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr;
  if (!Ws) return;

  var Extract = {};
  Ws.Extract = Extract;

  function zonePreprocessMode(img, region, fieldKey, profile) {
    if (fieldKey === 'amount') {
      return Ws.resolveAmountPreprocessMode(img, region, profile);
    }
    return 'grayscale';
  }

  /** Apply 10% zone padding before crop — absorbs screenshot alignment drift. */
  function paddedZoneRegion(region) {
    return Ws.expandRegionPadding(region, Ws.ZONE_PAD_PCT);
  }

  function parseZoneOcr(fieldKey, raw, conf) {
    var text = (raw && raw.data && raw.data.text) ? raw.data.text : '';
    var ocrConf = (raw && raw.data && typeof raw.data.confidence === 'number')
      ? raw.data.confidence / 100 : 0.55;
    var parsed = Ws.Parser.huntField(fieldKey, text);
    if (!parsed) return Ws.fieldResult(null, 0, 'zone-empty');
    return Ws.fieldResult(parsed, Math.min(0.98, Math.max(conf || 0, ocrConf)), 'zone');
  }

  Extract.readZoneField = function readZoneField(img, region, fieldKey, slot, profile) {
    if (!region) return Promise.resolve(Ws.fieldResult(null, 0, 'none'));
    img = Ws.prepareSlipImage(img);
    var cropRegion = paddedZoneRegion(region);
    var mode = zonePreprocessMode(img, cropRegion, fieldKey, profile);
    var scale = img._slipDigital ? 2 : 2.4;
    var canvas = Ws.makeRegionCanvas(img, cropRegion, scale, mode, { zonePadAlreadyApplied: true });
    if (!canvas) return Promise.resolve(Ws.fieldResult(null, 0, 'crop-fail'));
    return Ws.recognizeCanvas(canvas, fieldKey, { psm: '7', noWhitelist: true }, slot)
      .then(function (raw) {
        return parseZoneOcr(fieldKey, raw, 0.72);
      });
  };

  Extract.extractZonesParallel = function extractZonesParallel(img, profile, opts) {
    opts = opts || {};
    img = Ws.prepareSlipImage(img);
    var regions = Ws.Profiles.profileRegionMap(profile);
    var keys = Ws.FIELD_KEYS;
    Ws.ocrLog('zones parallel', { profile: profile.name, digital: !!img._slipDigital });
    return Ws.prewarmInstantWorkers().then(function () {
      return Promise.all(keys.map(function (key, slot) {
        return Extract.readZoneField(img, regions[key], key, slot, profile).then(function (result) {
          if (typeof opts.onProgress === 'function' && result && result.value) {
            opts.onProgress({ key: key, value: result.value, result: result, profileName: profile.name });
          }
          return { key: key, result: result || Ws.fieldResult(null, 0, 'none') };
        });
      }));
    }).then(function (rows) {
      var fieldMeta = {};
      rows.forEach(function (row) { fieldMeta[row.key] = row.result; });
      return Extract.applyUniversalFallback(img, fieldMeta, opts).then(function (merged) {
        return Extract.flattenResults(merged, profile);
      });
    });
  };

  Extract.needsFallback = function needsFallback(fieldMeta) {
    return Ws.FIELD_KEYS.some(function (k) {
      var r = fieldMeta[k];
      return !r || !r.value || (r.confidence || 0) < Ws.FALLBACK_CONFIDENCE;
    });
  };

  Extract.applyUniversalFallback = function applyUniversalFallback(img, fieldMeta, opts) {
    if (!Extract.needsFallback(fieldMeta)) return Promise.resolve(fieldMeta);
    Ws.ocrLog('universal scan fallback');
    return Ws.prewarmWorker().then(function () {
      return Ws.ocrUniversalScan(Ws.makeUniversalScanCanvas(img));
    }).then(function (fullText) {
      var hunted = Ws.Parser.huntAll(fullText);
      var out = {};
      Ws.FIELD_KEYS.forEach(function (k) {
        var zone = fieldMeta[k];
        var low = !zone || !zone.value || (zone.confidence || 0) < Ws.FALLBACK_CONFIDENCE;
        if (low && hunted[k]) {
          out[k] = Ws.fieldResult(hunted[k], 0.68, 'universal');
          if (typeof opts.onProgress === 'function') {
            opts.onProgress({ key: k, value: hunted[k], result: out[k], profileName: opts.profileName });
          }
        } else {
          out[k] = zone || Ws.fieldResult(null, 0, 'none');
        }
      });
      out._ocrText = fullText;
      return out;
    });
  };

  Extract.flattenResults = function flattenResults(fieldMeta, profile) {
    var flat = {
      date: (fieldMeta.date && fieldMeta.date.value) || null,
      amount: (fieldMeta.amount && fieldMeta.amount.value) || null,
      reference_no: (fieldMeta.reference_no && fieldMeta.reference_no.value) || null,
      fieldMeta: {},
      profileName: profile ? profile.name : null,
      ocrText: fieldMeta._ocrText || '',
    };
    Ws.FIELD_KEYS.forEach(function (k) {
      flat.fieldMeta[k] = fieldMeta[k] || Ws.fieldResult(null, 0, 'none');
    });
    return flat;
  };

  Extract.isCompleteExtract = function isCompleteExtract(data) {
    if (!data) return false;
    return Ws.FIELD_KEYS.every(function (k) {
      var v = data[k] || (data.fieldMeta && data.fieldMeta[k] && data.fieldMeta[k].value);
      return !!v && v !== '—';
    });
  };

  Extract.extractionQuality = function extractionQuality(data) {
    if (!data) return 0;
    var filled = 0;
    var confSum = 0;
    Ws.FIELD_KEYS.forEach(function (k) {
      var meta = data.fieldMeta && data.fieldMeta[k];
      var val = data[k] || (meta && meta.value);
      if (val && val !== '—') {
        filled++;
        confSum += (meta && typeof meta.confidence === 'number') ? meta.confidence : 0.55;
      }
    });
    return filled * 100 + confSum;
  };

  Extract.extractGeneric = function extractGeneric(img, fullTextOptional) {
    img = Ws.prepareSlipImage(img);
    var run = fullTextOptional
      ? Promise.resolve(fullTextOptional)
      : Ws.ocrFullImageCached(img);
    return run.then(function (text) {
      var hunted = Ws.Parser.huntAll(text);
      var fieldMeta = {
        date: Ws.fieldResult(hunted.date, hunted.date ? 0.65 : 0, 'generic'),
        amount: Ws.fieldResult(hunted.amount, hunted.amount ? 0.65 : 0, 'generic'),
        reference_no: Ws.fieldResult(hunted.reference_no, hunted.reference_no ? 0.62 : 0, 'generic'),
        _ocrText: text,
      };
      return Extract.flattenResults(fieldMeta, null);
    });
  };

  Extract.previewField = function previewField(img, fieldKey, region, profile) {
    return Ws.prewarmWorker().then(function () {
      return Extract.readZoneField(img, region, fieldKey, 0, profile);
    });
  };

  Extract.previewRegions = function previewRegions(img, regionsByKey, profile) {
    img = Ws.prepareSlipImage(img);
    return Ws.prewarmInstantWorkers().then(function () {
      return Promise.all(Ws.FIELD_KEYS.map(function (key, slot) {
        var region = regionsByKey && regionsByKey[key];
        if (!region) return Promise.resolve({ key: key, result: Ws.fieldResult(null, 0, 'none') });
        return Extract.readZoneField(img, region, key, slot, profile).then(function (result) {
          return { key: key, result: result };
        });
      }));
    }).then(function (rows) {
      var fieldMeta = {};
      rows.forEach(function (row) { fieldMeta[row.key] = row.result; });
      return Extract.applyUniversalFallback(img, fieldMeta, {}).then(function (merged) {
        return Extract.flattenResults(merged, null);
      });
    });
  };

})(window);
