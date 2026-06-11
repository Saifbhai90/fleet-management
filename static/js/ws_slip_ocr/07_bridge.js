/**
 * Workspace Slip OCR v2 — UI bridge & public API (WorkspaceSlipTemplate).
 */
(function (global) {
  'use strict';

  var Ws = global.WsSlipOcr;
  if (!Ws || !Ws.Parser || !Ws.Extract || !Ws.Profiles) {
    console.error('[ws-ocr] modules failed to load — check script order');
    return;
  }

  function extractFromSlip(file, profiles, options) {
    options = options || {};
    profiles = profiles || [];
    var preferredId = options.preferredProfileId || null;
    var onProgress = typeof options.onProgress === 'function' ? options.onProgress : null;
    var t0 = (typeof performance !== 'undefined' && performance.now) ? performance.now() : 0;

    function finish(data, label) {
      if (data && t0) {
        Ws.ocrLog(label || 'extract done', {
          ms: Math.round(performance.now() - t0),
          profile: data.profileName,
          quality: Ws.Extract.extractionQuality(data),
        });
      }
      return data;
    }

    function attachMeta(data, profile, score, fullText, img) {
      if (img) Ws.isMyAblSlip(img, fullText, profile);
      if (profile) {
        data.profileName = profile.name;
        data.profileId = profile.id;
        data.profile = profile;
      }
      data.matchScore = score;
      var prov = Ws.detectProviderFromText(fullText || data.ocrText || '');
      data.provider = prov ? prov.id : null;
      data.ocrText = fullText || data.ocrText || '';
      data.img = img;
      return data;
    }

    return Ws.loadImageFromFile(file)
      .then(function (img) { return Ws.warmOcrWorkersOnce().then(function () { return img; }); })
      .then(function (img) {
        var preferred = Ws.Profiles.findProfileById(profiles, preferredId);
        if (!preferred && profiles.length === 1) preferred = profiles[0];

        if (preferred && Ws.Profiles.profileHasAllZones(preferred) && options.instant !== false) {
          return Ws.Extract.extractZonesParallel(img, preferred, {
            onProgress: onProgress,
            profileName: preferred.name,
          }).then(function (data) {
            attachMeta(data, preferred, 1, data.ocrText, img);
            if (!Ws.Extract.isCompleteExtract(data)) {
              return Ws.Extract.extractGeneric(img, data.ocrText).then(function (generic) {
                Ws.FIELD_KEYS.forEach(function (k) {
                  if (!data[k] && generic[k]) {
                    data[k] = generic[k];
                    data.fieldMeta[k] = generic.fieldMeta[k];
                  }
                });
                return finish(data, 'extract hybrid-reinforced');
              });
            }
            return finish(data, 'extract instant');
          });
        }

        return Ws.ocrFullImageCached(img).then(function (fullText) {
          var ranked = Ws.Profiles.rankProfiles(profiles, fullText);
          var profile = preferred || (ranked[0] && ranked[0].profile);
          var score = preferred ? 1 : (ranked[0] ? ranked[0].score : 0);

          if (profile && Ws.Profiles.profileHasAllZones(profile)) {
            return Ws.Extract.extractZonesParallel(img, profile, {
              onProgress: onProgress,
              profileName: profile.name,
            }).then(function (data) {
              attachMeta(data, profile, score, fullText || data.ocrText, img);
              return finish(data, 'extract zonal');
            });
          }

          return Ws.Extract.extractGeneric(img, fullText).then(function (data) {
            attachMeta(data, profile, score, fullText, img);
            return finish(data, 'extract generic');
          });
        });
      });
  }

  function previewFieldRegion(img, fieldKey, region) {
    return Ws.prewarmWorker().then(function () {
      return Ws.Extract.previewField(img, fieldKey, region);
    });
  }

  function previewRegions(img, regionPayload) {
    var regions = regionPayload || {};
    return Ws.Extract.previewRegions(img, regions);
  }

  function buildFingerprintFromImage(img) {
    return Ws.prewarmWorker().then(function () {
      return Ws.ocrFullImageCached(img).then(function (text) {
        return { ocrText: text, keywords: Ws.Profiles.buildFingerprint(text) };
      });
    });
  }

  function buildFingerprintFromFile(file) {
    return Ws.loadImageFromFile(file).then(function (img) {
      return buildFingerprintFromImage(img).then(function (fp) {
        fp.img = img;
        return fp;
      });
    });
  }

  function ocrRegionField(img, region, fieldKey, opts) {
    opts = opts || {};
    return Ws.Extract.readZoneField(img, region, fieldKey, 0, opts.profile).then(function (zoneRes) {
      if (zoneRes && zoneRes.value && (zoneRes.confidence || 0) >= Ws.FALLBACK_CONFIDENCE) return zoneRes;
      return Ws.ocrFullImageCached(img).then(function (text) {
        var hunted = Ws.Parser.huntField(fieldKey, text);
        if (hunted) return Ws.fieldResult(hunted, 0.65, 'universal-fallback');
        return zoneRes || Ws.fieldResult(null, 0, 'none');
      });
    });
  }

  /**
   * Unified auto-fill policy + invisible DOM writes (focus, touch, TomSelect, OCR).
   */
  var AutoFill = (function () {
    var NAV = Ws.NAV_KEYS;
    var ID_MAP = Ws.FIELD_ID_MAP;
    var DEFAULTS = Ws.SELECT_DEFAULTS;

    function fieldKey(el) {
      if (!el) return null;
      if (el.id && ID_MAP[el.id]) return ID_MAP[el.id];
      return el.name || el.id || null;
    }

    function readValue(el) {
      if (!el) return '';
      if (el.tomselect) return String(el.tomselect.getValue() || '');
      return String(el.value != null ? el.value : '');
    }

    function isTomSelectBusy(el) {
      if (!el || !el.tomselect) return false;
      var ts = el.tomselect;
      if (ts.isOpen || (ts.dropdown && ts.dropdown.classList.contains('active'))) return true;
      var ci = ts.control_input;
      if (ci && String(ci.value || '').trim()) return true;
      var a = document.activeElement;
      if (ci && a === ci) return true;
      if (a && ts.wrapper && ts.wrapper.contains(a)) return true;
      return !!(ts.isFocused || (ts.wrapper && ts.wrapper.classList.contains('focus')));
    }

    /** Block OCR fill: TomSelect when busy; plain inputs only when focused AND non-empty. */
    function shouldBlockAutoFill(el, key) {
      if (!el) return true;
      if (el.tomselect) return isTomSelectBusy(el);
      if (hasContent(el, key)) return true;
      var a = document.activeElement;
      if (a !== el && !(el.contains && el.contains(a))) return false;
      return false;
    }

    function isDescriptionFocused(el) {
      if (!el) return false;
      var a = document.activeElement;
      return !!(a && (a === el || (el.contains && el.contains(a))));
    }

    function isFieldActive(el) {
      return shouldBlockAutoFill(el, fieldKey(el));
    }

    function isEmptyForFill(el, key) {
      key = key || fieldKey(el);
      if (!el) return true;
      if (el.tomselect) {
        var v = readValue(el);
        if (!v) return true;
        if (Object.prototype.hasOwnProperty.call(DEFAULTS, key) && v === DEFAULTS[key]) return true;
        return false;
      }
      return !String(el.value != null ? el.value : '').trim();
    }

    function silentTomSelectSet(el, value, opts) {
      opts = opts || {};
      if (!el) return false;
      if (el.tomselect) {
        var ts = el.tomselect;
        ts._wsSilentFill = true;
        try {
          if (opts.closeIfOpen && ts.isOpen) ts.close();
          ts.setValue(String(value), true);
        } finally {
          window.setTimeout(function () {
            ts._wsSilentFill = false;
          }, 120);
        }
      } else {
        el.value = String(value);
      }
      return true;
    }

    /** Payment Mode — native select + TomSelect display sync; never setValue/focus. */
    function ghostPaymentModeOnline(el) {
      if (!el) return false;
      var cur = readValue(el);
      if (cur === 'Online') return false;
      if (cur && cur !== 'Cash') return false;

      var value = 'Online';
      var prevFocus = document.activeElement;
      var scrollX = window.scrollX;
      var scrollY = window.scrollY;

      el.value = value;

      if (el.tomselect) {
        var ts = el.tomselect;
        ts._wsSilentFill = true;
        try {
          var nativeOpt = el.querySelector('option[value="' + value + '"]');
          var label = nativeOpt ? String(nativeOpt.textContent || '').trim() : value;
          if (!ts.options[value]) {
            ts.options[value] = { value: value, text: label };
          }
          ts.items = [value];
          ts.lastValue = value;
          var chip = ts.control ? ts.control.querySelector('.item') : null;
          if (chip) {
            chip.setAttribute('data-value', value);
            chip.textContent = label;
          }
        } finally {
          ts._wsSilentFill = false;
        }
      }

      if (scrollX !== window.scrollX || scrollY !== window.scrollY) {
        window.scrollTo(scrollX, scrollY);
      }
      if (prevFocus && document.body.contains(prevFocus) && document.activeElement !== prevFocus) {
        try {
          prevFocus.focus({ preventScroll: true });
        } catch (e) {
          try { prevFocus.focus(); } catch (e2) { /* ignore */ }
        }
      }

      return readValue(el) === value;
    }

    function hasContent(el, key) {
      key = key || fieldKey(el);
      if (!el || !key) return false;
      if (key === 'description') return !!String(el.value || '').trim();
      if (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && el.type !== 'hidden')) {
        return !!String(el.value || '').trim();
      }
      var v = readValue(el);
      if (!v) return false;
      return !(Object.prototype.hasOwnProperty.call(DEFAULTS, key) && v === DEFAULTS[key]);
    }

    function nativeSet(el, str) {
      try {
        var proto = el.tagName === 'TEXTAREA'
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
        var desc = Object.getOwnPropertyDescriptor(proto, 'value');
        if (desc && desc.set) {
          desc.set.call(el, str);
          return;
        }
      } catch (e) { /* fall through */ }
      el.value = str;
    }

    function create(config) {
      config = config || {};
      var touched = Object.create(null);
      var registry = [];
      var desc = { managed: false, last: '', el: null, build: null };
      var categoryEl = config.categoryEl || null;
      var slipAttachToken = 0;

      function register(el, key) {
        if (!el) return;
        key = key || fieldKey(el);
        registry.push({ el: el, key: key });
      }

      (config.fields || []).forEach(function (f) { register(f.el, f.key); });

      if (config.description) {
        desc.el = config.description.el || null;
        desc.build = config.description.build || null;
        if (desc.el) register(desc.el, 'description');
      }

      function wasTouched(key) { return !!touched[key]; }

      function markTouched(el, key) {
        key = key || fieldKey(el);
        if (key) touched[key] = true;
        if (key === 'description') desc.managed = false;
      }

      function findField(target) {
        if (!target) return null;
        for (var i = 0; i < registry.length; i++) {
          var r = registry[i];
          if (target === r.el) return r;
          if (r.el.tomselect && r.el.tomselect.control_input === target) return r;
          if (target._tsOrigSelect === r.el) return r;
          if (r.el.contains && r.el.contains(target)) return r;
        }
        return null;
      }

      function onDelegatedEvent(e) {
        if (global._wsOcrIsUpdating) return;
        var field = findField(e.target);
        if (!field) return;
        if (e.type === 'keydown' && NAV[e.key]) return;
        markTouched(field.el, field.key);
      }

      if (config.form) {
        config.form.addEventListener('input', onDelegatedEvent, true);
        config.form.addEventListener('change', onDelegatedEvent, true);
        config.form.addEventListener('keydown', onDelegatedEvent, true);
      }

      function canFill(el, key) {
        key = key || fieldKey(el);
        var result = false;
        var reason = 'unknown';
        if (!el || !key) {
          reason = 'missing el or key';
        } else if (isEmptyForFill(el, key)) {
          result = true;
          reason = 'empty override';
        } else if (wasTouched(key)) {
          reason = 'user touched';
        } else if (shouldBlockAutoFill(el, key)) {
          reason = 'focus or tomselect busy';
        } else if (hasContent(el, key)) {
          reason = 'has content';
        } else {
          result = true;
          reason = 'allowed';
        }
        try {
          console.log('[ws-ocr] canFill check for', key, 'Result:', result, 'Reason:', reason);
        } catch (logErr) { /* ignore */ }
        return result;
      }

      function setInputValue(el, value, key) {
        if (!el || value == null || value === '—') return false;
        key = key || fieldKey(el);
        if (readValue(el) === String(value)) return false;
        if (global._wsOcrIsUpdating) {
          nativeSet(el, String(value));
          return readValue(el) === String(value);
        }
        if (!canFill(el, key)) return false;
        nativeSet(el, String(value));
        return readValue(el) === String(value);
      }

      function setSelectValue(el, value, key) {
        if (!el || value == null || value === '—') return false;
        key = key || fieldKey(el);
        if (readValue(el) === String(value)) return false;
        if (global._wsOcrIsUpdating) {
          silentTomSelectSet(el, value);
          return readValue(el) === String(value);
        }
        if (!canFill(el, key)) return false;
        silentTomSelectSet(el, value);
        return readValue(el) === String(value);
      }

      function setPaymentModeOnline(el) {
        return ghostPaymentModeOnline(el);
      }

      /** OCR batch — lock focus; restore after (never touch TomSelect search text). */
      function runOcrIsolated(fn) {
        var lockedElement = document.activeElement;
        var scrollX = window.scrollX;
        var scrollY = window.scrollY;
        global._wsOcrIsUpdating = true;
        var result;
        try {
          result = fn();
        } finally {
          global._wsOcrIsUpdating = false;
          if (scrollX !== window.scrollX || scrollY !== window.scrollY) {
            window.scrollTo(scrollX, scrollY);
          }
          if (lockedElement && document.body.contains(lockedElement) &&
              document.activeElement !== lockedElement) {
            try {
              lockedElement.focus({ preventScroll: true });
            } catch (e) {
              try { lockedElement.focus(); } catch (e2) { /* ignore */ }
            }
          }
        }
        return result;
      }

      function runBatch(fn) {
        return runOcrIsolated(fn);
      }

      function ocrFillInput(el, key, value) {
        if (!el || value == null || value === '—') return false;
        if (String(el.value || '').trim() === String(value).trim()) return false;
        if (wasTouched(key) && hasContent(el, key) && !isEmptyForFill(el, key)) return false;
        nativeSet(el, String(value));
        return String(el.value || '').trim() === String(value).trim();
      }

      /**
       * Strict isolation: ONLY the 4 OCR targets by id — never From/To/Category.
       * No focus restore, no events, no TomSelect close on unrelated dropdowns.
       */
      function applyOcrExtracted(payload) {
        payload = payload || {};
        var ids = Ws.OCR_FIELD_IDS;
        var dateEl = payload.dateEl || document.getElementById(ids.date);
        var amountEl = payload.amountEl || document.getElementById(ids.amount);
        var refEl = payload.refEl || document.getElementById(ids.reference_no);
        var pmEl = payload.pmEl || document.getElementById(ids.payment_mode);
        var filled = runOcrIsolated(function () {
          var out = [];
          if (payload.date && payload.date !== '—' && dateEl &&
              ocrFillInput(dateEl, 'date', payload.date)) {
            out.push('date');
          }
          if (payload.amount && payload.amount !== '—' && amountEl) {
            var skipAmount = payload.skipAmount === true;
            if (!skipAmount && ocrFillInput(amountEl, 'amount', payload.amount)) {
              out.push('amount');
            }
          }
          if (payload.reference_no && payload.reference_no !== '—' && refEl &&
              ocrFillInput(refEl, 'reference_no', payload.reference_no)) {
            out.push('reference_no');
          }
          return out;
        });

        if (pmEl && ghostPaymentModeOnline(pmEl)) {
          filled.push('payment_mode');
        }
        if (typeof payload.onFilled === 'function') {
          payload.onFilled(filled);
        }
        return filled;
      }

      function focusCategoryOnce() {
        if (!categoryEl) return;
        var token = ++slipAttachToken;
        window.setTimeout(function () {
          if (token !== slipAttachToken) return;
          if (categoryEl.tomselect) {
            try { categoryEl.tomselect.focus(); } catch (e) { categoryEl.focus(); }
          } else {
            categoryEl.focus();
          }
        }, 50);
      }

      function enableDescriptionAuto() { desc.managed = true; }

      function releaseDescription() {
        desc.managed = false;
        markTouched(desc.el, 'description');
      }

      function onDescriptionInput(value) {
        if (value !== desc.last) markTouched(desc.el, 'description');
      }

      function writeDescription(text) {
        if (!desc.el || !text) return false;
        if (!desc.managed || wasTouched('description') || isDescriptionFocused(desc.el)) return false;
        if (readValue(desc.el) === text) return false;
        nativeSet(desc.el, text);
        return true;
      }

      function updateDescription(enableAuto) {
        if (!desc.el || !desc.build) return;
        if (enableAuto) desc.managed = true;
        if (!desc.managed || wasTouched('description') || isDescriptionFocused(desc.el)) return;
        var text = desc.build();
        if (!text) return;
        if (readValue(desc.el) === text) {
          desc.last = text;
          return;
        }
        runOcrIsolated(function () {
          if (writeDescription(text)) desc.last = text;
        });
      }

      function onSlipAttach() {
        focusCategoryOnce();
        updateDescription(true);
      }

      if (config.description && config.description.watch) {
        (config.description.watch || []).forEach(function (el) {
          if (el) el.addEventListener('change', function () { updateDescription(false); });
        });
      }

      if (desc.el && config.description && config.description.trackInput !== false) {
        desc.el.addEventListener('input', function () { onDescriptionInput(this.value); });
      }

      return {
        canFill: canFill,
        hasContent: hasContent,
        isFieldActive: isFieldActive,
        setInputValue: setInputValue,
        setSelectValue: setSelectValue,
        setPaymentModeOnline: setPaymentModeOnline,
        applyOcrExtracted: applyOcrExtracted,
        markTouched: markTouched,
        wasTouched: wasTouched,
        runBatch: runBatch,
        withFocusGuard: runBatch,
        fieldKey: fieldKey,
        focusCategory: focusCategoryOnce,
        enableDescriptionAuto: enableDescriptionAuto,
        releaseDescription: releaseDescription,
        updateDescription: updateDescription,
        onSlipAttach: onSlipAttach,
      };
    }

    return { create: create, isFieldActive: isFieldActive, readValue: readValue };
  })();

  global.WorkspaceSlipTemplate = {
    VERSION: Ws.VERSION,
    FIELD_LABELS: Ws.FIELD_LABELS,
    FIELD_COLORS: Ws.FIELD_COLORS,
    FIELD_TINTS: Ws.FIELD_TINTS,
    LOW_CONFIDENCE: Ws.LOW_CONFIDENCE,
    ensureTesseract: Ws.ensureTesseract,
    prewarmWorker: Ws.prewarmWorker,
    prewarmInstantWorkers: Ws.prewarmInstantWorkers,
    warmOcrWorkersOnce: Ws.warmOcrWorkersOnce,
    prepareOcrEngine: Ws.prepareOcrEngine,
    getLastOcrEngineError: Ws.getLastOcrEngineError,
    tesseractWorkerOptions: Ws.tesseractWorkerOptions,
    getWorker: Ws.getWorker,
    buildFingerprint: Ws.Profiles.buildFingerprint,
    buildFingerprintFromFile: buildFingerprintFromFile,
    buildFingerprintFromImage: buildFingerprintFromImage,
    loadImageFromFile: Ws.loadImageFromFile,
    extractFromSlip: extractFromSlip,
    extractGeneric: Ws.Extract.extractGeneric,
    previewRegions: previewRegions,
    previewFieldRegion: previewFieldRegion,
    ocrRegionField: ocrRegionField,
    regionToPixelRect: Ws.regionToPixelRect,
    logRegionMapping: Ws.logRegionMapping,
    makeRegionCanvas: Ws.makeRegionCanvas,
    parseDateFromText: Ws.Parser.parseDateFromText,
    parseAmountFromText: Ws.Parser.parseAmountFromText,
    parseReferenceFromText: Ws.Parser.parseReferenceFromText,
    parseReferenceFromZone: Ws.Parser.parseReferenceFromZone,
    rankProfiles: Ws.Profiles.rankProfiles,
    extractionQuality: Ws.Extract.extractionQuality,
    cacheProfiles: Ws.Profiles.cacheProfiles,
    readCachedProfiles: Ws.Profiles.readCachedProfiles,
    normalizeFieldValue: Ws.Profiles.normalizeFieldValue,
    fieldValuesMatch: Ws.Profiles.fieldValuesMatch,
    learnFieldCorrection: Ws.Profiles.learnFieldCorrection,
    validateAmountCandidate: Ws.Parser.validateAmountCandidate,
    parseProviderAmount: function () { return null; },
    isSlipDigital: Ws.isSlipDigital,
    isMyAblSlip: Ws.isMyAblSlip,
    normalizeSlipImage: Ws.normalizeSlipImage,
    ocrConfig: Ws.ocrConfig,
    enhanceCanvas: Ws.enhanceCanvas,
    createAutoFill: AutoFill.create,
    applyOcrExtractedIds: Ws.OCR_FIELD_IDS,
    detectProviderFromText: Ws.detectProviderFromText,
  };

})(window);
