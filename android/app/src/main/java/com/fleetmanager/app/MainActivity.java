package com.fleetmanager.app;

import android.Manifest;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.graphics.Color;
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
import android.webkit.URLUtil;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;
import android.app.DownloadManager;
import android.content.Context;

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
    private static final long SPLASH_MIN_MS = 1200L;
    private static final long AUTO_RETRY_MS = 5000L;

    private volatile boolean tokenResolved = false;
    private Handler mainHandler;
    private Timer deadlineTimer;
    private SharedPreferences prefs;
    private FleetAutoUpdateManager autoUpdateManager;

    private View networkOverlayRoot;
    private TextView networkAutoRetryText;
    private Button networkRetryBtn;
    private boolean networkOverlayVisible = false;
    private boolean appPageLoaded = false;
    private boolean minSplashDone = false;
    private boolean webViewGuardReady = false;
    private boolean webViewMainFrameFailed = false;
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
        evaluatePostSplashNetworkState();
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        registerPlugin(AttendanceFrontCameraPlugin.class);
        registerPlugin(FleetApkDownloadPlugin.class);
        mainHandler = new Handler(Looper.getMainLooper());
        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        setupNetworkOverlay();
        runServerProbe();
        mainHandler.postDelayed(splashMinRunnable, SPLASH_MIN_MS);

        if (!initializeFirebase()) return;

        createNotificationChannels();
        checkGooglePlayServices();
        requestNotificationPermission();
        requestLocationPermission();
        requestBatteryOptimizationExemption();

        FirebaseMessaging.getInstance().setAutoInitEnabled(true);
        startTokenAcquisition();

        schedulePollingActivation();
        setupDownloadListener();
        getWindow().setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        scheduleWebViewTransparent();

        // Auto-update: initialize manager and check for pending install on app open
        autoUpdateManager = new FleetAutoUpdateManager(this);
        // Check pending install after WebView is ready (delayed to not block splash)
        mainHandler.postDelayed(() -> {
            if (autoUpdateManager != null) autoUpdateManager.checkPendingInstall();
        }, 3000);
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

    /** CameraPreview (toBack) needs a transparent WebView; opaque white blocks the native preview. */
    private void scheduleWebViewTransparent() {
        if (mainHandler == null) {
            mainHandler = new Handler(Looper.getMainLooper());
        }
        mainHandler.post(() -> {
            if (getBridge() != null && getBridge().getWebView() != null) {
                WebView wv = getBridge().getWebView();
                WebSettings settings = wv.getSettings();
                settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
                // Allow geolocation on insecure (HTTP) local origins — needed for LAN dev testing
                settings.setGeolocationEnabled(true);
                // Clear all cached data so latest template is always fetched from server
                wv.clearCache(true);
                wv.clearHistory();
                android.webkit.CookieManager.getInstance().flush();
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
                wv.setBackgroundColor(Color.TRANSPARENT);
                wv.setLayerType(View.LAYER_TYPE_HARDWARE, null);
                wv.addJavascriptInterface(new FleetNativeBridge(this), "_fleetNative");
                // Set server URL for auto-update from WebView URL
                if (autoUpdateManager != null && wv.getUrl() != null) {
                    String wvUrl = wv.getUrl();
                    if (wvUrl.startsWith("http")) {
                        // Extract base URL (scheme + host + port)
                        try {
                            java.net.URL parsed = new java.net.URL(wvUrl);
                            String base = parsed.getProtocol() + "://" + parsed.getHost()
                                    + (parsed.getPort() > 0 ? ":" + parsed.getPort() : "");
                            autoUpdateManager.setServerBaseUrl(base);
                        } catch (Exception ignored) {}
                    }
                }
                setupWebViewNetworkGuard();
            } else {
                mainHandler.postDelayed(this::scheduleWebViewTransparent, 50);
            }
        });
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

    /** After splash: show overlay only when server probe failed (not while page is still loading). */
    private void evaluatePostSplashNetworkState() {
        if (!minSplashDone || appPageLoaded) {
            return;
        }
        if (Boolean.TRUE.equals(serverReachable)) {
            return;
        }
        if (Boolean.FALSE.equals(serverReachable) || webViewMainFrameFailed) {
            showNetworkOverlay(false);
        }
    }

    private void showNetworkOverlay(boolean connecting) {
        if (!connecting && Boolean.TRUE.equals(serverReachable)) {
            return;
        }
        if (!minSplashDone) {
            return;
        }
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
        // Check if APK was downloaded while app was in background
        if (autoUpdateManager != null) {
            mainHandler.postDelayed(() -> {
                if (autoUpdateManager != null) autoUpdateManager.checkPendingInstall();
            }, 500);
        }
        if (networkOverlayVisible) {
            return;
        }
        if (appPageLoaded || !minSplashDone) {
            return;
        }
        if (Boolean.FALSE.equals(serverReachable)) {
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

        /** Trigger auto-update check from Java side (silent download) */
        @JavascriptInterface
        public void checkForUpdate() {
            if (activity.autoUpdateManager != null) {
                activity.runOnUiThread(() -> activity.autoUpdateManager.checkForUpdate());
            }
        }

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
        }
        unregisterNetworkCallback();
        cancelDeadlineTimer();
        if (autoUpdateManager != null) autoUpdateManager.onDestroy();
        super.onDestroy();
    }
}
