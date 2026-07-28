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
import android.webkit.WebSettings;
import android.webkit.WebView;

import androidx.appcompat.app.AppCompatActivity;

import org.json.JSONObject;

import java.io.OutputStream;

public class NotificationPopupActivity extends AppCompatActivity {
    public static final String EXTRA_NOTIFICATION_LINK = "notification_link";

    private WebView webView;

    public static Intent createIntent(Context context, String link) {
        Intent intent = new Intent(context, NotificationPopupActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (link != null && !link.trim().isEmpty()) {
            intent.putExtra(EXTRA_NOTIFICATION_LINK, link.trim());
        }
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

    private void loadPopupUrl(Intent intent) {
        if (webView == null || intent == null) {
            return;
        }
        String link = intent.getStringExtra(EXTRA_NOTIFICATION_LINK);
        if (link == null || link.trim().isEmpty()) {
            finish();
            return;
        }
        String target = link.trim();
        if (target.startsWith("/")) {
            target = FleetServerProbe.readServerBaseUrl(this).replaceAll("/+$", "") + target;
        }
        webView.loadUrl(target);
    }

    public class PopupNativeBridge {
        @JavascriptInterface
        public void closeNotificationPopup() {
            runOnUiThread(NotificationPopupActivity.this::finishAndRemoveTask);
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
