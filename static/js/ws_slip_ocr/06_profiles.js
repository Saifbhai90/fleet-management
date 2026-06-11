/**
 * Workspace Slip OCR v2 — profile matching, fingerprint, teach helpers.
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr;
  if (!Ws) return;

  var Profiles = {};
  Ws.Profiles = Profiles;

  function levenshtein(a, b) {
    var m = a.length;
    var n = b.length;
    if (!m) return n;
    if (!n) return m;
    var row = [];
    for (var j = 0; j <= n; j++) row[j] = j;
    for (var i = 1; i <= m; i++) {
      var prev = i - 1;
      row[0] = i;
      for (j = 1; j <= n; j++) {
        var tmp = row[j];
        row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
        prev = tmp;
      }
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
    return Math.max(0, (longer.length - levenshtein(longer, shorter)) / longer.length);
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

  Profiles.profileRegionMap = function profileRegionMap(profile) {
    var regions = {};
    ((profile && profile.fields) || []).forEach(function (f) {
      if (f && f.field_key) regions[f.field_key] = f;
    });
    return regions;
  };

  Profiles.profileHasAllZones = function profileHasAllZones(profile) {
    var r = Profiles.profileRegionMap(profile);
    return !!(r.date && r.amount && r.reference_no);
  };

  Profiles.findProfileById = function findProfileById(profiles, id) {
    if (!id || !profiles) return null;
    for (var i = 0; i < profiles.length; i++) {
      if (profiles[i].id === id) return profiles[i];
    }
    return null;
  };

  Profiles.buildFingerprint = function buildFingerprint(text) {
    var upper = String(text || '').toUpperCase().replace(/[^A-Z0-9\s]/g, ' ');
    var words = upper.split(/\s+/).filter(function (w) {
      return w.length >= 3 && !Ws.STOP_WORDS[w];
    });
    var seen = {};
    var out = [];
    words.forEach(function (w) {
      if (seen[w]) return;
      seen[w] = 1;
      out.push(w);
    });
    Ws.PROVIDER_TEMPLATES.forEach(function (p) {
      p.keys.forEach(function (k) {
        var kk = k.replace(/\s+/g, '');
        if (fuzzyKeywordInText(upper, k) && !seen[kk]) {
          seen[kk] = 1;
          out.unshift(kk);
        }
      });
    });
    return out.slice(0, 45);
  };

  Profiles.scoreProfile = function scoreProfile(profile, ocrText) {
    var upper = String(ocrText || '').toUpperCase();
    var keys = profile.fingerprint_keywords || [];
    var namePart = stringSimilarity(profile.name || '', upper) * 0.25;
    if (!keys.length) return namePart;
    var hits = 0;
    keys.forEach(function (k) {
      if (fuzzyKeywordInText(upper, k)) hits++;
    });
    return namePart + (hits / keys.length) * 0.75;
  };

  Profiles.rankProfiles = function rankProfiles(profiles, ocrText) {
    return (profiles || []).map(function (p) {
      return { profile: p, score: Profiles.scoreProfile(p, ocrText) };
    }).sort(function (a, b) { return b.score - a.score; });
  };

  Profiles.profileLooksMyAbl = function profileLooksMyAbl(profile) {
    if (!profile) return false;
    var blob = String(profile.name || '').toUpperCase();
    (profile.fingerprint_keywords || []).forEach(function (k) {
      blob += ' ' + String(k || '').toUpperCase();
    });
    return Ws.Parser.slipTextHasMyAbl(blob);
  };

  Profiles.normalizeFieldValue = function normalizeFieldValue(fieldKey, val) {
    var v = String(val || '').trim();
    if (!v) return '';
    if (fieldKey === 'amount') {
      var num = parseFloat(v.replace(/,/g, ''));
      if (!isFinite(num)) return v;
      return num % 1 === 0 ? String(Math.round(num)) : num.toFixed(2);
    }
    if (fieldKey === 'reference_no') return v.replace(/\s/g, '').toUpperCase();
    if (fieldKey === 'date') return Ws.Parser.huntDate(v) || v;
    return v;
  };

  Profiles.fieldValuesMatch = function fieldValuesMatch(fieldKey, a, b) {
    return Profiles.normalizeFieldValue(fieldKey, a) === Profiles.normalizeFieldValue(fieldKey, b);
  };

  Profiles.cacheProfiles = function cacheProfiles(profiles) {
    try {
      global.localStorage.setItem('ws_slip_profiles_v1', JSON.stringify(profiles || []));
    } catch (e) { /* ignore */ }
  };

  Profiles.readCachedProfiles = function readCachedProfiles() {
    try {
      var raw = global.localStorage.getItem('ws_slip_profiles_v1');
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : null;
    } catch (e) {
      return null;
    }
  };

  function bboxToRegion(bbox, imgW, imgH, padRatio) {
    padRatio = padRatio || 0.15;
    var x0 = bbox.x0;
    var y0 = bbox.y0;
    var x1 = bbox.x1;
    var y1 = bbox.y1;
    var pw = (x1 - x0) * padRatio;
    var ph = (y1 - y0) * padRatio;
    x0 = Math.max(0, x0 - pw);
    y0 = Math.max(0, y0 - ph);
    x1 = Math.min(imgW, x1 + pw);
    y1 = Math.min(imgH, y1 + ph);
    return {
      region_x: (x0 / imgW) * 100,
      region_y: (y0 / imgH) * 100,
      region_w: ((x1 - x0) / imgW) * 100,
      region_h: ((y1 - y0) / imgH) * 100,
    };
  }

  Profiles.findRegionForCorrectedValue = function findRegionForCorrectedValue(img, fieldKey, correctedValue) {
    img = Ws.prepareSlipImage(img);
    var target = Profiles.normalizeFieldValue(fieldKey, correctedValue);
    if (!target) return Promise.resolve(null);
    return Ws.prewarmWorker().then(function () {
      return Ws.recognizeCanvas(Ws.makeUniversalScanCanvas(img), null, { psm: '6', noWhitelist: true });
    }).then(function (raw) {
      var words = (raw && raw.data && raw.data.words) ? raw.data.words : [];
      var size = Ws.imagePixelSize(img);
      var scale = size.w > Ws.UNIVERSAL_SCAN_MAX_WIDTH ? Ws.UNIVERSAL_SCAN_MAX_WIDTH / size.w : 1;
      var best = null;
      var bestScore = 0;
      for (var i = 0; i < words.length; i++) {
        for (var len = 1; len <= 4 && i + len <= words.length; len++) {
          var chunk = words.slice(i, i + len);
          var text = chunk.map(function (w) { return w.text; }).join(' ');
          var norm = Profiles.normalizeFieldValue(fieldKey, Ws.Parser.huntField(fieldKey, text) || text);
          var sim = stringSimilarity(norm, target);
          if (sim > bestScore && chunk[0].bbox) {
            bestScore = sim;
            var bb = chunk[0].bbox;
            for (var j = 1; j < chunk.length; j++) {
              bb = {
                x0: Math.min(bb.x0, chunk[j].bbox.x0),
                y0: Math.min(bb.y0, chunk[j].bbox.y0),
                x1: Math.max(bb.x1, chunk[j].bbox.x1),
                y1: Math.max(bb.y1, chunk[j].bbox.y1),
              };
            }
            best = bboxToRegion(
              { x0: bb.x0 / scale, y0: bb.y0 / scale, x1: bb.x1 / scale, y1: bb.y1 / scale },
              size.w,
              size.h
            );
          }
        }
      }
      return bestScore >= 0.72 ? best : null;
    }).catch(function () { return null; });
  };

  Profiles.learnFieldCorrection = function learnFieldCorrection(img, profile, fieldKey, correctedValue, ocrTextOptional) {
    if (!img || !profile || !fieldKey || !correctedValue) return Promise.resolve(null);
    return Profiles.findRegionForCorrectedValue(img, fieldKey, correctedValue).then(function (region) {
      if (!region) return null;
      return {
        field_key: fieldKey,
        region: region,
        keywords: ocrTextOptional ? Profiles.buildFingerprint(ocrTextOptional).slice(0, 12) : [],
      };
    });
  };

})(window);
