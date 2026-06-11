/**
 * Workspace Slip OCR v2 — image prep, digital fast-path, zone crops.
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr;
  if (!Ws) return;

  var _fullTextCache = new WeakMap();

  Ws.slipDrawTarget = function slipDrawTarget(img) {
    return img && img._slipCanvas ? img._slipCanvas : img;
  };

  Ws.imagePixelSize = function imagePixelSize(img) {
    return {
      w: img.naturalWidth || img.width || 0,
      h: img.naturalHeight || img.height || 0,
    };
  };

  function applyGrayscalePixels(d) {
    for (var i = 0; i < d.length; i += 4) {
      var g = (0.299 * d[i]) + (0.587 * d[i + 1]) + (0.114 * d[i + 2]);
      d[i] = d[i + 1] = d[i + 2] = Math.round(g);
    }
  }

  /** Orange/brown Rs. amounts on white slips (myABL etc.). */
  function applyColoredInkPixels(d) {
    for (var i = 0; i < d.length; i += 4) {
      var r = d[i];
      var g = d[i + 1];
      var b = d[i + 2];
      var max = Math.max(r, g, b);
      if (max > 245) {
        d[i] = d[i + 1] = d[i + 2] = 255;
        continue;
      }
      var orangeBrown = r > 90 && g > 30 && g < 180 && b < 135 && r > g && (r - b) > 30;
      var warmAmt = r - (g * 0.52) - (b * 0.35);
      var v = (orangeBrown || warmAmt > 16) ? 0 : 255;
      d[i] = d[i + 1] = d[i + 2] = v;
    }
  }

  Ws.enhanceCanvas = function enhanceCanvas(ctx, canvas, mode) {
    if (!mode || mode === 'none') return;
    var id = ctx.getImageData(0, 0, canvas.width, canvas.height);
    if (mode === 'grayscale') applyGrayscalePixels(id.data);
    else if (mode === 'colored-ink') applyColoredInkPixels(id.data);
    ctx.putImageData(id, 0, 0);
  };

  function sampleSlipImageStats(img) {
    var size = Ws.imagePixelSize(img);
    if (size.w < 8 || size.h < 8) return null;
    var sw = Math.min(96, size.w);
    var sh = Math.min(96, size.h);
    var c = document.createElement('canvas');
    c.width = sw;
    c.height = sh;
    var ctx = c.getContext('2d');
    try {
      ctx.drawImage(Ws.slipDrawTarget(img), (size.w - sw) / 2, (size.h - sh) / 2, sw, sh, 0, 0, sw, sh);
    } catch (e) {
      return null;
    }
    var d = ctx.getImageData(0, 0, sw, sh).data;
    var white = 0;
    var satSum = 0;
    var n = sw * sh;
    for (var i = 0; i < d.length; i += 4) {
      var r = d[i];
      var g = d[i + 1];
      var b = d[i + 2];
      var max = Math.max(r, g, b);
      var min = Math.min(r, g, b);
      if (max > 232 && (max - min) < 20) white++;
      satSum += (max - min);
    }
    return { whiteRatio: white / n, avgSat: satSum / n };
  }

  Ws.isSlipDigital = function isSlipDigital(img, file) {
    if (!img) return false;
    if (img._slipDigital === true || img._slipDigital === false) return img._slipDigital;
    var size = Ws.imagePixelSize(img);
    if (size.w < 540 || size.h < 400) return false;
    var stats = sampleSlipImageStats(img);
    if (!stats) return false;
    var type = (file && file.type) || (img._slipFileMeta && img._slipFileMeta.type) || '';
    var hiRes = size.w >= 720 && size.h >= 600;
    return hiRes && stats.whiteRatio >= 0.4 && stats.avgSat < 58 &&
      (type === 'image/png' || size.h / Math.max(1, size.w) > 1.25 || size.w >= 1080);
  };

  function profileHintsAllied(profile) {
    if (!profile) return false;
    var blob = String(profile.name || '').toUpperCase();
    (profile.fingerprint_keywords || []).forEach(function (k) {
      blob += ' ' + String(k || '').toUpperCase();
    });
    return blob.indexOf('MYABL') !== -1 || blob.indexOf('ALLIED') !== -1;
  }

  Ws.isMyAblSlip = function isMyAblSlip(img, ocrText, profile) {
    if (ocrText && Ws.Parser && Ws.Parser.slipTextHasMyAbl(ocrText)) {
      if (img) img._slipMyAbl = true;
      return true;
    }
    if (profile && (profileHintsAllied(profile) ||
        (Ws.Profiles && Ws.Profiles.profileLooksMyAbl(profile)))) {
      if (img) img._slipMyAbl = true;
      return true;
    }
    return !!(img && img._slipMyAbl);
  };

  Ws.cropHasOrangeInk = function cropHasOrangeInk(img, region) {
    var px = Ws.regionToPixelRect(img, region, 0, true);
    if (!px || px.w < 8) return false;
    var c = document.createElement('canvas');
    c.width = Math.min(px.w, 120);
    c.height = Math.min(px.h, 60);
    var ctx = c.getContext('2d');
    try {
      ctx.drawImage(Ws.slipDrawTarget(img), px.x, px.y, px.w, px.h, 0, 0, c.width, c.height);
    } catch (e) {
      return false;
    }
    var d = ctx.getImageData(0, 0, c.width, c.height).data;
    var orange = 0;
    var n = c.width * c.height;
    for (var i = 0; i < d.length; i += 4) {
      var r = d[i];
      var g = d[i + 1];
      var b = d[i + 2];
      if (r > 95 && g > 35 && b < 130 && r > g && (r - b) > 30) orange++;
    }
    return orange / n > 0.012;
  };

  /**
   * Amount field preprocess: colored-ink when Allied/myABL or orange pixels detected.
   * Grayscale otherwise (digital fast-path).
   */
  Ws.resolveAmountPreprocessMode = function resolveAmountPreprocessMode(img, region, profile) {
    if (Ws.isMyAblSlip(img, null, profile)) return 'colored-ink';
    if (Ws.cropHasOrangeInk(img, region)) return 'colored-ink';
    return 'grayscale';
  };

  Ws.expandRegionPadding = function expandRegionPadding(region, padPct) {
    if (!region) return region;
    padPct = padPct != null ? padPct : Ws.ZONE_PAD_PCT;
    var x = region.region_x || 0;
    var y = region.region_y || 0;
    var w = region.region_w || 10;
    var h = region.region_h || 8;
    var xPad = w * (padPct / 100);
    var yPad = h * (padPct / 100);
    var nx = Math.max(0, x - xPad);
    var ny = Math.max(0, y - yPad);
    return {
      region_x: nx,
      region_y: ny,
      region_w: Math.min(100 - nx, w + xPad * 2),
      region_h: Math.min(100 - ny, h + yPad * 2),
    };
  };

  Ws.regionToPixelRect = function regionToPixelRect(img, region, padPct, skipPad) {
    var size = Ws.imagePixelSize(img);
    if (!size.w || !size.h) return null;
    if (!skipPad) {
      var pad = (padPct != null && padPct > 0) ? padPct : (padPct === 0 ? 0 : Ws.ZONE_PAD_PCT);
      if (pad > 0) region = Ws.expandRegionPadding(region, pad);
    }
    var rx = Math.max(0, Math.floor(size.w * (region.region_x || 0) / 100));
    var ry = Math.max(0, Math.floor(size.h * (region.region_y || 0) / 100));
    var rw = Math.max(24, Math.floor(size.w * (region.region_w || 10) / 100));
    var rh = Math.max(8, Math.floor(size.h * (region.region_h || 10) / 100));
    rw = Math.min(rw, size.w - rx);
    rh = Math.min(rh, size.h - ry);
    return { x: rx, y: ry, w: rw, h: rh, naturalW: size.w, naturalH: size.h, region: region };
  };

  Ws.logRegionMapping = function logRegionMapping(tag, img, region) {
    Ws.ocrLog(tag || 'region', Ws.regionToPixelRect(img, region, 0));
  };

  Ws.prepareSlipImage = function prepareSlipImage(img, opts) {
    opts = opts || {};
    if (!img || img._slipReady) return img;
    var size = Ws.imagePixelSize(img);
    var digital = Ws.isSlipDigital(img, img._slipFileMeta);
    img._slipDigital = digital;
    var maxW = digital ? Ws.DIGITAL_MAX_WIDTH : Math.max(size.w, 1280);
    var scale = size.w > maxW ? maxW / size.w : 1;
    if (scale >= 0.999 && !digital) {
      img._slipReady = true;
      return img;
    }
    var c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(size.w * scale));
    c.height = Math.max(1, Math.round(size.h * scale));
    var ctx = c.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(Ws.slipDrawTarget(img), 0, 0, c.width, c.height);
    var wrapped = {
      naturalWidth: c.width,
      naturalHeight: c.height,
      width: c.width,
      height: c.height,
      complete: true,
      _slipCanvas: c,
      _slipReady: true,
      _slipDigital: digital,
      _raw: img._raw || img,
      _slipFileMeta: img._slipFileMeta,
      _slipMyAbl: img._slipMyAbl,
      src: img.src || '',
    };
    return wrapped;
  };

  Ws.normalizeSlipImage = function normalizeSlipImage(img) {
    return Ws.prepareSlipImage(img);
  };

  Ws.makeRegionCanvas = function makeRegionCanvas(img, region, scale, mode, opts) {
    opts = opts || {};
    scale = scale || 2;
    var px = opts.zonePadAlreadyApplied
      ? Ws.regionToPixelRect(img, region, 0, true)
      : Ws.regionToPixelRect(img, region, Ws.ZONE_PAD_PCT);
    if (!px) return null;
    var c = document.createElement('canvas');
    c.width = Math.max(24, Math.round(px.w * scale));
    c.height = Math.max(12, Math.round(px.h * scale));
    var ctx = c.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(Ws.slipDrawTarget(img), px.x, px.y, px.w, px.h, 0, 0, c.width, c.height);
    Ws.enhanceCanvas(ctx, c, mode || 'grayscale');
    return c;
  };

  Ws.makeUniversalScanCanvas = function makeUniversalScanCanvas(img) {
    img = Ws.prepareSlipImage(img);
    var size = Ws.imagePixelSize(img);
    var maxW = Ws.UNIVERSAL_SCAN_MAX_WIDTH;
    var scale = size.w > maxW ? maxW / size.w : 1;
    var c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(size.w * scale));
    c.height = Math.max(1, Math.round(size.h * scale));
    var ctx = c.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(Ws.slipDrawTarget(img), 0, 0, c.width, c.height);
    Ws.enhanceCanvas(ctx, c, 'grayscale');
    return c;
  };

  Ws.loadImageFromFile = function loadImageFromFile(file) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        img._slipFileMeta = file || null;
        img._slipDigital = Ws.isSlipDigital(img, file);
        resolve(img);
      };
      img.onerror = function () { reject(new Error('Image decode failed')); };
      img.src = URL.createObjectURL(file);
    });
  };

  Ws.ocrFullImageCached = function ocrFullImageCached(img) {
    img = Ws.prepareSlipImage(img);
    var key = img._raw || img;
    if (_fullTextCache.has(key)) return Promise.resolve(_fullTextCache.get(key));
    return Ws.prewarmWorker().then(function () {
      return Ws.ocrUniversalScan(Ws.makeUniversalScanCanvas(img));
    }).then(function (text) {
      _fullTextCache.set(key, text);
      return text;
    });
  };

})(window);
