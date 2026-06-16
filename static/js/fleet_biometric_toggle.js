/**
 * Professional biometric login — verify fingerprint on login screen, then save + dashboard.
 * Single source: fleet_bio_token + fleet_saved_username.
 */
(function(global) {
  'use strict';

  var KEYS = {
    token: 'fleet_bio_token',
    username: 'fleet_saved_username',
    name: 'fleet_saved_name',
    setupPending: 'fleet_bio_setup',
    setupPendingLocal: 'fleet_bio_setup_pending',
  };

  var LINK_SUCCESS_MSG = 'Biometric Verification Successful!';
  var PENDING_BIO_KEY = '_fleetPendingBioLink';
  var MAX_AUTO_BIO_FAILS = 3;
  var _bioAutoFailCount = 0;
  var _pendingRedirect = null;

  function isNative() {
    return !!(global.Capacitor && global.Capacitor.getPlatform && global.Capacitor.getPlatform() !== 'web');
  }

  function getPlugin() {
    if (!global.Capacitor || !global.Capacitor.Plugins) return null;
    var p = global.Capacitor.Plugins;
    return p.BiometricAuthNative || p.BiometricAuth || null;
  }

  function runAuth(bp, options) {
    if (typeof bp.internalAuthenticate === 'function') return bp.internalAuthenticate(options);
    if (typeof bp.authenticate === 'function') return bp.authenticate(options);
    if (typeof bp.verifyIdentity === 'function') return bp.verifyIdentity(options);
    return Promise.reject(new Error('Biometric plugin has no authenticate method'));
  }

  function timed(p, ms) {
    return Promise.race([
      p,
      new Promise(function(_, rej) {
        setTimeout(function() { rej({ code: 'timeout' }); }, ms);
      }),
    ]);
  }

  function isCanceled(err) {
    var code = String(err && (err.code || err.message || ''));
    return code === 'biometricCanceled' || code === '10' || code === 'userCanceled' ||
      code.indexOf('Cancel') !== -1 || code.indexOf('cancel') !== -1;
  }

  function toast(msg) {
    if (!msg) return;
    if (global.FleetBridge && typeof global.FleetBridge._toast === 'function') {
      global.FleetBridge._toast(msg);
      return;
    }
    if (global.fleetSessionSounds && typeof global.fleetSessionSounds.toast === 'function') {
      global.fleetSessionSounds.toast(msg);
    }
  }

  function alertMsg(msg) {
    if (msg) global.alert(msg);
  }

  function confirmMsg(msg) {
    return global.confirm(msg);
  }

  function confirmDisable() {
    var msg = 'Are you sure you want to disable Biometric Login? You will need to use your password next time.';
    if (global.Swal && typeof global.Swal.fire === 'function') {
      return global.Swal.fire({
        title: 'Disable Biometric Login?',
        text: msg,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, Disable',
        cancelButtonText: 'Cancel',
        confirmButtonColor: '#ef4444',
      }).then(function(r) { return !!(r && r.isConfirmed); });
    }
    return Promise.resolve(global.confirm(msg));
  }

  function hasLocalToken() {
    return !!global.localStorage.getItem(KEYS.token);
  }

  function hasSavedUsername() {
    return !!(global.localStorage.getItem(KEYS.username) || '').trim();
  }

  function getSavedDisplayName() {
    return global.localStorage.getItem(KEYS.name) ||
      global.localStorage.getItem(KEYS.username) ||
      'User';
  }

  function resolveLoginUsername() {
    var usernameEl = global.document.getElementById('login_username');
    var usernameField = global.document.getElementById('usernameField');
    var savedUser = (global.localStorage.getItem(KEYS.username) || '').trim();
    var savedMode = usernameField && usernameField.style.display === 'none' && savedUser;
    if (savedMode) return savedUser;
    return usernameEl ? usernameEl.value.trim() : '';
  }

  function isSetupPending() {
    return global.localStorage.getItem(KEYS.setupPendingLocal) === 'true' ||
      global.sessionStorage.getItem(KEYS.setupPending) === '1';
  }

  function clearSetupPending() {
    global.localStorage.removeItem(KEYS.setupPendingLocal);
    global.sessionStorage.removeItem(KEYS.setupPending);
  }

  function saveUserInfo(data) {
    if (data.username) global.localStorage.setItem(KEYS.username, data.username);
    if (data.display_name || data.username) {
      global.localStorage.setItem(KEYS.name, data.display_name || data.username);
    }
  }

  function saveCredentials(data) {
    if (data.token) global.localStorage.setItem(KEYS.token, data.token);
    saveUserInfo(data);
    clearSetupPending();
  }

  function clearLocalCredentials() {
    global.localStorage.removeItem(KEYS.token);
    clearSetupPending();
  }

  function clearSavedAccount() {
    global.localStorage.removeItem(KEYS.token);
    global.localStorage.removeItem(KEYS.username);
    global.localStorage.removeItem(KEYS.name);
    clearSetupPending();
  }

  function setToggleChecked(toggle, checked) {
    if (toggle) toggle.checked = !!checked;
  }

  function showLoginError(msg) {
    var el = global.document.getElementById('loginFormError');
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      el.style.display = 'block';
    } else {
      el.textContent = '';
      el.style.display = 'none';
    }
  }

  function showSavedError(msg) {
    var el = global.document.getElementById('hblLoginError');
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      el.style.display = 'block';
    } else {
      el.textContent = '';
      el.style.display = 'none';
    }
  }

  function updateSetupHint() {
    var hint = global.document.getElementById('loginBioSetupHint');
    var toggle = global.document.getElementById('loginBioToggle');
    if (!hint || !toggle) return;
    hint.style.display = (toggle.checked && !hasLocalToken()) ? 'block' : 'none';
  }

  function setSubmitLoading(loading) {
    var btn = global.document.getElementById('loginSubmitBtn');
    if (!btn) return;
    if (loading) {
      btn.classList.add('loading');
      btn.disabled = true;
    } else {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  }

  function setSavedLoginLoading(loading) {
    var btn = global.document.getElementById('hblSavedLoginBtn');
    if (!btn) return;
    if (loading) {
      btn.classList.add('loading');
      btn.disabled = true;
    } else {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  }

  function setSavedBioVerifying(loading, message) {
    var status = global.document.getElementById('hblBioStatus');
    var statusText = global.document.getElementById('hblBioStatusText');
    var bioMode = global.document.getElementById('hblBioMode');
    var thumb = global.document.getElementById('hblThumbBtn');
    var retry = global.document.getElementById('hblBioRetryBtn');
    if (statusText && message) statusText.textContent = message;
    if (status) status.classList.toggle('is-active', !!loading);
    if (bioMode) bioMode.classList.toggle('is-verifying', !!loading);
    if (thumb) {
      thumb.disabled = !!loading;
      if (loading) thumb.classList.remove('bio-thumb-pulse');
      else thumb.classList.add('bio-thumb-pulse');
    }
    if (retry) retry.disabled = !!loading;
  }

  function fetchEnableToken() {
    return fetch('/api/biometric/enable', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json',
      },
      body: '{}',
    }).then(function(r) {
      return r.text().then(function(text) {
        try {
          var data = JSON.parse((text || '').trim() || '{}');
          if (!r.ok && !data.error) {
            data.error = r.status === 401 ? 'Login session lost. Please try again.' : ('HTTP ' + r.status);
          }
          return data;
        } catch (e) {
          return {
            ok: false,
            error: r.status === 401 ? 'Login session lost. Please try again.' : ('Server error (HTTP ' + r.status + ')'),
          };
        }
      });
    });
  }

  function fetchDisableServer() {
    return fetch('/api/biometric/disable', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: '{}',
    }).then(function(r) { return r.json(); });
  }

  function parseLoginResponse(r, fallbackUser) {
    if (r.status >= 300 && r.status < 400) {
      var loc = r.headers.get('Location') || '/dashboard';
      return Promise.resolve({
        ok: true,
        redirect: loc,
        username: fallbackUser && fallbackUser.username,
        display_name: fallbackUser && fallbackUser.display_name,
      });
    }
    return r.text().then(function(text) {
      var trimmed = (text || '').trim();
      if (trimmed.charAt(0) === '{' || trimmed.charAt(0) === '[') {
        try {
          return JSON.parse(trimmed);
        } catch (e) { /* fall through */ }
      }
      var ct = r.headers.get('content-type') || '';
      if (ct.indexOf('application/json') !== -1) {
        try {
          return JSON.parse(trimmed);
        } catch (e2) {
          return { ok: false, error: 'Invalid JSON from server (HTTP ' + r.status + ')' };
        }
      }
      return { ok: false, error: 'Unexpected server response (HTTP ' + r.status + ')' };
    });
  }

  function ajaxPasswordLogin(opts) {
    opts = opts || {};
    var form = global.document.getElementById('loginForm');
    if (!form) return Promise.reject(new Error('Login form not found'));

    var formData = new FormData(form);
    var usernameVal = opts.username || (global.document.getElementById('login_username') || {}).value || '';
    if (opts.username) formData.set('username', opts.username);
    if (opts.password) formData.set('password', opts.password);
    formData.set('_fleet_ajax', '1');
    formData.set('submit', 'Login');
    if (opts.bioLink) formData.set('_fleet_bio_link', '1');

    var csrfInput = form.querySelector('input[name="csrf_token"]');
    if (csrfInput && csrfInput.value) {
      formData.set('csrf_token', csrfInput.value);
    }

    var fallbackUser = {
      username: (usernameVal || '').trim(),
      display_name: (usernameVal || '').trim(),
    };

    var ping = fetch('/auth/session-ping', {
      method: 'GET',
      credentials: 'same-origin',
      redirect: 'manual',
    }).catch(function() {});

    return ping.then(function() {
      return fetch('/login?ajax=1', {
        method: 'POST',
        credentials: 'same-origin',
        redirect: 'manual',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json',
        },
        body: formData,
      });
    }).then(function(r) {
      return parseLoginResponse(r, fallbackUser);
    });
  }

  function markAppSessionActive() {
    try {
      global.sessionStorage.setItem('_fleetAppSession', '1');
    } catch (e) { /* ignore */ }
  }

  function withFromLogin(url) {
    if (!url) url = '/dashboard';
    if (url.indexOf('from_login=1') !== -1) return url;
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'from_login=1';
  }

  function proceedToDashboard(redirectUrl) {
    markAppSessionActive();
    global.location.href = withFromLogin(redirectUrl || '/dashboard');
  }

  function askProceedWithoutBio(redirectUrl, reason) {
    var msg = reason
      ? (reason + '\n\nContinue to dashboard without biometric login?')
      : 'Continue to dashboard without biometric login?';
    if (confirmMsg(msg)) {
      proceedToDashboard(redirectUrl);
      return true;
    }
    return false;
  }

  function readPendingBioLink() {
    try {
      var raw = global.sessionStorage.getItem(PENDING_BIO_KEY);
      if (!raw) return null;
      var data = JSON.parse(raw);
      if (!data || !data.token) return null;
      if (data.ts && (Date.now() - data.ts) > 600000) {
        clearPendingBioLink();
        return null;
      }
      return data;
    } catch (e) {
      return null;
    }
  }

  function savePendingBioLink(data, redirectUrl) {
    if (!data || !data.token) return;
    try {
      global.sessionStorage.setItem(PENDING_BIO_KEY, JSON.stringify({
        redirect: redirectUrl || '/dashboard',
        token: data.token,
        username: data.username,
        display_name: data.display_name,
        ts: Date.now(),
      }));
    } catch (e) { /* ignore */ }
  }

  function clearPendingBioLink() {
    try {
      global.sessionStorage.removeItem(PENDING_BIO_KEY);
    } catch (e) { /* ignore */ }
    hideBioSetupOverlay();
  }

  function hideBioSetupOverlay() {
    var el = global.document.getElementById('fleetBioSetupOverlay');
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  function showBioSetupOverlay(pending, onRetry) {
    hideBioSetupOverlay();
    var wrap = global.document.createElement('div');
    wrap.id = 'fleetBioSetupOverlay';
    wrap.setAttribute('style',
      'position:fixed;inset:0;z-index:99998;background:rgba(15,23,42,0.88);' +
      'display:flex;align-items:center;justify-content:center;padding:24px;');
    wrap.innerHTML =
      '<div style="background:#fff;border-radius:16px;padding:28px 24px;max-width:320px;width:100%;text-align:center;">' +
      '<div style="font-size:1rem;font-weight:700;color:#0f172a;margin-bottom:8px;">Enable Fingerprint Login</div>' +
      '<div style="font-size:0.86rem;color:#64748b;margin-bottom:20px;line-height:1.45;">Verify your fingerprint to save biometric login for this account.</div>' +
      '<button type="button" id="fleetBioSetupThumb" style="width:80px;height:80px;border-radius:50%;border:2px solid #bfdbfe;background:#eff6ff;cursor:pointer;margin:0 auto 16px;display:flex;align-items:center;justify-content:center;">' +
      '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="1.8"><path d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 0 0 8 11a4 4 0 1 1 8 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0 0 15.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 0 0 8 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4"/></svg>' +
      '</button>' +
      '<button type="button" id="fleetBioSetupSkip" style="background:none;border:none;color:#64748b;font-size:0.85rem;text-decoration:underline;cursor:pointer;">Skip for now</button>' +
      '</div>';
    global.document.body.appendChild(wrap);
    var thumb = global.document.getElementById('fleetBioSetupThumb');
    var skip = global.document.getElementById('fleetBioSetupSkip');
    if (thumb) thumb.addEventListener('click', onRetry);
    if (skip) {
      skip.addEventListener('click', function() {
        var redirect = (pending && pending.redirect) || '/dashboard';
        clearPendingBioLink();
        toast('Biometric login not enabled. You can set it up later from Profile.');
        if (isLoginPage()) {
          proceedToDashboard(redirect);
        }
      });
    }
  }

  function isLoginPage() {
    var path = (global.location && global.location.pathname) || '';
    return path.indexOf('/login') !== -1;
  }

  function installBioResumeHandler() {
    if (global._fleetBioResumeInstalled || !isNative()) return;
    var app = global.Capacitor && global.Capacitor.Plugins && global.Capacitor.Plugins.App;
    if (!app || typeof app.addListener !== 'function') return;
    global._fleetBioResumeInstalled = true;
    app.addListener('appStateChange', function(state) {
      if (!state || !state.isActive) return;
      global.setTimeout(function() {
        tryCompletePendingBioLink(false);
      }, 700);
    });
  }

  function runPendingBioLinkPrompt(pending, onSaved) {
    if (!pending || !pending.token || hasLocalToken()) {
      clearPendingBioLink();
      return Promise.resolve(hasLocalToken() ? pending : null);
    }
    if (global._fleetBioLinkRunning) {
      return global._fleetBioLinkPromise || Promise.resolve(null);
    }
    var bp = getPlugin();
    if (!bp) {
      var msg = 'Biometric sensor unavailable.';
      if (isLoginPage()) showLoginError(msg);
      else toast(msg);
      return Promise.resolve(null);
    }

    global._fleetBioLinkRunning = true;
    global._fleetBioLinkPromise = timed(runAuth(bp, {
      androidTitle: 'FleetManager',
      reason: 'Verify your fingerprint to enable biometric login',
      cancelTitle: 'Cancel',
    }), 30000)
      .then(function() {
        finishBioLink(pending.redirect || '/dashboard', pending);
        clearPendingBioLink();
        hideBioSetupOverlay();
        if (typeof onSaved === 'function') onSaved(pending);
        return pending;
      })
      .catch(function(err) {
        var failMsg = isCanceled(err)
          ? 'Fingerprint cancelled. Tap below to try again.'
          : ((err && err.message) ? err.message : 'Fingerprint verification failed. Tap below to retry.');
        if (isLoginPage()) showLoginError(failMsg);
        else toast(failMsg);
        showBioSetupOverlay(pending, function() {
          runPendingBioLinkPrompt(pending, onSaved);
        });
        return null;
      })
      .then(function(result) {
        global._fleetBioLinkRunning = false;
        return result;
      });
    return global._fleetBioLinkPromise;
  }

  function afterPendingBioSaved(pending) {
    if (!pending) return;
    if (isLoginPage()) {
      proceedToDashboard(pending.redirect || '/dashboard');
    }
  }

  function tryCompletePendingBioLink(auto) {
    if (!isNative()) return;
    var pending = readPendingBioLink();
    if (!pending || hasLocalToken()) {
      clearPendingBioLink();
      return;
    }
    if (global.document.hidden) return;
    if (auto) {
      runPendingBioLinkPrompt(pending, afterPendingBioSaved);
      return;
    }
    showBioSetupOverlay(pending, function() {
      runPendingBioLinkPrompt(pending, afterPendingBioSaved);
    });
  }

  function initDashboardBioSetup() {
    if (!isNative()) return;
    installBioResumeHandler();
    if (!readPendingBioLink()) return;
    global.setTimeout(function() {
      tryCompletePendingBioLink(true);
    }, 800);
  }

  function finishBioLink(redirectUrl, userInfo) {
    saveCredentials(userInfo);
    toast(LINK_SUCCESS_MSG);
  }

  function linkBiometricAfterLogin(redirectUrl, userInfo) {
    if (!userInfo || !userInfo.token) {
      saveUserInfo(userInfo);
      proceedToDashboard(redirectUrl || '/dashboard');
      return Promise.resolve(userInfo);
    }

    markAppSessionActive();
    saveUserInfo(userInfo);
    savePendingBioLink(userInfo, redirectUrl);
    installBioResumeHandler();
    showLoginError('');

    var pending = readPendingBioLink();
    if (!pending) {
      proceedToDashboard(redirectUrl || '/dashboard');
      return Promise.resolve(userInfo);
    }

    return runPendingBioLinkPrompt(pending, afterPendingBioSaved).then(function(result) {
      setSubmitLoading(false);
      if (!result && !hasLocalToken()) {
        return userInfo;
      }
      return result || userInfo;
    });
  }

  function completeSetup() {
    if (!isSetupPending() || hasLocalToken()) {
      clearSetupPending();
      return Promise.resolve(null);
    }
    if (global._fleetBioCompleteSetupRunning) {
      return global._fleetBioCompleteSetupPromise || Promise.resolve(null);
    }
    global._fleetBioCompleteSetupRunning = true;
    global._fleetBioCompleteSetupPromise = fetchEnableToken()
      .then(function(data) {
        if (!data || !data.ok || !data.token) {
          throw new Error((data && data.error) || 'Could not link biometric login');
        }
        saveCredentials(data);
        alertMsg(LINK_SUCCESS_MSG);
        return data;
      })
      .catch(function(err) {
        console.warn('[Bio] completeSetup failed:', err);
        return null;
      })
      .then(function(result) {
        global._fleetBioCompleteSetupRunning = false;
        return result;
      });
    return global._fleetBioCompleteSetupPromise;
  }

  function showSavedAccountBiometricMode() {
    var bioMode = global.document.getElementById('hblBioMode');
    var pwdRow = global.document.getElementById('hblPasswordRow');
    var usePwd = global.document.getElementById('hblUsePassword');
    setSavedBioVerifying(false);
    if (bioMode) bioMode.style.display = 'block';
    if (pwdRow) pwdRow.style.display = 'none';
    if (usePwd) usePwd.style.display = 'inline-block';
    showSavedError('');
  }

  function showSavedAccountPasswordMode() {
    var bioMode = global.document.getElementById('hblBioMode');
    var pwdRow = global.document.getElementById('hblPasswordRow');
    var usePwd = global.document.getElementById('hblUsePassword');
    if (bioMode) bioMode.style.display = 'none';
    if (pwdRow) pwdRow.style.display = 'block';
    if (usePwd) usePwd.style.display = 'none';
    showSavedError('');
  }

  function showSavedAccountView() {
    var hblView = global.document.getElementById('hblSavedAccountView');
    var loginForm = global.document.getElementById('loginForm');
    var loginTitle = global.document.getElementById('loginTitle');
    var loginSub = global.document.getElementById('loginSubtitle');
    var hblName = global.document.getElementById('hblSavedName');
    var savedName = global.localStorage.getItem(KEYS.name);
    var savedUser = global.localStorage.getItem(KEYS.username);

    if (hblName) hblName.textContent = savedName || savedUser || 'User';
    if (hblView) hblView.style.display = 'block';
    if (loginForm) loginForm.style.display = 'none';
    if (loginTitle) loginTitle.style.display = 'none';
    if (loginSub) loginSub.style.display = 'none';
    showSavedAccountBiometricMode();
  }

  function showStandardForm() {
    var hblView = global.document.getElementById('hblSavedAccountView');
    var loginForm = global.document.getElementById('loginForm');
    var loginTitle = global.document.getElementById('loginTitle');
    var loginSub = global.document.getElementById('loginSubtitle');
    var setupRow = global.document.getElementById('loginBioSetupRow');
    var usernameField = global.document.getElementById('usernameField');
    var savedNameRow = global.document.getElementById('loginSavedNameRow');
    var otherRow = global.document.getElementById('loginOtherAccountRow');

    if (hblView) hblView.style.display = 'none';
    if (loginForm) loginForm.style.display = 'block';
    if (loginTitle) loginTitle.style.display = 'block';
    if (loginSub) loginSub.style.display = 'block';
    if (usernameField) usernameField.style.display = 'block';
    if (savedNameRow) savedNameRow.style.display = 'none';
    if (otherRow) otherRow.style.display = 'none';
    if (setupRow) setupRow.style.display = isNative() ? 'block' : 'none';
    setToggleChecked(global.document.getElementById('loginBioToggle'), false);
    setSavedBioVerifying(false);
    showLoginError('');
    updateSetupHint();
  }

  function showSavedPasswordLoginForm() {
    var hblView = global.document.getElementById('hblSavedAccountView');
    var loginForm = global.document.getElementById('loginForm');
    var loginTitle = global.document.getElementById('loginTitle');
    var loginSub = global.document.getElementById('loginSubtitle');
    var setupRow = global.document.getElementById('loginBioSetupRow');
    var usernameField = global.document.getElementById('usernameField');
    var savedNameRow = global.document.getElementById('loginSavedNameRow');
    var savedNameEl = global.document.getElementById('loginSavedDisplayName');
    var otherRow = global.document.getElementById('loginOtherAccountRow');
    var pwdEl = global.document.getElementById('login_password');

    if (hblView) hblView.style.display = 'none';
    if (loginForm) loginForm.style.display = 'block';
    if (loginTitle) loginTitle.style.display = 'block';
    if (loginSub) loginSub.style.display = 'none';
    if (usernameField) usernameField.style.display = 'none';
    if (savedNameRow) savedNameRow.style.display = 'block';
    if (savedNameEl) savedNameEl.textContent = getSavedDisplayName();
    if (otherRow) otherRow.style.display = 'block';
    if (setupRow) setupRow.style.display = 'block';
    setToggleChecked(global.document.getElementById('loginBioToggle'), false);
    setSavedBioVerifying(false);
    showLoginError('');
    updateSetupHint();

    global.setTimeout(function() {
      if (pwdEl && typeof pwdEl.focus === 'function') pwdEl.focus();
    }, 400);
  }

  function recordBiometricFail(reason) {
    _bioAutoFailCount += 1;
    if (reason) showSavedError(reason);
    if (_bioAutoFailCount >= MAX_AUTO_BIO_FAILS) {
      showSavedAccountPasswordMode();
      showSavedError('Fingerprint sign-in unavailable. Please enter your password.');
    }
  }

  function resetBiometricFailCount() {
    _bioAutoFailCount = 0;
    showSavedError('');
  }

  function performBiometricLogin() {
    if (!hasLocalToken()) return Promise.resolve(null);

    var bp = getPlugin();
    if (!bp) {
      showSavedAccountPasswordMode();
      showSavedError('Biometric sensor not available. Use your password.');
      return Promise.resolve(null);
    }

    var currentUser = global.localStorage.getItem(KEYS.username);
    var currentToken = global.localStorage.getItem(KEYS.token);
    if (!currentUser || !currentToken) {
      showStandardForm();
      return Promise.resolve(null);
    }

    setSavedBioVerifying(false);
    setSavedLoginLoading(false);
    showSavedError('');

    return timed(runAuth(bp, {
      androidTitle: 'FleetManager',
      reason: 'Verify your identity to sign in',
      cancelTitle: 'Cancel',
    }), 30000)
      .then(function() {
        setSavedBioVerifying(true, 'Signing you in…');
        return fetch('/auth/biometric-login', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body: JSON.stringify({ username: currentUser, token: currentToken }),
        });
      })
      .then(parseLoginResponse)
      .then(function(data) {
        if (data && data.ok) {
          resetBiometricFailCount();
          setSavedBioVerifying(true, 'Opening dashboard…');
          markAppSessionActive();
          global.location.href = withFromLogin(data.redirect || '/dashboard');
          return data;
        }
        setSavedBioVerifying(false);
        var errMsg = (data && data.error) || 'Biometric login failed';
        if (errMsg === 'Invalid token') {
          clearLocalCredentials();
          showStandardForm();
          alertMsg('Biometric token is invalid. Please sign in and enable biometric again.');
        } else {
          recordBiometricFail(errMsg + '. Try again or use your password.');
        }
        return data;
      })
      .catch(function(err) {
        setSavedBioVerifying(false);
        if (isCanceled(err)) {
          showSavedAccountPasswordMode();
          showSavedError('Fingerprint cancelled. Enter your password or tap the fingerprint icon to try again.');
          var pwdEl = global.document.getElementById('hblSavedPassword');
          if (pwdEl && typeof pwdEl.focus === 'function') {
            global.setTimeout(function() { pwdEl.focus(); }, 300);
          }
          return null;
        }
        var code = String(err && (err.code || err.message || ''));
        if (code === 'biometricNotEnrolled' || code === '6') {
          recordBiometricFail('No fingerprint enrolled on this device.');
        } else if (code === 'timeout') {
          recordBiometricFail('Fingerprint timed out. Please try again.');
        } else {
          recordBiometricFail('Connection error. Please try again.');
        }
        return null;
      });
  }

  function autoTrigger() {
    if (!isNative()) return;

    markAppSessionActive();

    var urlParams = new global.URLSearchParams(global.location.search);
    if (urlParams.get('clear_bio') === '1') {
      global.sessionStorage.clear();
      if (global.history && global.history.replaceState) {
        global.history.replaceState({}, global.document.title, global.location.pathname);
      }
    }

    resetBiometricFailCount();

    if (hasLocalToken() && hasSavedUsername()) {
      showSavedAccountView();
      global.setTimeout(function() {
        performBiometricLogin();
      }, 800);
    } else if (hasSavedUsername()) {
      showSavedPasswordLoginForm();
    } else {
      showStandardForm();
    }
  }

  function submitNativePasswordLogin(opts) {
    opts = opts || {};
    var username = opts.username || resolveLoginUsername();
    var password = opts.password || '';
    var passwordEl = global.document.getElementById('login_password');
    if (!password && passwordEl) password = passwordEl.value.trim();

    if (!username || !password) {
      var savedMode = !global.document.getElementById('usernameField') ||
        global.document.getElementById('usernameField').style.display === 'none';
      showLoginError(savedMode ? 'Please enter your password.' : 'Please enter your User ID and Password.');
      return Promise.resolve(null);
    }

    setSubmitLoading(true);
    showLoginError('');

    return ajaxPasswordLogin({
      username: username,
      password: password,
      bioLink: !!opts.bioLink,
    }).then(function(data) {
      if (!data || !data.ok) {
        setSubmitLoading(false);
        showLoginError((data && data.error) || 'Login failed. Please check your credentials.');
        return data;
      }
      if (data.token) {
        return linkBiometricAfterLogin(data.redirect || '/dashboard', data);
      }
      setSubmitLoading(false);
      saveUserInfo(data);
      proceedToDashboard(data.redirect || '/dashboard');
      return data;
    }).catch(function(err) {
      setSubmitLoading(false);
      showLoginError((err && err.message) || 'Network error. Please try again.');
      return null;
    });
  }

  function handlesLoginSubmit(e) {
    if (!isNative()) return false;

    e.preventDefault();
    showLoginError('');

    var loginBioToggle = global.document.getElementById('loginBioToggle');
    var wantsBioLink = !!(loginBioToggle && loginBioToggle.checked && !hasLocalToken());
    submitNativePasswordLogin({ bioLink: wantsBioLink });
    return true;
  }

  function enrollWithFingerprint(opts) {
    opts = opts || {};
    var bp = getPlugin();
    if (!bp) {
      alertMsg('Biometric plugin not found. Please reinstall or update the app.');
      return Promise.reject({ __handled: true });
    }

    return bp.checkBiometry().then(function(info) {
      if (!info || !(info.isAvailable || info.biometryIsAvailable || info.strongBiometryIsAvailable)) {
        throw { __handled: true, message: (info && info.reason) || 'Fingerprint not available' };
      }
      return runAuth(bp, {
        androidTitle: 'FleetManager',
        reason: opts.reason || 'Verify your fingerprint to enable biometric login',
        cancelTitle: 'Cancel',
      });
    }).then(function() {
      return fetchEnableToken();
    }).then(function(data) {
      if (!data || !data.ok || !data.token) {
        throw new Error((data && data.error) || 'Server error');
      }
      saveCredentials(data);
      alertMsg(LINK_SUCCESS_MSG);
      return data;
    });
  }

  function disableBiometric(opts) {
    opts = opts || {};
    return confirmDisable().then(function(yes) {
      if (!yes) {
        setToggleChecked(opts.toggle, true);
        return { ok: false, canceled: true };
      }
      var chain = Promise.resolve({ ok: true });
      if (opts.hasSession) {
        chain = fetchDisableServer().then(function(data) {
          if (!data || !data.ok) throw new Error((data && data.error) || 'Server error');
          return data;
        });
      }
      return chain.then(function() {
        clearLocalCredentials();
        setToggleChecked(opts.toggle, false);
        toast('Biometric login disabled');
        return { ok: true };
      });
    });
  }

  function handleToggleChange(toggle, opts) {
    opts = opts || {};
    if (!toggle) return Promise.resolve();
    if (!isNative()) {
      setToggleChecked(toggle, false);
      return Promise.resolve();
    }

    if (toggle.checked) {
      if (hasLocalToken() && !opts.forceReenroll) {
        return Promise.resolve({ ok: true, alreadyEnabled: true });
      }
      if (opts.onLoginScreen && !opts.hasSession) {
        updateSetupHint();
        return Promise.resolve({ ok: true, setupOnLogin: true });
      }
      return enrollWithFingerprint({
        reason: opts.enrollReason,
      }).catch(function(err) {
        setToggleChecked(toggle, false);
        updateSetupHint();
        if (err && err.__handled && err.message && !isCanceled(err)) {
          alertMsg('Fingerprint not available: ' + err.message);
        } else if (!isCanceled(err)) {
          alertMsg('Could not enable biometric login. Please try again.');
        }
        return { ok: false };
      });
    }

    if (opts.onLoginScreen && !opts.hasSession && !hasLocalToken()) {
      updateSetupHint();
      return Promise.resolve({ ok: true });
    }

    return disableBiometric({
      toggle: toggle,
      hasSession: !!opts.hasSession,
    }).catch(function() {
      setToggleChecked(toggle, true);
      alertMsg('Could not disable biometric login. Please try again.');
      return { ok: false };
    });
  }

  function syncProfileRow(toggle, statusEl) {
    if (!toggle) return;
    var token = hasLocalToken();
    var name = global.localStorage.getItem(KEYS.name) || global.localStorage.getItem(KEYS.username);
    setToggleChecked(toggle, !!token);
    if (statusEl) {
      if (token) {
        statusEl.textContent = 'Enabled for ' + (name || 'you');
        statusEl.style.color = '#16a34a';
      } else {
        statusEl.textContent = 'Tap to enable';
        statusEl.style.color = '';
      }
    }
  }

  function submitSavedAccountPassword() {
    var hblPassword = global.document.getElementById('hblSavedPassword');
    var savedUser = global.localStorage.getItem(KEYS.username);
    var pwd = hblPassword ? hblPassword.value.trim() : '';

    showSavedError('');
    if (!pwd) {
      if (hblPassword) hblPassword.focus();
      return;
    }
    if (!savedUser) {
      showStandardForm();
      return;
    }

    setSavedLoginLoading(true);

    ajaxPasswordLogin({ username: savedUser, password: pwd })
      .then(function(data) {
        setSavedLoginLoading(false);
        if (!data || !data.ok) {
          showSavedError((data && data.error) || 'Login failed. Please check your password.');
          return;
        }
        saveUserInfo(data);
        proceedToDashboard(data.redirect || '/dashboard');
      })
      .catch(function(err) {
        setSavedLoginLoading(false);
        showSavedError((err && err.message) || 'Network error. Please try again.');
      });
  }

  function bindLoginPageEvents() {
    var hblPwdToggle = global.document.getElementById('hblPwdToggle');
    var hblPassword = global.document.getElementById('hblSavedPassword');
    var hblOtherBtn = global.document.getElementById('hblOtherAccount');
    var hblLoginBtn = global.document.getElementById('hblSavedLoginBtn');
    var hblThumbBtn = global.document.getElementById('hblThumbBtn');
    var hblBioRetryBtn = global.document.getElementById('hblBioRetryBtn');
    var hblUsePassword = global.document.getElementById('hblUsePassword');
    var loginBioToggle = global.document.getElementById('loginBioToggle');

    if (hblPwdToggle && hblPassword) {
      hblPwdToggle.addEventListener('click', function() {
        var show = hblPassword.type === 'password';
        hblPassword.type = show ? 'text' : 'password';
        hblPwdToggle.className = show ? 'bi bi-eye-slash field-icon' : 'bi bi-eye field-icon';
      });
    }

    if (loginBioToggle) {
      loginBioToggle.addEventListener('change', function() {
        handleToggleChange(loginBioToggle, { onLoginScreen: true, hasSession: false })
          .then(function() { updateSetupHint(); });
      });
    }

    if (hblOtherBtn) {
      hblOtherBtn.addEventListener('click', function() {
        clearSavedAccount();
        resetBiometricFailCount();
        showStandardForm();
      });
    }

    var loginOtherBtn = global.document.getElementById('loginOtherAccountBtn');
    if (loginOtherBtn) {
      loginOtherBtn.addEventListener('click', function() {
        clearSavedAccount();
        resetBiometricFailCount();
        showStandardForm();
        var userEl = global.document.getElementById('login_username');
        if (userEl) userEl.value = '';
        var pwdEl = global.document.getElementById('login_password');
        if (pwdEl) pwdEl.value = '';
      });
    }

    if (hblThumbBtn) {
      hblThumbBtn.addEventListener('click', function() {
        performBiometricLogin();
      });
    }

    if (hblBioRetryBtn) {
      hblBioRetryBtn.addEventListener('click', function() {
        performBiometricLogin();
      });
    }

    if (hblUsePassword) {
      hblUsePassword.addEventListener('click', function() {
        showSavedAccountPasswordMode();
      });
    }

    if (hblLoginBtn) {
      hblLoginBtn.addEventListener('click', function() {
        submitSavedAccountPassword();
      });
    }
  }

  function initLoginPage() {
    if (!isNative()) return;
    try {
      markAppSessionActive();
      installBioResumeHandler();
      bindLoginPageEvents();
      autoTrigger();
      if (readPendingBioLink() && !hasLocalToken()) {
        global.setTimeout(function() {
          tryCompletePendingBioLink(true);
        }, 500);
      }
    } catch (err) {
      console.error('[Bio] initLoginPage failed:', err);
      showStandardForm();
    }
  }

  global.fleetBiometricToggle = {
    KEYS: KEYS,
    LINK_SUCCESS_MSG: LINK_SUCCESS_MSG,
    isNative: isNative,
    getPlugin: getPlugin,
    hasLocalToken: hasLocalToken,
    isSetupPending: isSetupPending,
    clearSetupPending: clearSetupPending,
    saveCredentials: saveCredentials,
    clearSavedAccount: clearSavedAccount,
    markAppSessionActive: markAppSessionActive,
    withFromLogin: withFromLogin,
    completeSetup: completeSetup,
    completeSetupAfterLogin: completeSetup,
    autoTrigger: autoTrigger,
    initLoginPage: initLoginPage,
    initDashboardBioSetup: initDashboardBioSetup,
    handlesLoginSubmit: handlesLoginSubmit,
    performBiometricLogin: performBiometricLogin,
    handleToggleChange: handleToggleChange,
    syncProfileRow: syncProfileRow,
    enrollWithFingerprint: enrollWithFingerprint,
    disableBiometric: disableBiometric,
    showSavedAccountView: showSavedAccountView,
    showSavedPasswordLoginForm: showSavedPasswordLoginForm,
    showStandardForm: showStandardForm,
  };
})(window);
