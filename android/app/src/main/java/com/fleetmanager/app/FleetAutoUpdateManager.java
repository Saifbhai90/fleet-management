package com.fleetmanager.app;

import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.WindowManager;
import android.webkit.URLUtil;

import androidx.core.content.FileProvider;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * FleetAutoUpdateManager — handles silent background APK download + non-cancellable install prompt.
 *
 * Flow:
 * 1. checkForUpdate() — fetches /api/app/check-update from server
 * 2. If newer version → silently downloads APK via DownloadManager (no popup)
 * 3. On download complete → BroadcastReceiver fires → shows non-cancellable install dialog
 * 4. On app open → checkPendingInstall() → if APK already downloaded, show install dialog immediately
 */
public class FleetAutoUpdateManager {

    private static final String TAG = "FleetAutoUpdate";
    private static final String PREFS = "fleet_update_prefs";
    private static final String KEY_PENDING_APK_PATH = "pending_apk_path";
    private static final String KEY_PENDING_VERSION = "pending_version";
    private static final String KEY_DOWNLOAD_ID = "download_id";
    private static final String KEY_IS_DOWNLOADING = "is_downloading";

    private final Context context;
    private final SharedPreferences prefs;
    private final Handler mainHandler;
    private final ExecutorService executor;
    private BroadcastReceiver downloadReceiver;
    private AlertDialog installDialog;
    private String serverBaseUrl;

    public FleetAutoUpdateManager(Context context) {
        this.context = context;
        this.prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        this.mainHandler = new Handler(Looper.getMainLooper());
        this.executor = Executors.newSingleThreadExecutor();
        this.serverBaseUrl = resolveServerBaseUrl();
    }

    /** Resolve server base URL from Capacitor config or fallback to WebView URL */
    private String resolveServerBaseUrl() {
        try {
            // Read capacitor.config.json from assets
            android.content.res.AssetManager am = context.getAssets();
            java.io.InputStream is = am.open("capacitor.config.json");
            BufferedReader reader = new BufferedReader(new InputStreamReader(is));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) sb.append(line);
            reader.close();
            JSONObject config = new JSONObject(sb.toString());
            JSONObject server = config.optJSONObject("server");
            if (server != null) {
                String url = server.optString("url", null);
                if (url != null && !url.isEmpty()) {
                    return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "Could not read capacitor.config.json: " + e.getMessage());
        }
        // Fallback — try to get from WebView if running in MainActivity
        return null;
    }

    /** Set server URL from outside (e.g., from WebView URL when available) */
    public void setServerBaseUrl(String url) {
        if (url != null && !url.isEmpty()) {
            this.serverBaseUrl = url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
        }
    }

