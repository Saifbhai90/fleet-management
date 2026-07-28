package com.fleetmanager.app;

import android.Manifest;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.ContentValues;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.view.View;
import android.view.ViewGroup;
import android.util.Log;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.provider.MediaStore;
import android.webkit.URLUtil;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;
import android.app.DownloadManager;
import android.content.Context;
import android.text.TextUtils;

import androidx.annotation.NonNull;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeActivity;
import com.google.android.gms.common.ConnectionResult;
import com.google.android.gms.common.GoogleApiAvailability;
import com.google.firebase.FirebaseApp;
import com.google.firebase.installations.FirebaseInstallations;
import com.google.firebase.messaging.FirebaseMessaging;

import android.webkit.JavascriptInterface;
import org.json.JSONObject;
import java.io.OutputStream;
import java.util.Locale;
import java.util.Timer;
import java.util.TimerTask;

public class MainActivity extends BridgeActivity implements FleetBridgeWebViewClient.LoadStateCallback {

    private static final String PREFS_NAME = "fcm_prefs";
    private static final String KEY_USE_POLLING = "use_polling";
    private static final String KEY_FIS_ID = "fis_installation_id";
    private static final String KEY_FCM_TOKEN = "fcm_token";

    private static final int MAX_RETRY_ATTEMPTS = 3;
    private static final long INITIAL_BACKOFF_MS = 3000;
    private static final long GMS_TOKEN_TIMEOUT_MS = 15000;
    private static final long POLLING_ACTIVATION_DEADLINE_MS = 60000;
    private static final int BATTERY_OPT_REQUEST = 9999;
    private static final int NOTIF_PERMISSION_REQUEST = 1001;
    private static final int LOCATION_PERMISSION_REQUEST = 1002;
    /** Splash shows for at least this long for branding, then hides once the app page loads. */
    private static final long SPLASH_MIN_MS = 800L;
    /** Hard safety cap: splash is always hidden by this point even if the page never loads. */
    private static final long SPLASH_MAX_MS = 10000L;
    private static final long AUTO_RETRY_MS = 5000L;

    private volatile boolean tokenResolved = false;
    private volatile boolean splashHidden = false;
    private Handler mainHandler;
    private Timer deadlineTimer;
    private SharedPreferences prefs;

    private View networkOverlayRoot;
    private TextView networkAutoRetryText;
    private Button networkRetryBtn;
    private boolean networkOverlayVisible = false;
    private boolean appPageLoaded = false;
    private boolean minSplashDone = false;
    private boolean webViewGuardReady = false;
    private boolean webViewMainFrameFailed = false;
    private int webViewReloadAttempts = 0;
    private static final int MAX_RELOAD_ATTEMPTS = 3;
    private String pendingNotificationLink = null;
    private String appliedNotificationLink = null;

    // ── Branded Loading Overlay (modern CRM-style startup screen) ────────────────
    private View loadingOverlayRoot;
    private TextView loadingStatusText;
    private android.widget.ImageView[] loadingDots = new android.widget.ImageView[3];
    private int loadingDotIndex = 0;
    private int loadingStatusIndex = 0;
    private boolean loadingOverlayVisible = false;
    private final Runnable loadingDotRunnable = new Runnable() {
        @Override
        public void run() {
            if (!loadingOverlayVisible) return;
            // Pulse each dot: the "active" one bright, others dim.
            for (int i = 0; i < 3; i++) {
                if (loadingDots[i] != null) {
                    loadingDots[i].setAlpha(i == loadingDotIndex ? 1.0f : 0.3f);
                }
            }
            loadingDotIndex = (loadingDotIndex + 1) % 3;
            // Cycle the status text every 2 dot rotations (~1.4s).
            if (loadingDotIndex == 0) {
                loadingStatusIndex = (loadingStatusIndex + 1) % FLEET_LOADING_STATUSES.length;
                if (loadingStatusText != null) {
                    loadingStatusText.setText(FLEET_LOADING_STATUSES[loadingStatusIndex]);
                }
            }
            mainHandler.postDelayed(this, 350);
        }
    };
    private static final String[] FLEET_LOADING_STATUSES = {
        "Connecting to server...",
        "Loading application...",
        "Almost there..."
    };
    /** null = still probing; TRUE = server reachable; FALSE = confirmed unreachable. */
    private Boolean serverReachable = null;
    private ConnectivityManager.NetworkCallback networkCallback;
    private final Runnable autoRetryRunnable = new Runnable() {
        @Override
        public void run() {
            if (!networkOverlayVisible) {
                return;
            }
            pulseAutoRetryLabel();
            probeServerAndMaybeReload(false);
            mainHandler.postDelayed(this, AUTO_RETRY_MS);
        }
    };
    private final Runnable splashMinRunnable = () -> {
        minSplashDone = true;
        // Minimum branding time elapsed → swap native splash for the branded loading
        // overlay IMMEDIATELY (don't wait for the 10s safety cap). This is the single
        // transition point: native splash → branded loading → app page. No black gap.
        if (!appPageLoaded) {
            hideSplash();   // hideSplash() will then call showLoadingOverlay()
        }
        evaluatePostSplashNetworkState();
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        handleNotificationIntent(getIntent());
        getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        registerPlugin(AttendanceFrontCameraPlugin.class);
        registerPlugin(FleetApkDownloadPlugin.class);
        mainHandler = new Handler(Looper.getMainLooper());
        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        setupNetworkOverlay();
        setupLoadingOverlay();
        runServerProbe();
        mainHandler.postDelayed(splashMinRunnable, SPLASH_MIN_MS);
        // Hard safety cap: ensure splash is ALWAYS hidden, even if the page load stalls
        // or never fires onPageFinished. Prevents the "stuck splash / black screen" case.
        mainHandler.postDelayed(this::hideSplash, SPLASH_MAX_MS);

        // Firebase init on background thread — don't block app startup.
        // If Firebase fails, polling fallback starts immediately. WebView loads regardless.
        new Thread(() -> {
            boolean firebaseOk = initializeFirebase();
            if (firebaseOk) {
                runOnUiThread(() -> {
                    checkGooglePlayServices();
                    FirebaseMessaging.getInstance().setAutoInitEnabled(true);
                    startTokenAcquisition();
                    schedulePollingActivation();
                });
            } else {
                Log.w("FleetFirebase", "Firebase init failed — starting polling fallback");
                prefs.edit().putBoolean(KEY_USE_POLLING, true).apply();
                runOnUiThread(this::startPollingService);
            }
        }, "FirebaseInit").start();

        // These don't depend on Firebase — continue immediately on main thread
        createNotificationChannels();
        requestNotificationPermission();
        requestLocationPermission();
        requestBatteryOptimizationExemption();

        setupDownloadListener();
        getWindow().setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        scheduleWebViewTransparent();

        // App window background = branding color (#0f172a) so the user never sees a raw
        // BLACK screen while the WebView is loading or on slow networks. Previously the window
        // was transparent, which let a default black surface show through before content painted.
        getWindow().getDecorView().setBackgroundColor(Color.parseColor("#0f172a"));
    }

