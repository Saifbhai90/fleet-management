package com.fleetmanager.app;

import android.Manifest;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.webkit.URLUtil;
import android.widget.Toast;
import android.app.DownloadManager;
import android.content.Context;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.getcapacitor.BridgeActivity;
import com.google.android.gms.common.ConnectionResult;
import com.google.android.gms.common.GoogleApiAvailability;
import com.google.firebase.FirebaseApp;
import com.google.firebase.installations.FirebaseInstallations;
import com.google.firebase.messaging.FirebaseMessaging;

import java.util.Locale;
import java.util.Timer;
import java.util.TimerTask;

public class MainActivity extends BridgeActivity {

    private static final String TAG = "FCM_DEBUG";
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

    private volatile boolean tokenResolved = false;
    private Handler mainHandler;
    private Timer deadlineTimer;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        mainHandler = new Handler(Looper.getMainLooper());
        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        Log.e(TAG, "=== onCreate v1.9 === manufacturer=" + Build.MANUFACTURER + " model=" + Build.MODEL + " SDK=" + Build.VERSION.SDK_INT);

        if (!initializeFirebase()) return;

        createNotificationChannels();
        checkGooglePlayServices();
        requestNotificationPermission();
        requestBatteryOptimizationExemption();

        FirebaseMessaging.getInstance().setAutoInitEnabled(true);
        startTokenAcquisition();

        schedulePollingActivation();
        setupDownloadListener();
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

