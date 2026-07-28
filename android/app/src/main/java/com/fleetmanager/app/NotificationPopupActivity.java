package com.fleetmanager.app;

import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.TextUtils;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.appcompat.app.AppCompatActivity;

import org.json.JSONObject;

import java.io.OutputStream;

public class NotificationPopupActivity extends AppCompatActivity {
    public static final String EXTRA_NOTIFICATION_LINK = "notification_link";
    public static final String EXTRA_NOTIFICATION_TITLE = "notification_title";
    public static final String EXTRA_NOTIFICATION_BODY = "notification_body";
    public static final String EXTRA_SAVE_ENABLED = "notification_save_enabled";
    public static final String EXTRA_POPUP_SOURCE = "notification_popup_source";
    public static final String EXTRA_CREATED_AT = "notification_created_at";

    private static final String OFFLINE_POPUP_ASSET = "file:///android_asset/notification_popup.html";

    private WebView webView;

    public static Intent createIntent(Context context, String link) {
        return createIntent(context, link, "", "", false, "generic", "");
    }

    public static Intent createIntent(
            Context context,
            String link,
            String title,
            String body,
            boolean saveEnabled,
            String popupSource,
            String createdAt
    ) {
        Intent intent = new Intent(context, NotificationPopupActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (link != null && !link.trim().isEmpty()) {
            intent.putExtra(EXTRA_NOTIFICATION_LINK, link.trim());
        }
        intent.putExtra(EXTRA_NOTIFICATION_TITLE, title != null ? title : "");
        intent.putExtra(EXTRA_NOTIFICATION_BODY, body != null ? body : "");
        intent.putExtra(EXTRA_SAVE_ENABLED, saveEnabled);
        intent.putExtra(EXTRA_POPUP_SOURCE, popupSource != null && !popupSource.isEmpty() ? popupSource : "generic");
        intent.putExtra(EXTRA_CREATED_AT, createdAt != null ? createdAt : "");
        return intent;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        webView.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));
        webView.setBackgroundColor(Color.TRANSPARENT);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        webView.setWebChromeClient(new WebChromeClient());
        webView.addJavascriptInterface(new PopupNativeBridge(), "_fleetNative");

        setContentView(webView);
        loadPopupUrl(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        loadPopupUrl(intent);
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private String resolvePopupLink(String link) {
        String target = link.trim();
        if (target.startsWith("/")) {
            String base = FleetServerProbe.readServerBaseUrl(this);
            if (base != null && !base.isEmpty()) {
                target = base.replaceAll("/+$", "") + target;
            }
        }
        return target;
    }

    private void loadOfflinePopup() {
        if (webView == null) {
            return;
        }
        webView.setWebViewClient(new WebViewClient());
        webView.loadUrl(OFFLINE_POPUP_ASSET);
    }

    private void loadPopupUrl(Intent intent) {
        if (webView == null || intent == null) {
            return;
        }
        String link = intent.getStringExtra(EXTRA_NOTIFICATION_LINK);
        if (link == null || link.trim().isEmpty()) {
            finish();
            return;
        }

        if (!FleetServerProbe.hasDeviceInternet(this)) {
            loadOfflinePopup();
            return;
        }

        final String serverUrl = resolvePopupLink(link);
        webView.setWebViewClient(new WebViewClient() {
            private boolean usedFallback = false;

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (usedFallback || request == null || !request.isForMainFrame()) {
                    return;
                }
                usedFallback = true;
                loadOfflinePopup();
            }

            @Override
            @SuppressWarnings("deprecation")
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                if (usedFallback) {
                    return;
                }
                usedFallback = true;
                loadOfflinePopup();
            }
        });
        webView.loadUrl(serverUrl);
    }

    private String extractTokenFromLink(String link) {
        if (link == null || link.isEmpty()) {
            return "";
        }
        int idx = link.indexOf("t=");
        if (idx < 0) {
            return "";
        }
        String tokenPart = link.substring(idx + 2);
        int amp = tokenPart.indexOf('&');
        if (amp >= 0) {
            tokenPart = tokenPart.substring(0, amp);
        }
        return tokenPart.trim();
    }

    public class PopupNativeBridge {
        @JavascriptInterface
        public void closeNotificationPopup() {
            runOnUiThread(NotificationPopupActivity.this::finishAndRemoveTask);
        }

        @JavascriptInterface
        public String getNotificationPayload() {
            Intent intent = getIntent();
            if (intent == null) {
                return "{}";
            }
            try {
                JSONObject obj = new JSONObject();
                String link = intent.getStringExtra(EXTRA_NOTIFICATION_LINK);
                obj.put("link", link != null ? link : "");
                obj.put("title", intent.getStringExtra(EXTRA_NOTIFICATION_TITLE));
                obj.put("message", intent.getStringExtra(EXTRA_NOTIFICATION_BODY));
                obj.put("save_enabled", intent.getBooleanExtra(EXTRA_SAVE_ENABLED, false));
                obj.put("source", intent.getStringExtra(EXTRA_POPUP_SOURCE));
                obj.put("created_at", intent.getStringExtra(EXTRA_CREATED_AT));
                obj.put("token", extractTokenFromLink(link));
                String base = FleetServerProbe.readServerBaseUrl(NotificationPopupActivity.this);
                obj.put("server_base", base != null ? base : "");
                return obj.toString();
            } catch (Exception e) {
                return "{}";
            }
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
                return "Save failed.";
            }
        }
    }

    private Bitmap renderNotificationBitmap(String title, String message, String createdAt, String source) {
        int width = 1080;
        int padding = 72;
        int cardPadding = 54;
        int y;

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
        badgePaint.setColor(Color.parseColor("#13243c"));
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
}