    /** Get current app version name */
    private String getCurrentVersion() {
        try {
            return context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0).versionName;
        } catch (PackageManager.NameNotFoundException e) {
            return "0.0.0";
        }
    }

    /** Compare version strings like "2.0.2" vs "2.0.3" → returns -1, 0, 1 */
    private int compareVersions(String a, String b) {
        if (a == null) a = "0.0.0";
        if (b == null) b = "0.0.0";
        String[] pa = a.split("\\.");
        String[] pb = b.split("\\.");
        for (int i = 0; i < Math.max(pa.length, pb.length); i++) {
            int na = i < pa.length ? Integer.parseInt(pa[i]) : 0;
            int nb = i < pb.length ? Integer.parseInt(pb[i]) : 0;
            if (na < nb) return -1;
            if (na > nb) return 1;
        }
        return 0;
    }

    /**
     * Main entry: check server for update. If newer version found, start silent download.
     * Safe to call from any thread — network call runs on background executor.
     */
    public void checkForUpdate() {
        if (serverBaseUrl == null || serverBaseUrl.isEmpty()) {
            Log.w(TAG, "No server URL — skipping update check");
            return;
        }
        // If already downloading or pending install, skip
        if (prefs.getBoolean(KEY_IS_DOWNLOADING, false)) {
            Log.d(TAG, "Download already in progress — skipping check");
            return;
        }
        if (prefs.getString(KEY_PENDING_APK_PATH, null) != null) {
            Log.d(TAG, "Pending APK already downloaded — skipping check");
            return;
        }

        executor.execute(() -> {
            try {
                String apiUrl = serverBaseUrl + "/api/app/check-update";
                HttpURLConnection conn = (HttpURLConnection) new URL(apiUrl).openConnection();
                conn.setConnectTimeout(10000);
                conn.setReadTimeout(10000);
                conn.setRequestProperty("Accept", "application/json");
                conn.connect();

                if (conn.getResponseCode() != 200) {
                    Log.w(TAG, "Update check failed: HTTP " + conn.getResponseCode());
                    conn.disconnect();
                    return;
                }

                BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
                StringBuilder sb = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) sb.append(line);
                reader.close();
                conn.disconnect();

                JSONObject data = new JSONObject(sb.toString());
                String latestVersion = data.optString("latest_version", "0.0.0");
                String apkUrl = data.optString("apk_url", null);
                String apkFilename = data.optString("apk_filename", "fleet-manager-update.apk");

                if (latestVersion.equals("0.0.0") || apkUrl == null) {
                    Log.d(TAG, "No update available on server");
                    return;
                }

                String currentVersion = getCurrentVersion();
                Log.d(TAG, "Current: " + currentVersion + " | Latest: " + latestVersion);

                if (compareVersions(currentVersion, latestVersion) >= 0) {
                    Log.d(TAG, "App is up to date");
                    return;
                }

                // Normalize APK URL — if relative, prepend server base
                if (!apkUrl.startsWith("http")) {
                    apkUrl = serverBaseUrl + (apkUrl.startsWith("/") ? "" : "/") + apkUrl;
                }

                startSilentDownload(apkUrl, apkFilename, latestVersion);

            } catch (Exception e) {
                Log.e(TAG, "Update check failed: " + e.getMessage());
            }
        });
    }

    /** Start silent APK download via Android DownloadManager */
    private void startSilentDownload(String apkUrl, String filename, String version) {
        try {
            DownloadManager dm = (DownloadManager) context.getSystemService(Context.DOWNLOAD_SERVICE);
            if (dm == null) {
                Log.e(TAG, "DownloadManager not available");
                return;
            }

            DownloadManager.Request req = new DownloadManager.Request(Uri.parse(apkUrl));
            req.setTitle("Fleet Manager Update v" + version);
            req.setDescription("Downloading update...");
            // Silent — no notification during download, only on completion
            req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            req.setMimeType("application/vnd.android.package-archive");
            req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename);
            // Only download over WiFi (optional — remove to allow cellular)
            // req.setAllowedOverMetered(true);

            long downloadId = dm.enqueue(req);

            prefs.edit()
                    .putBoolean(KEY_IS_DOWNLOADING, true)
                    .putLong(KEY_DOWNLOAD_ID, downloadId)
                    .putString(KEY_PENDING_VERSION, version)
                    .apply();

            Log.d(TAG, "Silent download started: " + filename + " (id=" + downloadId + ")");

            // Register receiver for download complete
            registerDownloadReceiver();

        } catch (Exception e) {
            Log.e(TAG, "Download start failed: " + e.getMessage());
        }
    }

    /** Register BroadcastReceiver for DownloadManager.ACTION_DOWNLOAD_COMPLETE */
    private void registerDownloadReceiver() {
        if (downloadReceiver != null) return;

        downloadReceiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context ctx, Intent intent) {
                long id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1);
                long expectedId = prefs.getLong(KEY_DOWNLOAD_ID, -1);
                if (id != expectedId) return;

                handleDownloadComplete(id);
            }
        };

        IntentFilter filter = new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(downloadReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            context.registerReceiver(downloadReceiver, filter);
        }
        Log.d(TAG, "Download receiver registered");
    }

    /** Handle download completion — verify and save path */
    private void handleDownloadComplete(long downloadId) {
        DownloadManager dm = (DownloadManager) context.getSystemService(Context.DOWNLOAD_SERVICE);
        if (dm == null) return;

        DownloadManager.Query query = new DownloadManager.Query().setFilterById(downloadId);
        Cursor cursor = dm.query(query);
        try {
            if (cursor == null || !cursor.moveToFirst()) {
                Log.e(TAG, "Download status unknown");
                prefs.edit().putBoolean(KEY_IS_DOWNLOADING, false).apply();
                return;
            }

            int statusIdx = cursor.getColumnIndex(DownloadManager.COLUMN_STATUS);
            int status = statusIdx >= 0 ? cursor.getInt(statusIdx) : -1;
            if (status != DownloadManager.STATUS_SUCCESSFUL) {
                int reasonIdx = cursor.getColumnIndex(DownloadManager.COLUMN_REASON);
                int reason = reasonIdx >= 0 ? cursor.getInt(reasonIdx) : 0;
                Log.e(TAG, "Download failed (reason " + reason + ")");
                prefs.edit()
                        .putBoolean(KEY_IS_DOWNLOADING, false)
                        .remove(KEY_DOWNLOAD_ID)
                        .apply();
                return;
            }

            int uriIdx = cursor.getColumnIndex(DownloadManager.COLUMN_LOCAL_URI);
            String localUri = uriIdx >= 0 ? cursor.getString(uriIdx) : null;
            if (localUri == null || localUri.isEmpty()) {
                Log.e(TAG, "Download path missing");
                prefs.edit().putBoolean(KEY_IS_DOWNLOADING, false).apply();
                return;
            }

            // Convert to file path
            Uri uri = Uri.parse(localUri);
            File apkFile;
            if ("file".equals(uri.getScheme())) {
                apkFile = new File(uri.getPath());
            } else {
                // Try Downloads directory
                apkFile = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                        prefs.getString(KEY_PENDING_VERSION, "update") + ".apk");
            }

            if (!apkFile.exists()) {
                Log.e(TAG, "APK file not found at: " + apkFile.getAbsolutePath());
                prefs.edit().putBoolean(KEY_IS_DOWNLOADING, false).apply();
                return;
            }

            String apkPath = apkFile.getAbsolutePath();
            Log.d(TAG, "Download complete: " + apkPath);

            prefs.edit()
                    .putBoolean(KEY_IS_DOWNLOADING, false)
                    .putString(KEY_PENDING_APK_PATH, apkPath)
                    .apply();

            // Show install dialog on UI thread
            mainHandler.post(() -> showInstallDialog());

        } finally {
            if (cursor != null) cursor.close();
            unregisterDownloadReceiver();
        }
    }

    /** Unregister download receiver */
    private void unregisterDownloadReceiver() {
        if (downloadReceiver != null) {
            try {
                context.unregisterReceiver(downloadReceiver);
            } catch (Exception ignored) {}
            downloadReceiver = null;
        }
    }

    /**
     * Check if a pending APK install exists. Call this on app open.
     * If APK is downloaded → show install dialog immediately.
     * If download is in progress → do nothing (old version runs, dialog appears when download completes).
     */
    public void checkPendingInstall() {
        String apkPath = prefs.getString(KEY_PENDING_APK_PATH, null);
        if (apkPath == null || apkPath.isEmpty()) {
            // No pending APK — check if we should start a new update check
            if (!prefs.getBoolean(KEY_IS_DOWNLOADING, false)) {
                // Trigger a background update check
                checkForUpdate();
            }
            return;
        }

        File apkFile = new File(apkPath);
        if (!apkFile.exists()) {
            // File was deleted — clear pending state
            prefs.edit().remove(KEY_PENDING_APK_PATH).remove(KEY_PENDING_VERSION).apply();
            checkForUpdate();
            return;
        }

        // APK exists — show install dialog
        mainHandler.post(this::showInstallDialog);
    }

    /** Show non-cancellable install dialog — user MUST tap Install */
    public void showInstallDialog() {
        String apkPath = prefs.getString(KEY_PENDING_APK_PATH, null);
        if (apkPath == null || apkPath.isEmpty()) return;

        File apkFile = new File(apkPath);
        if (!apkFile.exists()) {
            prefs.edit().remove(KEY_PENDING_APK_PATH).remove(KEY_PENDING_VERSION).apply();
            return;
        }

        // Dismiss existing dialog if any
        if (installDialog != null && installDialog.isShowing()) {
            return; // Already showing
        }

        String version = prefs.getString(KEY_PENDING_VERSION, "new version");

        AlertDialog.Builder builder = new AlertDialog.Builder(context);
        builder.setTitle("Update Ready");
        builder.setMessage("Fleet Manager v" + version + " is ready to install. Tap Install to continue.");
        builder.setCancelable(false);
        builder.setPositiveButton("Install", (dialog, which) -> {
            launchInstaller(apkFile);
        });
        // No negative button, no cancel — user MUST install
        installDialog = builder.create();

        // Make dialog non-cancellable by back button
        installDialog.setOnCancelListener(dialog -> {
            // Re-show immediately if user somehow cancels
            mainHandler.postDelayed(this::showInstallDialog, 100);
        });

        // Prevent dialog from being dismissed by outside touch
        installDialog.setCanceledOnTouchOutside(false);

        try {
            installDialog.getWindow().setType(WindowManager.LayoutParams.TYPE_APPLICATION_ATTACHED_DIALOG);
        } catch (Exception ignored) {}

        try {
            installDialog.show();
        } catch (Exception e) {
            Log.e(TAG, "Could not show install dialog: " + e.getMessage());
        }
    }

    /** Launch Android package installer for the APK */
    private void launchInstaller(File apkFile) {
        try {
            Uri uri;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                uri = FileProvider.getUriForFile(context,
                        context.getPackageName() + ".fileprovider", apkFile);
            } else {
                uri = Uri.fromFile(apkFile);
            }

            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(uri, "application/vnd.android.package-archive");
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);

            context.startActivity(intent);
            Log.d(TAG, "Installer launched for: " + apkFile.getAbsolutePath());
        } catch (Exception e) {
            Log.e(TAG, "Installer launch failed: " + e.getMessage());
            // Fallback: try with ACTION_INSTALL_PACKAGE
            try {
                Uri uri = FileProvider.getUriForFile(context,
                        context.getPackageName() + ".fileprovider", apkFile);
                Intent intent = new Intent(Intent.ACTION_INSTALL_PACKAGE);
                intent.setData(uri);
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(intent);
            } catch (Exception e2) {
                Log.e(TAG, "Fallback installer also failed: " + e2.getMessage());
            }
        }
    }

    /** Clean up — call from Activity.onDestroy */
    public void onDestroy() {
        unregisterDownloadReceiver();
        if (installDialog != null && installDialog.isShowing()) {
            installDialog.dismiss();
        }
        executor.shutdown();
    }
}
