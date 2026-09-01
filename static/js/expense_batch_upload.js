/**
 * Shared split/batch attachment upload with retry UI for expense forms.
 * Used by Oil and Maintenance expense add forms.
 */
(function (global) {
  'use strict';

  function formatBytes(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
    return (n / 1073741824).toFixed(2) + ' GB';
  }

  function fileLabel(f) {
    if (!f) return 'file';
    var name = f.name || 'file';
    var sz = formatBytes(f.size || 0);
    return name + ' (' + sz + ')';
  }

  function buildBatches(fileList, fileLimit, byteLimit) {
    fileLimit = fileLimit || 12;
    byteLimit = byteLimit || (120 * 1024 * 1024);
    var batches = [];
    var cur = [];
    var curBytes = 0;
    for (var i = 0; i < fileList.length; i++) {
      var f = fileList[i];
      var sz = f.size || 0;
      if (cur.length > 0 && (cur.length >= fileLimit || (curBytes + sz > byteLimit))) {
        batches.push(cur);
        cur = [];
        curBytes = 0;
      }
      cur.push(f);
      curBytes += sz;
    }
    if (cur.length) batches.push(cur);
    return batches;
  }

  function ensureOverlay(opts) {
    var id = opts.overlayId;
    var ov = document.getElementById(id);
    var needsBuild = !ov || !ov.querySelector('.expense-batch-result-view');
    if (ov && needsBuild) {
      ov.remove();
      ov = null;
    }
    if (ov) return ov;
    ov = document.createElement('div');
    ov.id = id;
    ov.className = 'expense-batch-overlay d-none';
    ov.innerHTML =
      '<div class="expense-batch-panel ' + (opts.panelClass || '') + '">' +
        '<div class="expense-batch-progress-view">' +
          '<div class="fw-bold mb-1" data-role="title"></div>' +
          '<div class="small text-muted mb-2" data-role="detail"></div>' +
          '<div class="progress mb-2"><div data-role="bar" class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" style="width:0%">0%</div></div>' +
          '<div class="small text-secondary" data-role="hint">Browser se server par files bhej raha hai. Tab band na karein.</div>' +
        '</div>' +
        '<div class="expense-batch-result-view d-none">' +
          '<div class="d-flex align-items-start gap-2 mb-2">' +
            '<div class="expense-batch-result-icon text-danger"><i class="bi bi-exclamation-triangle-fill fs-3"></i></div>' +
            '<div class="flex-grow-1">' +
              '<div class="fw-bold" data-role="result-title">Upload incomplete</div>' +
              '<div class="small text-muted" data-role="result-sub"></div>' +
            '</div>' +
          '</div>' +
          '<div class="alert alert-warning py-2 px-3 small mb-2" data-role="result-alert"></div>' +
          '<div class="expense-batch-lists small mb-3" data-role="lists"></div>' +
          '<div class="d-flex flex-wrap gap-2 justify-content-end">' +
            '<button type="button" class="btn btn-outline-secondary btn-sm" data-role="btn-close">Close</button>' +
            '<a href="#" class="btn btn-outline-primary btn-sm" data-role="btn-list">Open list</a>' +
            '<button type="button" class="btn btn-danger btn-sm" data-role="btn-retry"><i class="bi bi-arrow-clockwise me-1"></i>Retry failed files</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    if (!document.getElementById('expenseBatchUploadStyles')) {
      var style = document.createElement('style');
      style.id = 'expenseBatchUploadStyles';
      style.textContent =
        '.expense-batch-overlay{position:fixed;inset:0;z-index:1070;background:rgba(15,23,42,.72);display:flex;align-items:center;justify-content:center;padding:1rem;}' +
        '.expense-batch-overlay.d-none{display:none!important;}' +
        '.expense-batch-panel{width:min(560px,100%);background:#fff;border-radius:14px;padding:1.1rem 1.2rem;box-shadow:0 18px 48px rgba(15,23,42,.28);max-height:min(88vh,720px);overflow:auto;}' +
        '.expense-batch-panel .progress{height:1.25rem;}' +
        '.expense-batch-lists details{border:1px solid #e2e8f0;border-radius:10px;padding:.55rem .7rem;margin-bottom:.5rem;background:#f8fafc;}' +
        '.expense-batch-lists summary{cursor:pointer;font-weight:600;color:#0f172a;}' +
        '.expense-batch-lists ul{margin:.45rem 0 0;padding-left:1.1rem;}' +
        '.expense-batch-lists li{margin:.15rem 0;word-break:break-word;}' +
        '.expense-batch-lists .ok{color:#15803d;}' +
        '.expense-batch-lists .fail{color:#b91c1c;}' +
        '.expense-batch-lists .pending{color:#a16207;}';
      document.head.appendChild(style);
    }
    document.body.appendChild(ov);
    return ov;
  }

  function showProgress(ov, title, detail, pct, hint) {
    var progress = ov.querySelector('.expense-batch-progress-view');
    var result = ov.querySelector('.expense-batch-result-view');
    if (progress) progress.classList.remove('d-none');
    if (result) result.classList.add('d-none');
    var t = ov.querySelector('[data-role="title"]');
    var d = ov.querySelector('[data-role="detail"]');
    var bar = ov.querySelector('[data-role="bar"]');
    var h = ov.querySelector('[data-role="hint"]');
    if (t) t.textContent = title || 'Saving...';
    if (d) d.textContent = detail || '';
    if (h && hint != null) h.textContent = hint;
    var safePct = (pct == null || isNaN(pct)) ? null : Math.max(0, Math.min(100, Math.round(pct)));
    if (bar) {
      bar.classList.remove('bg-danger', 'bg-success');
      if (safePct == null) {
        bar.style.width = '100%';
        bar.textContent = '...';
        bar.classList.add('progress-bar-animated');
      } else {
        bar.style.width = safePct + '%';
        bar.textContent = safePct + '%';
        if (safePct >= 100) bar.classList.remove('progress-bar-animated');
        else bar.classList.add('progress-bar-animated');
      }
    }
    ov.classList.remove('d-none');
  }

  function hideOverlay(ov) {
    if (ov) ov.classList.add('d-none');
  }

  function renderResult(ov, state) {
    var progress = ov.querySelector('.expense-batch-progress-view');
    var result = ov.querySelector('.expense-batch-result-view');
    if (progress) progress.classList.add('d-none');
    if (result) result.classList.remove('d-none');

    var okCount = 0;
    var failCount = 0;
    var pendingCount = 0;
    var listsHtml = '';
    state.batches.forEach(function (batch, idx) {
      var st = state.batchStatus[idx] || 'pending';
      var badge = st === 'ok' ? 'ok' : (st === 'failed' ? 'fail' : 'pending');
      var label = st === 'ok' ? 'Uploaded' : (st === 'failed' ? 'Failed' : 'Pending / not sent');
      if (st === 'ok') okCount += batch.length;
      else if (st === 'failed') failCount += batch.length;
      else pendingCount += batch.length;
      var openAttr = st !== 'ok' ? ' open' : '';
      listsHtml +=
        '<details' + openAttr + '>' +
          '<summary>Batch ' + (idx + 1) + ' — ' + batch.length + ' file(s) — <span class="' + badge + '">' + label + '</span></summary>' +
          '<ul>' + batch.map(function (f) {
            return '<li class="' + badge + '">' + fileLabel(f) + '</li>';
          }).join('') + '</ul>' +
        '</details>';
    });

    var titleEl = ov.querySelector('[data-role="result-title"]');
    var subEl = ov.querySelector('[data-role="result-sub"]');
    var alertEl = ov.querySelector('[data-role="result-alert"]');
    var listsEl = ov.querySelector('[data-role="lists"]');
    var btnList = ov.querySelector('[data-role="btn-list"]');
    var btnRetry = ov.querySelector('[data-role="btn-retry"]');
    var btnClose = ov.querySelector('[data-role="btn-close"]');

    if (titleEl) titleEl.textContent = 'Upload incomplete — kuch files fail hui hain';
    if (subEl) {
      subEl.textContent = state.expenseId
        ? ('Bill pehle save ho chuka hai (#' + state.expenseId + '). Duplicate Save mat karein.')
        : 'Bill save hone se pehle error aaya.';
    }
    if (alertEl) {
      alertEl.innerHTML =
        '<div><strong>' + (state.lastError || 'Network / upload error') + '</strong></div>' +
        '<div class="mt-1">Uploaded: <strong>' + okCount + '</strong> &nbsp;|&nbsp; Failed: <strong>' + failCount + '</strong> &nbsp;|&nbsp; Pending: <strong>' + pendingCount + '</strong></div>' +
        '<div class="mt-1 text-muted">Neeche list me har batch ki files dikh rahi hain. Retry sirf failed + pending files dubara bhejega.</div>';
    }
    if (listsEl) listsEl.innerHTML = listsHtml;
    if (btnList) {
      btnList.href = state.listUrl || '#';
      btnList.classList.toggle('d-none', !state.listUrl);
    }
    if (btnRetry) {
      btnRetry.disabled = !(failCount + pendingCount) || !state.expenseId;
    }

    btnClose.onclick = function () {
      hideOverlay(ov);
      if (typeof state.onClose === 'function') state.onClose();
    };
    btnRetry.onclick = function () {
      if (typeof state.onRetry === 'function') state.onRetry();
    };
    ov.classList.remove('d-none');
  }

  function uploadBatchXhr(opts) {
    return new Promise(function (resolve, reject) {
      var fd = new FormData();
      opts.files.forEach(function (f) { fd.append('attachments', f, f.name || 'file'); });
      var xhr = new XMLHttpRequest();
      xhr.open('POST', opts.url);
      xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
      if (opts.csrf) xhr.setRequestHeader('X-CSRFToken', opts.csrf);
      if (opts.isFinal && opts.finalHeader) xhr.setRequestHeader(opts.finalHeader, '1');
      xhr.upload.addEventListener('progress', function (ev) {
        if (opts.onProgress) opts.onProgress(ev);
      });
      xhr.onload = function () {
        try {
          var j = JSON.parse(xhr.responseText || '{}');
          if (xhr.status >= 200 && xhr.status < 400 && j.ok) {
            resolve(j);
            return;
          }
          reject(new Error((j && j.error) ? j.error : ('Batch HTTP ' + xhr.status)));
        } catch (err) {
          reject(err);
        }
      };
      xhr.onerror = function () {
        reject(new Error('Network error on batch ' + (opts.batchIdx + 1)));
      };
      xhr.ontimeout = function () {
        reject(new Error('Timeout on batch ' + (opts.batchIdx + 1)));
      };
      xhr.timeout = opts.timeoutMs || 0;
      xhr.send(fd);
    });
  }

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  /**
   * @param {object} cfg
   * @param {string} cfg.overlayId
   * @param {string} [cfg.panelClass]
   * @param {File[]} cfg.fileList
   * @param {number} cfg.totalBytes
   * @param {function(): string} cfg.getCsrf
   * @param {function(): Promise<{id:number, list_url?:string}>} cfg.saveFormWithoutFiles
   * @param {function(number): string} cfg.queueUrl
   * @param {string} cfg.finalHeader  e.g. X-Oil-Batch-Final
   * @param {number} [cfg.fileLimit]
   * @param {number} [cfg.byteLimit]
   * @param {boolean} [cfg.autoRetryOnce=true]
   * @param {function()} [cfg.onUnlock]
   * @param {function(string)} [cfg.onSuccessRedirect]
   */
  function runSplitUpload(cfg) {
    var ov = ensureOverlay(cfg);
    var batches = buildBatches(cfg.fileList, cfg.fileLimit, cfg.byteLimit);
    var state = {
      expenseId: null,
      listUrl: null,
      batches: batches,
      batchStatus: batches.map(function () { return 'pending'; }),
      lastError: '',
      autoRetryUsed: false,
      onClose: null,
      onRetry: null
    };

    function markFailedFrom(idx, err) {
      state.lastError = (err && err.message) ? err.message : String(err || 'Upload failed');
      for (var i = idx; i < state.batchStatus.length; i++) {
        if (state.batchStatus[i] !== 'ok') {
          state.batchStatus[i] = (i === idx) ? 'failed' : 'pending';
        }
      }
    }

    function uploadFrom(startIdx, isAutoRetry) {
      var total = batches.length;
      var chain = Promise.resolve();
      for (var i = startIdx; i < total; i++) {
        (function (idx) {
          chain = chain.then(function () {
            if (state.batchStatus[idx] === 'ok') return null;
            showProgress(
              ov,
              (isAutoRetry ? 'Auto-retry: ' : '') + 'Batch ' + (idx + 1) + ' / ' + total + ' upload ho rahi hai',
              batches[idx].length + ' file(s) — ' + formatBytes(cfg.totalBytes) + ' total',
              Math.round((idx / total) * 100),
              isAutoRetry
                ? 'Network fail ke baad automatic retry… Tab band na karein.'
                : 'Browser se server par files bhej raha hai. Tab band na karein.'
            );
            return uploadBatchXhr({
              url: cfg.queueUrl(state.expenseId),
              files: batches[idx],
              batchIdx: idx,
              isFinal: idx === total - 1,
              finalHeader: cfg.finalHeader,
              csrf: cfg.getCsrf(),
              onProgress: function (ev) {
                if (!ev.lengthComputable || !ev.total) return;
                var within = (ev.loaded / ev.total) * (100 / total);
                var pct = Math.round(((idx / total) * 100) + within);
                showProgress(
                  ov,
                  (isAutoRetry ? 'Auto-retry: ' : '') + 'Batch ' + (idx + 1) + ' / ' + total + ' upload ho rahi hai',
                  formatBytes(ev.loaded) + ' / ' + formatBytes(ev.total),
                  Math.min(99, pct)
                );
              }
            }).then(function () {
              state.batchStatus[idx] = 'ok';
            }).catch(function (err) {
              markFailedFrom(idx, err);
              throw err;
            });
          });
        })(i);
      }
      return chain;
    }

    function finishOk() {
      showProgress(ov, 'Upload queue me lag gayi', 'Background me Cloudflare par jaa rahi hain — list par status dekhein.', 100);
      var listUrl = state.listUrl || '/';
      window.setTimeout(function () {
        if (typeof cfg.onSuccessRedirect === 'function') cfg.onSuccessRedirect(listUrl);
        else window.location.href = listUrl;
      }, 600);
    }

    function showFailPanel() {
      state.onClose = function () {
        if (typeof cfg.onUnlock === 'function') cfg.onUnlock();
      };
      state.onRetry = function () {
        var start = 0;
        while (start < state.batchStatus.length && state.batchStatus[start] === 'ok') start += 1;
        showProgress(ov, 'Retry shuru…', 'Failed / pending files dubara bhej rahe hain', 0);
        uploadFrom(start, false).then(finishOk).catch(function () {
          // One more automatic retry on network errors during manual retry? Keep panel.
          if (!state.autoRetryUsed && /network|timeout/i.test(state.lastError || '')) {
            state.autoRetryUsed = true;
            showProgress(ov, 'Network fail — 2s baad auto-retry…', state.lastError, null);
            sleep(2000).then(function () {
              var s2 = 0;
              while (s2 < state.batchStatus.length && state.batchStatus[s2] === 'ok') s2 += 1;
              return uploadFrom(s2, true);
            }).then(finishOk).catch(function () {
              showFailPanel();
            });
            return;
          }
          showFailPanel();
        });
      };
      renderResult(ov, state);
    }

    showProgress(
      ov,
      'Form save ho raha hai',
      cfg.fileList.length + ' file(s), ' + batches.length + ' batch(es) — please wait',
      0
    );

    return cfg.saveFormWithoutFiles().then(function (saved) {
      state.expenseId = saved.id;
      state.listUrl = saved.list_url || cfg.fallbackListUrl || '';
      return uploadFrom(0, false).then(finishOk).catch(function () {
        var allowAuto = cfg.autoRetryOnce !== false;
        if (allowAuto && !state.autoRetryUsed && /network|timeout/i.test(state.lastError || '')) {
          state.autoRetryUsed = true;
          showProgress(ov, 'Network fail — 2s baad auto-retry…', state.lastError, null,
            'Batch fail hui. System khud ek dafa retry karega.');
          return sleep(2000).then(function () {
            var start = 0;
            while (start < state.batchStatus.length && state.batchStatus[start] === 'ok') start += 1;
            return uploadFrom(start, true);
          }).then(finishOk).catch(function () {
            showFailPanel();
          });
        }
        showFailPanel();
      });
    }).catch(function (err) {
      // Save itself failed — no expense id
      state.lastError = (err && err.message) ? err.message : String(err || 'Save failed');
      state.batchStatus = state.batchStatus.map(function () { return 'pending'; });
      if (typeof cfg.onUnlock === 'function') cfg.onUnlock();
      showProgress(ov, 'Save fail', state.lastError, 0);
      // Simple fail without retry for save errors
      state.onClose = function () {
        if (typeof cfg.onUnlock === 'function') cfg.onUnlock();
      };
      state.onRetry = function () {
        hideOverlay(ov);
        if (typeof cfg.onUnlock === 'function') cfg.onUnlock();
      };
      var btnRetry = ov.querySelector('[data-role="btn-retry"]');
      if (btnRetry) {
        btnRetry.textContent = 'Close & fix form';
      }
      renderResult(ov, state);
      var alertEl = ov.querySelector('[data-role="result-alert"]');
      if (alertEl) {
        alertEl.innerHTML = '<div><strong>' + state.lastError + '</strong></div>' +
          '<div class="mt-1">Bill abhi save nahi hua. Form check karke dubara Save karein.</div>';
      }
      var titleEl = ov.querySelector('[data-role="result-title"]');
      if (titleEl) titleEl.textContent = 'Form save nahi hua';
    });
  }

  global.ExpenseBatchUpload = {
    formatBytes: formatBytes,
    buildBatches: buildBatches,
    runSplitUpload: runSplitUpload,
    showProgress: function (cfg, title, detail, pct) {
      var ov = ensureOverlay(cfg);
      showProgress(ov, title, detail, pct);
      return ov;
    },
    hide: function (overlayId) {
      hideOverlay(document.getElementById(overlayId));
    }
  };
})(window);