    private void setupNetworkOverlay() {
        ViewGroup content = findViewById(android.R.id.content);
        if (content == null) {
            return;
        }
        networkOverlayRoot = getLayoutInflater().inflate(R.layout.overlay_network_error, content, false);
        content.addView(networkOverlayRoot);
        networkAutoRetryText = networkOverlayRoot.findViewById(R.id.fleetNetworkAutoRetry);
        networkRetryBtn = networkOverlayRoot.findViewById(R.id.fleetNetworkRetryBtn);
        if (networkRetryBtn != null) {
            networkRetryBtn.setOnClickListener(v -> retryWebViewLoad());
        }
    }

    /** Inflate the branded loading overlay on top of the WebView (but below network overlay).
     *  Shown right after the native splash hides, dismissed once the app page finishes loading.
     *  This is the "modern CRM/ERP" pattern: user always sees live progress, never a black screen. */
    private void setupLoadingOverlay() {
        ViewGroup content = findViewById(android.R.id.content);
        if (content == null) return;
        loadingOverlayRoot = getLayoutInflater().inflate(R.layout.overlay_loading, content, false);
        content.addView(loadingOverlayRoot);
        loadingStatusText = loadingOverlayRoot.findViewById(R.id.fleetLoadingStatus);
        loadingDots[0] = loadingOverlayRoot.findViewById(R.id.fleetDot1);
        loadingDots[1] = loadingOverlayRoot.findViewById(R.id.fleetDot2);
        loadingDots[2] = loadingOverlayRoot.findViewById(R.id.fleetDot3);
    }

    private void showLoadingOverlay() {
        if (loadingOverlayRoot == null) return;
        if (loadingOverlayVisible) return;
        loadingOverlayVisible = true;
        loadingOverlayRoot.setVisibility(View.VISIBLE);
        loadingDotIndex = 0;
        loadingStatusIndex = 0;
        if (loadingStatusText != null) loadingStatusText.setText(FLEET_LOADING_STATUSES[0]);
        mainHandler.removeCallbacks(loadingDotRunnable);
        mainHandler.post(loadingDotRunnable);
    }

    private void hideLoadingOverlay() {
        if (!loadingOverlayVisible) return;
        loadingOverlayVisible = false;
        mainHandler.removeCallbacks(loadingDotRunnable);
        if (loadingOverlayRoot != null) loadingOverlayRoot.setVisibility(View.GONE);
    }

    private void setupWebViewNetworkGuard() {
        if (webViewGuardReady) {
            return;
        }
        Bridge bridge = getBridge();
        if (bridge == null || bridge.getWebView() == null) {
            return;
        }
        WebView wv = bridge.getWebView();
        wv.setWebViewClient(new FleetBridgeWebViewClient(bridge, this));
        webViewGuardReady = true;
    }

