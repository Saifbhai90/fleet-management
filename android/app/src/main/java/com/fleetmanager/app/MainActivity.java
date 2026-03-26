package com.fleetmanager.app;

import android.os.Bundle;
import android.os.Environment;
import android.webkit.WebView;
import android.webkit.URLUtil;
import android.widget.Toast;
import android.app.DownloadManager;
import android.content.Context;
import android.net.Uri;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        getBridge().getWebView().setDownloadListener(
            (url, userAgent, contentDisposition, mimetype, contentLength) -> {
                try {
                    DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                    String fileName = URLUtil.guessFileName(url, contentDisposition, mimetype);
                    request.setTitle(fileName);
                    request.setDescription("Downloading file...");
                    request.setNotificationVisibility(
                        DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                    request.setDestinationInExternalPublicDir(
                        Environment.DIRECTORY_DOWNLOADS, fileName);
                    request.setMimeType(mimetype);
                    request.addRequestHeader("User-Agent", userAgent);
                    request.addRequestHeader("Cookie",
                        android.webkit.CookieManager.getInstance().getCookie(url));

                    DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                    if (dm != null) {
                        dm.enqueue(request);
                        Toast.makeText(this, "Downloading: " + fileName,
                            Toast.LENGTH_SHORT).show();
                    }
                } catch (Exception e) {
                    Toast.makeText(this, "Download failed: " + e.getMessage(),
                        Toast.LENGTH_LONG).show();
                }
            }
        );
    }
}
