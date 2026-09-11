/**
 * Offline queue for Add/Edit Fuel Expense — IndexedDB + auto-sync on reconnect.
 */
(function (global) {
  'use strict';

  var DB_NAME = 'fleet_fuel_offline_v1';
  var DB_VERSION = 1;
  var STORE = 'pending_entries';

  function openDb() {
    return new Promise(function (resolve, reject) {
      if (!global.indexedDB) {
        reject(new Error('IndexedDB unavailable'));
        return;
      }
      var req = global.indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error || new Error('IndexedDB open failed')); };
    });
  }

  function toast(msg) {
    try {
      if (global.FleetBridge && typeof global.FleetBridge._toast === 'function') {
        global.FleetBridge._toast(msg);
        return;
      }
    } catch (e) { /* ignore */ }
    try {
      var host = document.getElementById('fleetOfflineToastHost');
      if (!host) {
        host = document.createElement('div');
        host.id = 'fleetOfflineToastHost';
        host.className = 'fleet-notif-toast-host';
        document.body.appendChild(host);
      }
      var el = document.createElement('div');
      el.className = 'fleet-notif-toast';
      el.textContent = msg;
      host.appendChild(el);
      setTimeout(function () {
        el.classList.add('fleet-notif-toast--out');
        setTimeout(function () { el.remove(); }, 300);
      }, 4200);
    } catch (e2) { /* ignore */ }
  }

  function blobToArrayBuffer(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(reader.error); };
      reader.readAsArrayBuffer(blob);
    });
  }

  function arrayBufferToBlob(buf, type) {
    return new Blob([buf], { type: type || 'application/octet-stream' });
  }

  function serializeFormData(formData) {
    var fields = [];
    var files = [];
    var promises = [];
    formData.forEach(function (value, key) {
      if (value instanceof File) {
        promises.push(blobToArrayBuffer(value).then(function (buf) {
          files.push({
            key: key,
            name: value.name,
            type: value.type || 'application/octet-stream',
            buffer: buf,
          });
        }));
      } else {
        fields.push({ key: key, value: String(value) });
      }
    });
    return Promise.all(promises).then(function () {
      return { fields: fields, files: files };
    });
  }

  function rebuildFormData(payload) {
    var fd = new FormData();
    (payload.fields || []).forEach(function (row) {
      fd.append(row.key, row.value);
    });
    var filePromises = (payload.files || []).map(function (f) {
      var blob = arrayBufferToBlob(f.buffer, f.type);
      var file = new File([blob], f.name || 'upload', { type: f.type || 'application/octet-stream' });
      fd.append(f.key, file, file.name);
    });
    return Promise.all(filePromises).then(function () { return fd; });
  }

  function savePending(formEl, submitter) {
    if (!formEl) return Promise.reject(new Error('No form'));
    var url = formEl.getAttribute('action') || global.location.href;
    var fd = new FormData(formEl);
    if (submitter && submitter.name) {
      fd.append(submitter.name, submitter.value || '');
    }
    return serializeFormData(fd).then(function (payload) {
      var entry = {
        url: url,
        createdAt: new Date().toISOString(),
        payload: payload,
      };
      return openDb().then(function (db) {
        return new Promise(function (resolve, reject) {
          var tx = db.transaction(STORE, 'readwrite');
          tx.objectStore(STORE).add(entry);
          tx.oncomplete = function () { db.close(); resolve(entry); };
          tx.onerror = function () { db.close(); reject(tx.error); };
        });
      });
    }).then(function () {
      toast('No internet — fuel entry saved offline. It will sync automatically when you are back online.');
      refreshPendingBar();
      if (global.navigator && global.navigator.serviceWorker && global.navigator.serviceWorker.ready) {
        global.navigator.serviceWorker.ready.then(function (reg) {
          if (reg.sync && typeof reg.sync.register === 'function') {
            reg.sync.register('fleet-fuel-sync').catch(function () {});
          }
        }).catch(function () {});
      }
    });
  }

  function listPending() {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, 'readonly');
        var req = tx.objectStore(STORE).getAll();
        req.onsuccess = function () { db.close(); resolve(req.result || []); };
        req.onerror = function () { db.close(); reject(req.error); };
      });
    });
  }

  function updatePendingEntry(entry) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).put(entry);
        tx.oncomplete = function () { db.close(); resolve(); };
        tx.onerror = function () { db.close(); reject(tx.error); };
      });
    });
  }

  function refreshPendingBar() {
    listPending().then(function (rows) {
      var bar = document.getElementById('fuelPendingSyncBar');
      if (!bar) return;
      var count = rows.length;
      bar.classList.toggle('d-none', count === 0);
      var txt = document.getElementById('fuelPendingSyncText');
      if (txt) {
        txt.textContent = count === 1
          ? '1 fuel entry saved offline — waiting to sync.'
          : count + ' fuel entries saved offline — waiting to sync.';
      }
    }).catch(function () { });
  }

  function sessionAlive() {
    return fetch('/expenses/fuel/add', {
      method: 'GET',
      credentials: 'same-origin',
      redirect: 'follow',
    }).then(function (resp) {
      return !(resp.redirected && /\/login\b/.test(resp.url || ''));
    }).catch(function () { return false; });
  }

  function deletePending(id) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).delete(id);
        tx.oncomplete = function () { db.close(); resolve(); };
        tx.onerror = function () { db.close(); reject(tx.error); };
      });
    });
  }

  // Replays one queued POST without following redirects so we can tell apart:
  //  - 'ok':       server redirected (302) and the session is still alive → saved.
  //  - 'auth':     server redirected to login → session expired, keep the entry.
  //  - 'rejected': server answered 200 with the form re-rendered → entry refused.
  //  - 'retry':    anything else (network/server error) → try again later.
  function syncOne(entry) {
    return rebuildFormData(entry.payload).then(function (fd) {
      return fetch(entry.url, {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
        redirect: 'manual',
      });
    }).then(function (resp) {
      if (resp.type === 'opaqueredirect' || resp.status === 0) {
        return sessionAlive().then(function (alive) { return alive ? 'ok' : 'auth'; });
      }
      if (resp.ok) { return 'rejected'; }
      return 'retry';
    });
  }

  var MAX_ENTRY_ATTEMPTS = 5;

  function syncPending() {
    if (!global.navigator.onLine) return Promise.resolve(0);
    return listPending().then(function (rows) {
      if (!rows.length) return 0;
      var stoppedForAuth = false;
      var rejected = 0;
      var chain = Promise.resolve(0);
      rows.forEach(function (entry) {
        chain = chain.then(function (synced) {
          if (stoppedForAuth) return synced;
          return syncOne(entry).then(function (outcome) {
            if (outcome === 'ok') {
              return deletePending(entry.id).then(function () { return synced + 1; });
            }
            if (outcome === 'auth') {
              stoppedForAuth = true;
              toast('Login required — pending fuel entries are kept and will sync after you log in again.');
              return synced;
            }
            if (outcome === 'rejected') {
              entry.attempts = (entry.attempts || 0) + 1;
              if (entry.attempts >= MAX_ENTRY_ATTEMPTS) {
                rejected += 1;
                return deletePending(entry.id).then(function () { return synced; });
              }
              return updatePendingEntry(entry).then(function () { return synced; });
            }
            return synced;
          }).catch(function () { return synced; });
        });
      });
      return chain.then(function (count) {
        if (count > 0) {
          var msg = count === 1
            ? '1 pending fuel entry synced to live server successfully.'
            : (count + ' pending fuel entries synced to live server successfully.');
          toast(msg);
        }
        if (rejected > 0) {
          toast(rejected === 1
            ? '1 offline fuel entry was rejected by the server after several tries and removed from the queue.'
            : (rejected + ' offline fuel entries were rejected by the server after several tries and removed from the queue.'));
        }
        refreshPendingBar();
        return count;
      });
    });
  }

  function submitWithOfflineFallback(formEl, submitter) {
    if (!formEl) return Promise.reject(new Error('No form'));
    var url = formEl.getAttribute('action') || global.location.href;
    var fd = new FormData(formEl);
    if (submitter && submitter.name) {
      fd.append(submitter.name, submitter.value || '');
    }
    if (!global.navigator.onLine) {
      return savePending(formEl, submitter);
    }
    // Manual redirect: the 302's flash stays in the session and is rendered by
    // the page we navigate to below — never consumed silently by fetch.
    return fetch(url, {
      method: 'POST',
      body: fd,
      credentials: 'same-origin',
      redirect: 'manual',
    }).then(function (resp) {
      if (resp.type === 'opaqueredirect' || resp.status === 0) {
        global.location.assign(url);
        return;
      }
      if (resp.ok) {
        // Server re-rendered the form (validation/business error). Keep the
        // user's data by letting the caller decide — default to a reload so
        // the server-rendered form (with bound values + flash) shows.
        global.location.reload();
        return;
      }
      throw new Error('Save failed (' + resp.status + ')');
    }).catch(function (err) {
      var offline = !global.navigator.onLine
        || (err && err.message && /failed to fetch|network|load/i.test(err.message));
      if (offline) {
        return savePending(formEl, submitter);
      }
      throw err;
    });
  }

  global.FuelExpenseOffline = {
    savePending: savePending,
    syncPending: syncPending,
    submitWithOfflineFallback: submitWithOfflineFallback,
    listPending: listPending,
    refreshPendingBar: refreshPendingBar,
    toast: toast,
  };

  global.addEventListener('online', function () {
    syncPending();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      refreshPendingBar();
      if (global.navigator.onLine) syncPending();
    });
  } else {
    refreshPendingBar();
    if (global.navigator.onLine) syncPending();
  }

  if (global.navigator.serviceWorker) {
    global.navigator.serviceWorker.addEventListener('message', function (ev) {
      if (ev.data && ev.data.type === 'fleet-fuel-sync') syncPending();
    });
  }
})(window);