    /** Configure the WebView once it is ready. Opaque background + HTTP cache enabled
     *  so the server's Brotli + Cache-Control headers actually speed up repeat loads.
     *  (Camera capture is a separate native Activity, so the WebView no longer needs to be
     *  transparent — fixing the black-screen-on-slow-network issue.) */
    private void scheduleWebViewTransparent() {
        if (mainHandler == null) {
            mainHandler = new Handler(Looper.getMainLooper());
        }
        mainHandler.post(() -> {
            if (getBridge() != null && getBridge().getWebView() != null) {
                WebView wv = getBridge().getWebView();
                WebSettings settings = wv.getSettings();
                // Enable standard HTTP caching so static assets cached by the server's
                // Cache-Control headers are reused on repeat opens (big speedup on slow networks).
                // HTML stays fresh via the server's no-store header, so templates are never stale.
                settings.setCacheMode(WebSettings.LOAD_DEFAULT);
                settings.setDomStorageEnabled(true);
                // Allow geolocation on insecure (HTTP) local origins — needed for LAN dev testing
                settings.setGeolocationEnabled(true);
                // Override WebChromeClient to auto-grant geolocation on insecure origins (HTTP local IP)
                // while preserving Capacitor's BridgeWebChromeClient behavior for camera, file picker, etc.
                final WebChromeClient originalChromeClient = wv.getWebChromeClient();
                wv.setWebChromeClient(new WebChromeClient() {
                    @Override
                    public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                        // Auto-grant geolocation for any origin (local dev on HTTP needs this)
                        callback.invoke(origin, true, false);
                    }
                    @Override
                    public void onPermissionRequest(PermissionRequest request) {
                        // Delegate to original Capacitor client for camera/mic/etc
                        if (originalChromeClient != null) {
                            originalChromeClient.onPermissionRequest(request);
                        } else {
                            request.grant(request.getResources());
                        }
                    }
                    @Override
                    public boolean onShowFileChooser(WebView webView, android.webkit.ValueCallback<android.net.Uri[]> filePathCallback, FileChooserParams fileChooserParams) {
                        if (originalChromeClient != null) {
                            return originalChromeClient.onShowFileChooser(webView, filePathCallback, fileChooserParams);
                        }
                        return false;
                    }
                    @Override
                    public void onConsoleMessage(String message, int lineNumber, String sourceID) {
                        if (originalChromeClient != null) {
                            originalChromeClient.onConsoleMessage(message, lineNumber, sourceID);
                        }
                    }
                    @Override
                    public boolean onConsoleMessage(android.webkit.ConsoleMessage consoleMessage) {
                        if (originalChromeClient != null) {
                            return originalChromeClient.onConsoleMessage(consoleMessage);
                        }
                        return false;
                    }
                    @Override
                    public void onGeolocationPermissionsHidePrompt() {
                        if (originalChromeClient != null) {
                            originalChromeClient.onGeolocationPermissionsHidePrompt();
                        }
                    }
                });
                // Opaque branding background — eliminates the black screen seen while the
                // first page is loading over a slow connection. Color matches the splash/app theme.
                wv.setBackgroundColor(Color.parseColor("#0f172a"));
                wv.setLayerType(View.LAYER_TYPE_HARDWARE, null);
                wv.addJavascriptInterface(new FleetNativeBridge(this), "_fleetNative");
                setupWebViewNetworkGuard();
                navigateToPendingNotificationLink();
            } else {
                mainHandler.postDelayed(this::scheduleWebViewTransparent, 50);
            }
        });
    }

    private void handleNotificationIntent(Intent intent) {
        if (intent == null) return;
        String link = intent.getStringExtra("notification_link");
        if (link == null || link.trim().isEmpty()) return;
        pendingNotificationLink = link.trim();
    }

    private void navigateToPendingNotificationLink() {
        if (pendingNotificationLink == null || pendingNotificationLink.isEmpty()) {
            return;
        }
        if (pendingNotificationLink.equals(appliedNotificationLink)) {
            return;
        }
        Bridge bridge = getBridge();
        if (bridge == null || bridge.getWebView() == null) {
            return;
        }
        String target = pendingNotificationLink;
        if (target.startsWith("/")) {
            target = resolveServerBaseUrl() + target;
        }
        appliedNotificationLink = pendingNotificationLink;
        bridge.getWebView().loadUrl(target);
    }

    private boolean hasNetworkConnectivity() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        if (cm == null) {
            return false;
        }
        Network network = cm.getActiveNetwork();
        if (network == null) {
            return false;
        }
        NetworkCapabilities caps = cm.getNetworkCapabilities(network);
        return caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }

    private String resolveServerBaseUrl() {
        Bridge bridge = getBridge();
        if (bridge != null) {
            String fromBridge = bridge.getServerUrl();
            if (fromBridge != null && !fromBridge.isEmpty()) {
                return fromBridge.replaceAll("/+$", "");
            }
        }
        return FleetServerProbe.readServerBaseUrl(this);
    }

    private void runServerProbe() {
        // Fast path: if the device has no network connectivity at all, show the offline
        // overlay immediately instead of waiting for the 1.1s server probe to time out.
        if (minSplashDone && !hasNetworkConnectivity()) {
            serverReachable = false;
            evaluatePostSplashNetworkState();
            return;
        }
        if (!minSplashDone) {
            serverReachable = null;
        }
        FleetServerProbe.probeServerAsync(this, resolveServerBaseUrl(), this::onServerProbeResult);
    }

    private void onServerProbeResult(boolean reachable) {
        serverReachable = reachable;
        if (reachable) {
            webViewMainFrameFailed = false;
            if (networkOverlayVisible) {
                hideNetworkOverlay();
            }
            if (minSplashDone && needsWebViewReload()) {
                loadAppUrlInWebView(false);
            }
        }
        evaluatePostSplashNetworkState();
    }

    private boolean needsWebViewReload() {
        if (appPageLoaded) {
            return false;
        }
        Bridge bridge = getBridge();
        if (bridge == null || bridge.getWebView() == null) {
            return webViewMainFrameFailed;
        }
        String current = bridge.getWebView().getUrl();
        return webViewMainFrameFailed
                || current == null
                || "about:blank".equals(current)
                || current.startsWith("data:");
    }

    /** After splash: show the offline error only when we have NO connectivity at all OR
     *  the WebView main frame also failed. A slow-but-alive server (probe timeout) must NOT
     *  trigger the error screen if the page is still loading — the branded loading overlay
     *  stays visible so the user keeps seeing progress instead of a false "No Internet". */
    private void evaluatePostSplashNetworkState() {
        if (!minSplashDone || appPageLoaded) {
            return;
        }
        if (Boolean.TRUE.equals(serverReachable)) {
            return;
        }
        // Truly offline (no network) OR both probe + main frame failed → show error screen.
        boolean trulyOffline = !hasNetworkConnectivity();
        if (trulyOffline || (Boolean.FALSE.equals(serverReachable) && webViewMainFrameFailed)) {
            showNetworkOverlay(false);
        }
        // Otherwise: keep the branded loading overlay running (slow network is still loading).
    }

    private void showNetworkOverlay(boolean connecting) {
        if (!connecting && Boolean.TRUE.equals(serverReachable)) {
            return;
        }
        if (!minSplashDone) {
            return;
        }
        // Loading overlay is superseded by the explicit error/offline screen.
        hideLoadingOverlay();
        if (networkOverlayRoot == null) {
            setupNetworkOverlay();
        }
        if (networkOverlayRoot == null) {
            return;
        }
        networkOverlayVisible = true;
        networkOverlayRoot.setVisibility(View.VISIBLE);
        if (networkAutoRetryText != null) {
            networkAutoRetryText.setText(connecting
                    ? getString(R.string.fleet_network_connecting)
                    : getString(R.string.fleet_network_auto_retry));
        }
        if (networkRetryBtn != null) {
            networkRetryBtn.setEnabled(!connecting);
        }
        startAutoRetryLoop();
    }

    private void hideNetworkOverlay() {
        networkOverlayVisible = false;
        stopAutoRetryLoop();
        if (networkOverlayRoot != null) {
            networkOverlayRoot.setVisibility(View.GONE);
        }
    }

    private void markAppPageLoaded() {
        appPageLoaded = true;
        webViewMainFrameFailed = false;
        serverReachable = true;
        hideNetworkOverlay();
        // App page fully rendered → hide the loading overlay (clean reveal of the real app).
        hideSplash();
        hideLoadingOverlay();
    }

    /** Programmatically hide the Capacitor splash screen (idempotent + thread-safe).
     *  Called on page load OR the SPLASH_MAX_MS safety cap, whichever comes first.
     *  Once the native splash is gone we immediately show the branded loading overlay so
     *  the user never sees a black screen while the WebView keeps fetching. */
    private void hideSplash() {
        if (splashHidden) return;
        splashHidden = true;
        boolean pluginHideOk = false;
        try {
            if (getBridge() != null) {
                com.getcapacitor.PluginHandle handle = getBridge().getPlugin("SplashScreen");
                if (handle != null && handle.getInstance() != null) {
                    // Try reflection first (version-agnostic), then the typed plugin as a backup.
                    try {
                        java.lang.reflect.Method m = handle.getInstance().getClass().getMethod("hide");
                        m.invoke(handle.getInstance());
                        pluginHideOk = true;
                    } catch (NoSuchMethodException nsme) {
                        // Fall through to typed cast below.
                    }
                }
            }
        } catch (Throwable ignored) {
            // Will be handled by the force-hide fallback below.
        }
        // Bulletproof fallback: even if the plugin path is wrong or reflection fails,
        // the SplashScreen fragment is hosted in our activity — find and remove it so
        // the splash can NEVER get stuck (the #1 cause of "hang" feel).
        if (!pluginHideOk) {
            try {
                getSupportFragmentManager().executePendingTransactions();
                android.app.Fragment legacy = getFragmentManager().findFragmentByTag("capacitor_splash_screen_fragment");
                if (legacy != null) getFragmentManager().beginTransaction().remove(legacy).commitAllowingStateLoss();
                androidx.fragment.app.Fragment frag = getSupportFragmentManager().findFragmentByTag("capacitor_splash_screen_fragment");
                if (frag != null) getSupportFragmentManager().beginTransaction().remove(frag).commitAllowingStateLoss();
            } catch (Throwable ignored) {}
        }
        // Splash just hid → show branded loading overlay until the app page finishes.
        // Only when the app is NOT yet loaded; otherwise markAppPageLoaded already handled it.
        if (!appPageLoaded) {
            showLoadingOverlay();
        }
    }

    private void pulseAutoRetryLabel() {
        if (networkAutoRetryText == null || !networkOverlayVisible) {
            return;
        }
        networkAutoRetryText.setText(getString(R.string.fleet_network_auto_retry));
    }

    private void startAutoRetryLoop() {
        mainHandler.removeCallbacks(autoRetryRunnable);
        mainHandler.postDelayed(autoRetryRunnable, AUTO_RETRY_MS);
    }

    private void stopAutoRetryLoop() {
        mainHandler.removeCallbacks(autoRetryRunnable);
    }

    private void probeServerAndMaybeReload(boolean fromManualRetry) {
        if (!hasNetworkConnectivity()) {
            serverReachable = false;
            if (fromManualRetry) {
                Toast.makeText(this, R.string.fleet_network_error_title, Toast.LENGTH_SHORT).show();
            }
            showNetworkOverlay(false);
            return;
        }
        if (fromManualRetry) {
            showNetworkOverlay(true);
        }
        FleetServerProbe.probeServerAsync(this, resolveServerBaseUrl(), reachable -> {
            serverReachable = reachable;
            if (reachable) {
                loadAppUrlInWebView(fromManualRetry);
            } else if (fromManualRetry || networkOverlayVisible) {
                showNetworkOverlay(false);
            }
        });
    }

    private void loadAppUrlInWebView(boolean fromManualRetry) {
        Bridge bridge = getBridge();
        if (bridge == null || bridge.getWebView() == null) {
            if (fromManualRetry) {
                showNetworkOverlay(false);
            }
            return;
        }
        if (fromManualRetry) {
            showNetworkOverlay(true);
        }
        String appUrl = bridge.getAppUrl();
        if (appUrl == null || appUrl.isEmpty()) {
            appUrl = bridge.getServerUrl();
        }
        if (appUrl == null || appUrl.isEmpty()) {
            bridge.getWebView().reload();
            return;
        }
        webViewMainFrameFailed = false;
        bridge.getWebView().loadUrl(appUrl);
    }

    private void retryWebViewLoad() {
        probeServerAndMaybeReload(true);
    }

    private void registerNetworkCallback() {
        if (networkCallback != null || Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return;
        }
        ConnectivityManager cm = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        if (cm == null) {
            return;
        }
        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override
            public void onAvailable(@NonNull Network network) {
                runOnUiThread(() -> {
                    if (networkOverlayVisible) {
                        probeServerAndMaybeReload(false);
                    } else if (minSplashDone && !appPageLoaded && !Boolean.TRUE.equals(serverReachable)) {
                        runServerProbe();
                    }
                });
            }
        };
        cm.registerDefaultNetworkCallback(networkCallback);
    }

    private void unregisterNetworkCallback() {
        if (networkCallback == null || Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return;
        }
        ConnectivityManager cm = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        if (cm != null) {
            try {
                cm.unregisterNetworkCallback(networkCallback);
            } catch (Exception ignored) {}
        }
        networkCallback = null;
    }

    @Override
    public void onMainFrameLoadFailed() {
        runOnUiThread(() -> {
            webViewMainFrameFailed = true;
            if (Boolean.TRUE.equals(serverReachable)) {
                webViewReloadAttempts++;
                if (webViewReloadAttempts > MAX_RELOAD_ATTEMPTS) {
                    Log.w("FleetMain", "Max reload attempts (" + MAX_RELOAD_ATTEMPTS + ") reached — showing network overlay");
                    showNetworkOverlay(false);
                    return;
                }
                loadAppUrlInWebView(false);
                return;
            }
            if (minSplashDone && Boolean.FALSE.equals(serverReachable)) {
                showNetworkOverlay(false);
            }
        });
    }

    @Override
    public void onMainFrameLoadSucceeded(String url) {
        webViewReloadAttempts = 0;
        runOnUiThread(this::markAppPageLoaded);
    }

    @Override
    public void onStart() {
        super.onStart();
        registerNetworkCallback();
    }

    @Override
    public void onStop() {
        unregisterNetworkCallback();
        super.onStop();
    }

    @Override
    public void onResume() {
        super.onResume();
        scheduleWebViewTransparent();
        navigateToPendingNotificationLink();
        if (networkOverlayVisible) {
            return;
        }
        // If the page already loaded there's nothing startup-related to resolve.
        if (appPageLoaded) {
            return;
        }
        // Splash hasn't elapsed yet — keep showing branding, evaluate later.
        if (!minSplashDone) {
            return;
        }
        // Splash done but app not yet loaded: immediately reflect offline state if so.
        if (!hasNetworkConnectivity() || Boolean.FALSE.equals(serverReachable)) {
            showNetworkOverlay(false);
        }
    }

    @Override
    public void onPause() {
        super.onPause();
        stopAutoRetryLoop();
        if (deadlineTimer != null) {
            cancelDeadlineTimer();
        }
    }

    private void createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            android.app.NotificationManager mgr =
                    (android.app.NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (mgr == null) return;

            android.app.NotificationChannel main = new android.app.NotificationChannel(
                    "fleet_attendance", "Fleet Notifications",
                    android.app.NotificationManager.IMPORTANCE_HIGH);
            main.setDescription("Attendance alerts and fleet management notifications");
            main.enableVibration(true);
            main.setSound(android.media.RingtoneManager.getDefaultUri(
                    android.media.RingtoneManager.TYPE_NOTIFICATION), null);
            mgr.createNotificationChannel(main);

            android.app.NotificationChannel sync = new android.app.NotificationChannel(
                    "sync_service", "Sync Service",
                    android.app.NotificationManager.IMPORTANCE_LOW);
            sync.setDescription("Background notification sync");
            sync.setShowBadge(false);
            mgr.createNotificationChannel(sync);
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this,
                        new String[]{Manifest.permission.POST_NOTIFICATIONS},
                        NOTIF_PERMISSION_REQUEST);
            }
        }
    }

    private void requestLocationPermission() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION},
                    LOCATION_PERMISSION_REQUEST);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == NOTIF_PERMISSION_REQUEST) {
            if (grantResults.length > 0 && grantResults[0] != PackageManager.PERMISSION_GRANTED) {
                boolean canAskAgain = true;
                if (Build.VERSION.SDK_INT >= 33) {
                    canAskAgain = ActivityCompat.shouldShowRequestPermissionRationale(this,
                            Manifest.permission.POST_NOTIFICATIONS);
                }
                if (!canAskAgain) {
                    Toast.makeText(this,
                            "Notifications are disabled. Enable them in Settings for alerts.",
                            Toast.LENGTH_LONG).show();
                }
            }
        }
    }

    private boolean initializeFirebase() {
        try {
            if (isProblematicDevice()) {
                if (FirebaseApp.getApps(this).isEmpty()) {
                    FirebaseApp.initializeApp(this);
                } else {
                    FirebaseApp existing = FirebaseApp.getInstance();
                    try {
                        existing.delete();
                        FirebaseApp.initializeApp(this);
                    } catch (Exception ignored) {}
                }
            }
            FirebaseApp.getInstance();
            return true;
        } catch (Exception e) {
            FirebaseApp.initializeApp(this);
            try { FirebaseApp.getInstance(); return true; }
            catch (Exception e2) { return false; }
        }
    }

    private void checkGooglePlayServices() {
        GoogleApiAvailability api = GoogleApiAvailability.getInstance();
        int code = api.isGooglePlayServicesAvailable(this);
        if (code != ConnectionResult.SUCCESS && api.isUserResolvableError(code)) {
            api.getErrorDialog(this, code, 9000).show();
        }
    }

    private boolean isProblematicDevice() {
        String m = Build.MANUFACTURER.toUpperCase(Locale.ROOT);
        return m.contains("OPPO") || m.contains("VIVO") || m.contains("REALME")
                || m.contains("XIAOMI") || m.contains("ONEPLUS")
                || m.contains("HUAWEI") || m.contains("HONOR");
    }

    private void requestBatteryOptimizationExemption() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return;
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        if (pm != null && !pm.isIgnoringBatteryOptimizations(getPackageName())) {
            try {
                Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                intent.setData(Uri.parse("package:" + getPackageName()));
                startActivityForResult(intent, BATTERY_OPT_REQUEST);
            } catch (Exception e) {
                try { startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)); }
                catch (Exception ignored) {}
            }
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
    }

    private void startTokenAcquisition() {
        attemptStandardToken(1);
    }

    private void attemptStandardToken(int attempt) {
        if (tokenResolved || attempt > MAX_RETRY_ATTEMPTS) {
            if (!tokenResolved && attempt > MAX_RETRY_ATTEMPTS) {
                initiateFisFallback();
            }
            return;
        }
        long backoff = INITIAL_BACKOFF_MS * (long) Math.pow(2, attempt - 1);

        final boolean[] done = {false};

        mainHandler.postDelayed(() -> {
            if (!done[0] && !tokenResolved) {
                done[0] = true;
                long delay = (attempt == 1) ? 0 : backoff;
                mainHandler.postDelayed(() -> attemptStandardToken(attempt + 1), delay);
            }
        }, GMS_TOKEN_TIMEOUT_MS);

        if (attempt > 1) {
            FirebaseMessaging.getInstance().deleteToken().addOnCompleteListener(dt ->
                    requestTokenForAttempt(attempt, done));
        } else {
            requestTokenForAttempt(attempt, done);
        }
    }

    private void requestTokenForAttempt(int attempt, boolean[] done) {
        if (tokenResolved) return;
        FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
            if (done[0] || tokenResolved) return;
            done[0] = true;
            if (task.isSuccessful() && task.getResult() != null && !task.getResult().isEmpty()) {
                onTokenAcquired(task.getResult(), "Attempt" + attempt);
            }
        });
    }

    private void initiateFisFallback() {
        if (tokenResolved) return;
        new Thread(() -> {
            try {
                String fisId = com.google.android.gms.tasks.Tasks.await(
                        FirebaseInstallations.getInstance().getId());
                prefs.edit().putString(KEY_FIS_ID, fisId).apply();

                com.google.android.gms.tasks.Tasks.await(
                        FirebaseInstallations.getInstance().getToken(false));
            } catch (Exception ignored) {}
        }).start();
    }

    private synchronized void onTokenAcquired(String token, String source) {
        if (tokenResolved) return;
        tokenResolved = true;
        prefs.edit().putString(KEY_FCM_TOKEN, token).putBoolean(KEY_USE_POLLING, false).apply();
        cancelDeadlineTimer();
        stopPollingService();
        runOnUiThread(() -> {
            if (getBridge() != null && getBridge().getWebView() != null) {
                String safe = token.replace("\\", "\\\\").replace("'", "\\'");
                getBridge().getWebView().evaluateJavascript(
                        "if(window._onNativeFcmToken) window._onNativeFcmToken('" + safe + "');", null);
            }
        });
    }

    private void schedulePollingActivation() {
        deadlineTimer = new Timer("FCM_Deadline", true);
        deadlineTimer.schedule(new TimerTask() {
            @Override
            public void run() {
                if (tokenResolved) return;
                prefs.edit().putBoolean(KEY_USE_POLLING, true).apply();
                startPollingService();
                String fisId = prefs.getString(KEY_FIS_ID, null);
                if (fisId != null) {
                    runOnUiThread(() -> {
                        if (getBridge() != null && getBridge().getWebView() != null) {
                            String js = "if(window._onFcmFallbackMode) window._onFcmFallbackMode('"
                                    + fisId.replace("'", "\\'") + "');";
                            getBridge().getWebView().evaluateJavascript(js, null);
                        }
                    });
                }
            }
        }, POLLING_ACTIVATION_DEADLINE_MS);
    }

    private void cancelDeadlineTimer() {
        if (deadlineTimer != null) { deadlineTimer.cancel(); deadlineTimer = null; }
    }

    private void startPollingService() {
        try {
            Intent intent = new Intent(this, NotificationPollingService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent);
            } else {
                startService(intent);
            }
        } catch (Exception ignored) {}
    }

    private void stopPollingService() {
        try {
            stopService(new Intent(this, NotificationPollingService.class));
        } catch (Exception ignored) {}
    }

    /** JS bridge — callable from WebView as window._fleetNative.*() */
    public class FleetNativeBridge {
        private final MainActivity activity;
        FleetNativeBridge(MainActivity a) { this.activity = a; }

        /** Return current app version name (e.g. "2.0.8") — 100% reliable, reads PackageManager directly.
         *  Used by JS reportDeviceVersion() for admin version stats. Sync call (safe on JS thread). */
        @JavascriptInterface
        public String getAppVersion() {
            try {
                return activity.getPackageManager()
                        .getPackageInfo(activity.getPackageName(), 0).versionName;
            } catch (Exception e) {
                Log.w("FleetNativeBridge", "getAppVersion failed: " + e.getMessage());
                return "";
            }
        }

        @JavascriptInterface
        public void openAppSettings() {
            try {
                Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
                intent.setData(Uri.parse("package:" + activity.getPackageName()));
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                activity.startActivity(intent);
            } catch (Exception e) {
                try {
                    activity.startActivity(new Intent(Settings.ACTION_APPLICATION_SETTINGS)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                } catch (Exception ignored) {}
            }
        }

        /** Sync check — runs on @JavascriptInterface background thread, safe to call */
        @JavascriptInterface
        public String getNotificationStatus() {
            String status = computeNotifStatus();
            return status;
        }

        /** Async version: computes status and fires JS callback(status) */
        @JavascriptInterface
        public void checkNotificationStatus(final String callbackFn) {
            final String status = computeNotifStatus();
            activity.runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    if (activity.isFinishing() || activity.isDestroyed()) return;
                    if (activity.getBridge() != null && activity.getBridge().getWebView() != null) {
                        activity.getBridge().getWebView().evaluateJavascript(
                            callbackFn + "('" + status + "');", null);
                    }
                }
            });
        }

        private String computeNotifStatus() {
            Log.d("FLEET_DEBUG", "computeNotifStatus called, SDK=" + Build.VERSION.SDK_INT);
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    int result = ContextCompat.checkSelfPermission(
                            activity, Manifest.permission.POST_NOTIFICATIONS);
                    String st = (result == PackageManager.PERMISSION_GRANTED) ? "granted" : "denied";
                    Log.d("FLEET_DEBUG", "POST_NOTIFICATIONS status=" + st);
                    return st;
                }
                android.app.NotificationManager nm =
                        (android.app.NotificationManager) activity.getSystemService(NOTIFICATION_SERVICE);
                if (nm != null && !nm.areNotificationsEnabled()) {
                    Log.d("FLEET_DEBUG", "areNotificationsEnabled=false → denied");
                    return "denied";
                }
                Log.d("FLEET_DEBUG", "Notifications=granted (below Android 13)");
                return "granted";
            } catch (Exception e) {
                Log.e("FLEET_DEBUG", "computeNotifStatus exception: " + e.getMessage());
                return "denied";
            }
        }

        /** Request notification permission (Android 13+) */
        @JavascriptInterface
        public void requestNotifications() {
            if (activity.isFinishing() || activity.isDestroyed()) return;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                activity.runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        ActivityCompat.requestPermissions(activity,
                                new String[]{Manifest.permission.POST_NOTIFICATIONS},
                                NOTIF_PERMISSION_REQUEST);
                    }
                });
            }
        }

        @JavascriptInterface
        public void closeNotificationPopup() {
            activity.runOnUiThread(activity::finishAndRemoveTask);
        }

        @JavascriptInterface
        public String saveNotificationCard(String json) {
            try {
                JSONObject obj = new JSONObject(json == null ? "{}" : json);
                String title = obj.optString("title", "Notification");
                String message = obj.optString("message", "");
                String createdAt = obj.optString("created_at", "");
                String source = obj.optString("source", "generic");
                Bitmap bmp = renderNotificationBitmap(title, message, createdAt, source);
                Uri uri = saveBitmapToGallery(bmp, "fleet_notification_" + System.currentTimeMillis() + ".png");
                return uri != null ? "Saved to gallery." : "Save failed.";
            } catch (Exception e) {
                Log.e("FleetNativeBridge", "saveNotificationCard failed", e);
                return "Save failed.";
            }
        }
    }

    private Bitmap renderNotificationBitmap(String title, String message, String createdAt, String source) {
        int width = 1080;
        int padding = 72;
        int cardPadding = 54;
        int y = 0;
        Paint titlePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        titlePaint.setColor(Color.WHITE);
        titlePaint.setTextSize(56f);
        titlePaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));

        Paint metaPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        metaPaint.setColor(Color.parseColor("#9fb0c9"));
        metaPaint.setTextSize(30f);

        Paint bodyPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        bodyPaint.setColor(Color.parseColor("#e5eefb"));
        bodyPaint.setTextSize(38f);

        Paint badgePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        badgePaint.setColor(Color.parseColor("##13243c".replace("##", "#")));
        Paint badgeText = new Paint(Paint.ANTI_ALIAS_FLAG);
        badgeText.setColor(Color.parseColor("#cfe8ff"));
        badgeText.setTextSize(28f);
        badgeText.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));

        Rect bounds = new Rect();
        titlePaint.getTextBounds(title, 0, title.length(), bounds);
        int badgeHeight = 72;
        int titleHeight = Math.max(70, bounds.height() + 24);
        int bodyLineHeight = 54;
        int bodyLines = Math.max(2, estimateWrappedLines(message, bodyPaint, width - (padding * 2) - (cardPadding * 2)));
        int bodyHeight = bodyLines * bodyLineHeight;
        int metaHeight = TextUtils.isEmpty(createdAt) ? 0 : 48;
        int height = padding * 2 + cardPadding * 2 + badgeHeight + titleHeight + metaHeight + bodyHeight + 80;

        Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        canvas.drawColor(Color.parseColor("#07111f"));

        Paint cardPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        cardPaint.setColor(Color.parseColor("#10213a"));
        float left = padding;
        float top = padding;
        float right = width - padding;
        float bottom = height - padding;
        canvas.drawRoundRect(left, top, right, bottom, 36f, 36f, cardPaint);

        Paint strokePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        strokePaint.setStyle(Paint.Style.STROKE);
        strokePaint.setStrokeWidth(3f);
        strokePaint.setColor(Color.parseColor("#2a3b59"));
        canvas.drawRoundRect(left, top, right, bottom, 36f, 36f, strokePaint);

        float x = left + cardPadding;
        y = (int) top + cardPadding + badgeHeight;
        canvas.drawRoundRect(x, top + cardPadding, x + 280, top + cardPadding + badgeHeight, 24f, 24f, badgePaint);
        canvas.drawText(
                "ufone_task_event".equals(source) ? "Task Notification" : "Notification",
                x + 24,
                top + cardPadding + 46,
                badgeText
        );
        canvas.drawText(title, x, y + 42, titlePaint);
        y += titleHeight + 26;
        if (!TextUtils.isEmpty(createdAt)) {
            canvas.drawText("Received: " + createdAt, x, y, metaPaint);
            y += metaHeight;
        }
        drawWrappedText(canvas, message, x, y, width - (padding * 2) - (cardPadding * 2), bodyPaint, bodyLineHeight);
        return bitmap;
    }

    private int estimateWrappedLines(String text, Paint paint, int maxWidth) {
        if (text == null || text.trim().isEmpty()) return 1;
        String[] words = text.split("\\s+");
        StringBuilder line = new StringBuilder();
        int lines = 1;
        for (String word : words) {
            String trial = line.length() == 0 ? word : (line + " " + word);
            if (paint.measureText(trial) > maxWidth && line.length() > 0) {
                lines++;
                line = new StringBuilder(word);
            } else {
                line = new StringBuilder(trial);
            }
        }
        return lines;
    }

    private void drawWrappedText(Canvas canvas, String text, float x, float y, int maxWidth, Paint paint, int lineHeight) {
        if (text == null) text = "";
        String[] words = text.split("\\s+");
        StringBuilder line = new StringBuilder();
        float drawY = y;
        for (String word : words) {
            String trial = line.length() == 0 ? word : (line + " " + word);
            if (paint.measureText(trial) > maxWidth && line.length() > 0) {
                canvas.drawText(line.toString(), x, drawY, paint);
                drawY += lineHeight;
                line = new StringBuilder(word);
            } else {
                line = new StringBuilder(trial);
            }
        }
        if (line.length() > 0) {
            canvas.drawText(line.toString(), x, drawY, paint);
        }
    }

    private Uri saveBitmapToGallery(Bitmap bitmap, String fileName) throws Exception {
        ContentValues values = new ContentValues();
        values.put(MediaStore.Images.Media.DISPLAY_NAME, fileName);
        values.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            values.put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/Fleet Manager");
            values.put(MediaStore.Images.Media.IS_PENDING, 1);
        }
        Uri uri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
        if (uri == null) {
            return null;
        }
        try (OutputStream out = getContentResolver().openOutputStream(uri)) {
            if (out == null || !bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)) {
                throw new IllegalStateException("Bitmap write failed");
            }
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ContentValues done = new ContentValues();
            done.put(MediaStore.Images.Media.IS_PENDING, 0);
            getContentResolver().update(uri, done, null, null);
        }
        return uri;
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleNotificationIntent(intent);
        navigateToPendingNotificationLink();
    }


    private void setupDownloadListener() {
        if (mainHandler == null) {
            mainHandler = new Handler(Looper.getMainLooper());
        }
        mainHandler.post(() -> {
            if (getBridge() == null || getBridge().getWebView() == null) {
                mainHandler.postDelayed(this::setupDownloadListener, 100);
                return;
            }
            getBridge().getWebView().setDownloadListener(
                (url, userAgent, contentDisposition, mimetype, contentLength) -> {
                    try {
                        DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
                        String fileName = URLUtil.guessFileName(url, contentDisposition, mimetype);
                        req.setTitle(fileName);
                        req.setDescription("Downloading file...");
                        req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                        req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);
                        req.setMimeType(mimetype);
                        req.addRequestHeader("User-Agent", userAgent);
                        req.addRequestHeader("Cookie", android.webkit.CookieManager.getInstance().getCookie(url));
                        DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                        if (dm != null) {
                            dm.enqueue(req);
                            Toast.makeText(this, "Downloading: " + fileName, Toast.LENGTH_SHORT).show();
                        }
                    } catch (Exception e) {
                        Toast.makeText(this, "Download failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
                    }
                });
        });
    }

    @Override
    public void onDestroy() {
        stopAutoRetryLoop();
        if (mainHandler != null) {
            mainHandler.removeCallbacks(splashMinRunnable);
            mainHandler.removeCallbacks(loadingDotRunnable);
        }
        unregisterNetworkCallback();
        cancelDeadlineTimer();
        super.onDestroy();
    }
}
