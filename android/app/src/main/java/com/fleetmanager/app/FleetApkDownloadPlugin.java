package com.fleetmanager.app;

import android.app.DownloadManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;

import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;

/**
 * Reliable APK download via Android DownloadManager (avoids WebView base64 size limits).
 */
@CapacitorPlugin(name = "FleetApkDownload")
public class FleetApkDownloadPlugin extends Plugin {

    private BroadcastReceiver downloadReceiver;
    private long pendingDownloadId = -1L;
    private PluginCall pendingCall;

    @PluginMethod
    public void download(PluginCall call) {
        String url = call.getString("url");
        String filename = call.getString("filename", "fleet-manager-update.apk");
        if (url == null || url.isEmpty()) {
            call.reject("Missing url");
            return;
        }
        if (getContext() == null) {
            call.reject("No context");
            return;
        }

        cleanupReceiver();

        DownloadManager dm = (DownloadManager) getContext().getSystemService(Context.DOWNLOAD_SERVICE);
        if (dm == null) {
            call.reject("DownloadManager not available");
            return;
        }

        try {
            DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
            req.setTitle("Fleet Manager Update");
            req.setDescription("Downloading " + filename);
            req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            req.setMimeType("application/vnd.android.package-archive");
            req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename);

            pendingCall = call;
            pendingDownloadId = dm.enqueue(req);

            downloadReceiver = new BroadcastReceiver() {
                @Override
                public void onReceive(Context context, Intent intent) {
                    long id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1);
                    if (id != pendingDownloadId) return;
                    handleDownloadComplete(dm, id);
                }
            };

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                getContext().registerReceiver(
                        downloadReceiver,
                        new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE),
                        Context.RECEIVER_NOT_EXPORTED);
            } else {
                getContext().registerReceiver(
                        downloadReceiver,
                        new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE));
            }
        } catch (Exception e) {
            cleanupReceiver();
            call.reject(e.getMessage() != null ? e.getMessage() : "Download failed");
        }
    }

    private void handleDownloadComplete(DownloadManager dm, long id) {
        PluginCall call = pendingCall;
        cleanupReceiver();
        if (call == null) return;

        DownloadManager.Query query = new DownloadManager.Query().setFilterById(id);
        Cursor cursor = dm.query(query);
        try {
            if (cursor == null || !cursor.moveToFirst()) {
                call.reject("Download status unknown");
                return;
            }
            int statusIdx = cursor.getColumnIndex(DownloadManager.COLUMN_STATUS);
            int status = statusIdx >= 0 ? cursor.getInt(statusIdx) : -1;
            if (status != DownloadManager.STATUS_SUCCESSFUL) {
                int reasonIdx = cursor.getColumnIndex(DownloadManager.COLUMN_REASON);
                int reason = reasonIdx >= 0 ? cursor.getInt(reasonIdx) : 0;
                call.reject("Download failed (reason " + reason + ")");
                return;
            }

            int uriIdx = cursor.getColumnIndex(DownloadManager.COLUMN_LOCAL_URI);
            String localUri = uriIdx >= 0 ? cursor.getString(uriIdx) : null;
            if (localUri == null || localUri.isEmpty()) {
                call.reject("Download path missing");
                return;
            }

            Uri installUri = Uri.parse(localUri);
            if ("file".equals(installUri.getScheme())) {
                File file = new File(installUri.getPath());
                installUri = FileProvider.getUriForFile(
                        getContext(),
                        getContext().getPackageName() + ".fileprovider",
                        file);
            }

            JSObject ret = new JSObject();
            ret.put("uri", installUri.toString());
            ret.put("filename", call.getString("filename", "fleet-manager-update.apk"));
            int sizeIdx = cursor.getColumnIndex(DownloadManager.COLUMN_TOTAL_SIZE_BYTES);
            if (sizeIdx >= 0) {
                ret.put("bytes", cursor.getLong(sizeIdx));
            }
            call.resolve(ret);
        } finally {
            if (cursor != null) cursor.close();
        }
    }

    @PluginMethod
    public void openInstaller(PluginCall call) {
        String uriStr = call.getString("uri");
        if (uriStr == null || uriStr.isEmpty()) {
            call.reject("Missing uri");
            return;
        }
        try {
            Uri uri = Uri.parse(uriStr);
            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(uri, "application/vnd.android.package-archive");
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
            call.resolve();
        } catch (Exception e) {
            call.reject(e.getMessage() != null ? e.getMessage() : "Could not open installer");
        }
    }

    private void cleanupReceiver() {
        if (downloadReceiver != null && getContext() != null) {
            try {
                getContext().unregisterReceiver(downloadReceiver);
            } catch (Exception ignored) {}
        }
        downloadReceiver = null;
        pendingCall = null;
        pendingDownloadId = -1L;
    }

    @Override
    protected void handleOnDestroy() {
        cleanupReceiver();
        super.handleOnDestroy();
    }
}
