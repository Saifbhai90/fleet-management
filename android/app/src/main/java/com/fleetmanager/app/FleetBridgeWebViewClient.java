package com.fleetmanager.app;

import android.graphics.Bitmap;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;

import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;

/**
 * Intercepts main-frame load failures so the native network overlay is shown
 * instead of Android's default "Webpage not available" page.
 */
public class FleetBridgeWebViewClient extends BridgeWebViewClient {

    public interface LoadStateCallback {
        void onMainFrameLoadFailed();

        void onMainFrameLoadSucceeded(String url);
    }

    private final LoadStateCallback callback;

    public FleetBridgeWebViewClient(Bridge bridge, LoadStateCallback callback) {
        super(bridge);
        this.callback = callback;
    }

    @Override
    public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
        if (request != null && request.isForMainFrame()) {
            callback.onMainFrameLoadFailed();
            view.loadUrl("about:blank");
            return;
        }
        super.onReceivedError(view, request, error);
    }

    @Override
    public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse errorResponse) {
        if (request != null && request.isForMainFrame() && errorResponse != null
                && errorResponse.getStatusCode() >= 500) {
            callback.onMainFrameLoadFailed();
            view.loadUrl("about:blank");
            return;
        }
        super.onReceivedHttpError(view, request, errorResponse);
    }

    @Override
    public void onPageFinished(WebView view, String url) {
        super.onPageFinished(view, url);
        if (url == null || "about:blank".equals(url) || view.getProgress() < 100) {
            return;
        }
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            return;
        }
        callback.onMainFrameLoadSucceeded(url);
    }

    @Override
    public void onPageStarted(WebView view, String url, Bitmap favicon) {
        super.onPageStarted(view, url, favicon);
    }
}