            Log.e(TAG, "Notification channels created: fleet_attendance + sync_service");
        }
    }
    // --- Android 13+ POST_NOTIFICATIONS runtime permission popup ---

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                Log.e(TAG, "POST_NOTIFICATIONS not granted - showing system popup");
                ActivityCompat.requestPermissions(this,
                        new String[]{Manifest.permission.POST_NOTIFICATIONS},
                        NOTIF_PERMISSION_REQUEST);
            } else {
                Log.e(TAG, "POST_NOTIFICATIONS already granted");
            }
        } else {
            Log.e(TAG, "SDK < 33 - no POST_NOTIFICATIONS needed");
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == NOTIF_PERMISSION_REQUEST) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                Log.e(TAG, "POST_NOTIFICATIONS GRANTED by user");
            } else {
                Log.e(TAG, "POST_NOTIFICATIONS DENIED by user");
                boolean canAskAgain = true;
                if (Build.VERSION.SDK_INT >= 33) {
                    canAskAgain = ActivityCompat.shouldShowRequestPermissionRationale(this,
                            Manifest.permission.POST_NOTIFICATIONS);
                }
                if (!canAskAgain) {
                    Log.e(TAG, "User selected 'Don't ask again' - directing to app settings");
                    Toast.makeText(this,
                            "Notifications are disabled. Enable them in Settings for alerts.",
                            Toast.LENGTH_LONG).show();
                }
            }
        }
    }

    // --- Firebase Initialization (OPPO/Vivo/Xiaomi fix) ---

    private boolean initializeFirebase() {
        try {
            if (isProblematicDevice()) {
                Log.e(TAG, "OPPO/Vivo/Realme detected - force re-init FirebaseApp");
                if (FirebaseApp.getApps(this).isEmpty()) {
                    FirebaseApp.initializeApp(this);
                } else {
                    FirebaseApp existing = FirebaseApp.getInstance();
                    Log.e(TAG, "FirebaseApp exists: " + existing.getOptions().getProjectId());
                    try {
                        existing.delete();
                        FirebaseApp.initializeApp(this);
                        Log.e(TAG, "FirebaseApp re-initialized");
                    } catch (Exception re) {
                        Log.e(TAG, "Re-init failed (non-fatal): " + re.getMessage());
                    }
                }
            }
            FirebaseApp app = FirebaseApp.getInstance();
            Log.e(TAG, "FirebaseApp: project=" + app.getOptions().getProjectId()
                    + " sender=" + app.getOptions().getGcmSenderId()
                    + " appId=" + app.getOptions().getApplicationId());
            return true;
        } catch (Exception e) {
            Log.e(TAG, "FirebaseApp INIT FAILED: " + e.getMessage(), e);
            FirebaseApp.initializeApp(this);
            try { FirebaseApp.getInstance(); return true; }
            catch (Exception e2) { Log.e(TAG, "FirebaseApp STILL MISSING: " + e2.getMessage()); return false; }
        }
    }

    private void checkGooglePlayServices() {
        GoogleApiAvailability api = GoogleApiAvailability.getInstance();
        int code = api.isGooglePlayServicesAvailable(this);
        Log.e(TAG, "Play Services check: code=" + code + " (0=SUCCESS)");
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

    // --- Battery Optimization Bypass ---

    private void requestBatteryOptimizationExemption() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return;
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        if (pm != null && !pm.isIgnoringBatteryOptimizations(getPackageName())) {
            Log.e(TAG, "Battery opt is ON - requesting exemption");
            try {
                Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                intent.setData(Uri.parse("package:" + getPackageName()));
                startActivityForResult(intent, BATTERY_OPT_REQUEST);
            } catch (Exception e) {
                Log.e(TAG, "Battery exemption request failed: " + e.getMessage());
                try { startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)); }
                catch (Exception e2) { Log.e(TAG, "Battery settings failed: " + e2.getMessage()); }
            }
        } else {
            Log.e(TAG, "Battery opt already exempt");
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == BATTERY_OPT_REQUEST && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            boolean exempt = pm != null && pm.isIgnoringBatteryOptimizations(getPackageName());
            Log.e(TAG, "Battery opt result: exempt=" + exempt);
        }
    }

    // --- Token Acquisition Pipeline ---

    private void startTokenAcquisition() {
        Log.e(TAG, "=== FCM TOKEN PIPELINE START ===");
        attemptStandardToken(1);
    }

    private void attemptStandardToken(int attempt) {
        if (tokenResolved || attempt > MAX_RETRY_ATTEMPTS) {
            if (!tokenResolved && attempt > MAX_RETRY_ATTEMPTS) {
                Log.e(TAG, "All " + MAX_RETRY_ATTEMPTS + " attempts exhausted - FIS fallback");
                initiateFisFallback();
            }
            return;
        }
        long backoff = INITIAL_BACKOFF_MS * (long) Math.pow(2, attempt - 1);
        Log.e(TAG, "-- Attempt " + attempt + "/" + MAX_RETRY_ATTEMPTS + " timeout=" + GMS_TOKEN_TIMEOUT_MS + "ms --");

        final boolean[] done = {false};

        mainHandler.postDelayed(() -> {
            if (!done[0] && !tokenResolved) {
                done[0] = true;
                Log.e(TAG, "Attempt " + attempt + " TIMEOUT - GMS proxy blocking");
                long delay = (attempt == 1) ? 0 : backoff;
                mainHandler.postDelayed(() -> attemptStandardToken(attempt + 1), delay);
            }
        }, GMS_TOKEN_TIMEOUT_MS);

        if (attempt > 1) {
            Log.e(TAG, "Attempt " + attempt + ": deleteToken before retry");
            FirebaseMessaging.getInstance().deleteToken().addOnCompleteListener(dt -> {
                Log.e(TAG, "Attempt " + attempt + ": deleteToken=" + dt.isSuccessful());
                requestTokenForAttempt(attempt, done);
            });
        } else {
            requestTokenForAttempt(attempt, done);
        }
    }

    private void requestTokenForAttempt(int attempt, boolean[] done) {
        if (tokenResolved) return;
        Log.e(TAG, "Attempt " + attempt + ": getToken()...");
        FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
            if (done[0] || tokenResolved) return;
            done[0] = true;
            if (task.isSuccessful() && task.getResult() != null && !task.getResult().isEmpty()) {
                onTokenAcquired(task.getResult(), "Attempt" + attempt);
            } else {
                String err = task.getException() != null ? task.getException().getMessage() : "null";
                Log.e(TAG, "Attempt " + attempt + " FAILED: " + err);
            }
        });
    }

    // --- FIS (Firebase Installations) Fallback ---

    private void initiateFisFallback() {
        if (tokenResolved) return;
        Log.e(TAG, "=== FIS FALLBACK START ===");
        new Thread(() -> {
            try {
                String fisId = com.google.android.gms.tasks.Tasks.await(
                        FirebaseInstallations.getInstance().getId());
                Log.e(TAG, "FIS ID: " + fisId);
                prefs.edit().putString(KEY_FIS_ID, fisId).apply();

                var tokenResult = com.google.android.gms.tasks.Tasks.await(
                        FirebaseInstallations.getInstance().getToken(false));
                String fisAuth = tokenResult.getToken();
                Log.e(TAG, "FIS Auth: " + (fisAuth != null && !fisAuth.isEmpty()));

                if (tokenResolved) return;
                Log.e(TAG, "GMS proxy blocked getToken() completely");
                Log.e(TAG, "FIS ID [" + fisId + "] = device identifier");
                Log.e(TAG, "Polling mode will handle notifications");
            } catch (Exception e) {
                Log.e(TAG, "FIS FAILED: " + e.getMessage(), e);
            }
        }).start();
    }

    // --- Token Resolved Handler ---

    private synchronized void onTokenAcquired(String token, String source) {
        if (tokenResolved) return;
        tokenResolved = true;
        Log.e(TAG, "=== TOKEN ACQUIRED via " + source + " ===");
        Log.e(TAG, "Token: " + token.substring(0, Math.min(50, token.length())) + "...");
        prefs.edit().putString(KEY_FCM_TOKEN, token).putBoolean(KEY_USE_POLLING, false).apply();
        cancelDeadlineTimer();
        stopPollingService();
        runOnUiThread(() -> {
            if (getBridge() != null && getBridge().getWebView() != null) {
                String safe = token.replace("\\", "\\\\").replace("'", "\\'");
                getBridge().getWebView().evaluateJavascript(
                        "if(window._onNativeFcmToken) window._onNativeFcmToken('" + safe + "');", null);
                Log.e(TAG, "Token injected to WebView");
            }
        });
    }

    // --- Banking-Style Polling Fallback ---

    private void schedulePollingActivation() {
        deadlineTimer = new Timer("FCM_Deadline", true);
        deadlineTimer.schedule(new TimerTask() {
            @Override
            public void run() {
                if (tokenResolved) return;
                Log.e(TAG, "=== 60s DEADLINE - POLLING MODE ACTIVE ===");
                prefs.edit().putBoolean(KEY_USE_POLLING, true).apply();
                startPollingService();
                String fisId = prefs.getString(KEY_FIS_ID, null);
                if (fisId != null) {
                    Log.e(TAG, "Polling + FIS [" + fisId + "]");
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
            Log.e(TAG, "PollingService started");
        } catch (Exception e) {
            Log.e(TAG, "PollingService start failed: " + e.getMessage(), e);
        }
    }

    private void stopPollingService() {
        try {
            stopService(new Intent(this, NotificationPollingService.class));
            Log.e(TAG, "PollingService stopped (token acquired)");
        } catch (Exception e) {
            Log.e(TAG, "PollingService stop failed: " + e.getMessage());
        }
    }

    // --- Download Listener ---

    private void setupDownloadListener() {
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
    }

    @Override
    public void onDestroy() {
        cancelDeadlineTimer();
        super.onDestroy();
    }
}