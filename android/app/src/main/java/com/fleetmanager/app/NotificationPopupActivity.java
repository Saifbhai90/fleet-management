package com.fleetmanager.app;

import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

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

    private static final class FieldRow {
        final String label;
        final String value;
        final int iconBg;
        final String emoji;

        FieldRow(String label, String value, int iconBg, String emoji) {
            this.label = label;
            this.value = value;
            this.iconBg = iconBg;
            this.emoji = emoji;
        }
    }

    private static final String[][] FIELD_SPECS = {
            {"CreateDateTime", "CreateDateTime", "#ede9fe", "📅"},
            {"Task Create Date/Time", "CreateDateTime", "#ede9fe", "📅"},
            {"Task ID", "Task ID", "#fef3c7", "🏷️"},
            {"Phone no", "Phone No", "#fce7f3", "📞"},
            {"Name", "Name", "#ede9fe", "👤"},
            {"Ambulance", "Ambulance", "#dcfce7", "🚑"},
            {"Pickup", "Pickup", "#fee2e2", "📍"},
            {"Destination", "Destination", "#e2e8f0", "🏁"},
            {"Close Category", "Close Category", "#e0e7ff", "📁"},
            {"Task Category", "Close Category", "#e0e7ff", "📁"},
            {"CompletedDateTime", "Completed", "#dbeafe", "✅"},
    };

    private String displayTitle(String raw) {
        if ("New Task Generate".equals(raw)) {
            return "New Task Generated";
        }
        return TextUtils.isEmpty(raw) ? "Notification" : raw;
    }

    private String formatReceived(String raw) {
        if (TextUtils.isEmpty(raw)) {
            return "Fleet Manager";
        }
        String cleaned = raw.replace('T', ' ').replaceAll("\\.\\d+", "");
        return "Received: " + cleaned;
    }

    private ParsedMessage parseMessageFields(String text) {
        ParsedMessage parsed = new ParsedMessage();
        String src = text == null ? "" : text.trim();
        if (src.isEmpty()) {
            return parsed;
        }

        StringBuilder keyAlt = new StringBuilder();
        for (String[] spec : FIELD_SPECS) {
            if (keyAlt.length() > 0) {
                keyAlt.append('|');
            }
            keyAlt.append(Pattern.quote(spec[0]));
        }
        Pattern pattern = Pattern.compile("(" + keyAlt + ")\\s*:", Pattern.CASE_INSENSITIVE);
        Matcher matcher = pattern.matcher(src);
        List<int[]> spans = new ArrayList<>();
        List<String> keys = new ArrayList<>();
        while (matcher.find()) {
            keys.add(matcher.group(1));
            spans.add(new int[]{matcher.start(), matcher.end()});
        }
        if (spans.isEmpty()) {
            parsed.leftover = src;
            return parsed;
        }
        if (spans.get(0)[0] > 0) {
            parsed.lead = src.substring(0, spans.get(0)[0]).trim().replaceAll("[.,;]+$", "").trim();
        }

        Map<String, String> values = new LinkedHashMap<>();
        for (int i = 0; i < spans.size(); i++) {
            int valueStart = spans.get(i)[1];
            int valueEnd = i + 1 < spans.size() ? spans.get(i + 1)[0] : src.length();
            String value = src.substring(valueStart, valueEnd).replaceAll("^[\\s,]+|[\\s,]+$", "").trim();
            String canon = keys.get(i);
            for (String[] spec : FIELD_SPECS) {
                if (spec[0].equalsIgnoreCase(canon)) {
                    canon = spec[0];
                    break;
                }
            }
            if ("Phone no".equalsIgnoreCase(canon)) {
                value = value.replaceAll("(?i)\\s+CLI\\s*:", " | CLI: ");
            }
            values.put(canon, value);
        }

        for (String[] spec : FIELD_SPECS) {
            String value = values.get(spec[0]);
            if (!TextUtils.isEmpty(value)) {
                parsed.rows.add(new FieldRow(spec[1], value, Color.parseColor(spec[2]), spec[3]));
            }
        }
        if (parsed.rows.isEmpty()) {
            parsed.leftover = src;
        }
        return parsed;
    }

    private static final class ParsedMessage {
        String lead = "";
        String leftover = "";
        final List<FieldRow> rows = new ArrayList<>();
    }

    private Bitmap renderNotificationBitmap(String title, String message, String createdAt, String source) {
        int width = 1080;
        int outerPad = 48;
        int cardPad = 48;
        int contentWidth = width - (outerPad * 2) - (cardPad * 2);

        Paint titlePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        titlePaint.setColor(Color.parseColor("#0f172a"));
        titlePaint.setTextSize(58f);
        titlePaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));

        Paint metaPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        metaPaint.setColor(Color.parseColor("#64748b"));
        metaPaint.setTextSize(30f);

        Paint badgeText = new Paint(Paint.ANTI_ALIAS_FLAG);
        badgeText.setColor(Color.parseColor("#1d4ed8"));
        badgeText.setTextSize(28f);
        badgeText.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));

        Paint labelPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        labelPaint.setColor(Color.parseColor("#334155"));
        labelPaint.setTextSize(28f);
        labelPaint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));

        Paint valuePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        valuePaint.setColor(Color.parseColor("#0f172a"));
        valuePaint.setTextSize(34f);

        Paint leadPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        leadPaint.setColor(Color.parseColor("#334155"));
        leadPaint.setTextSize(32f);

        Paint emojiPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        emojiPaint.setTextSize(34f);
        emojiPaint.setTextAlign(Paint.Align.CENTER);

        String shownTitle = displayTitle(title);
        String shownMeta = formatReceived(createdAt);
        ParsedMessage parsed = parseMessageFields(message);

        int badgeH = 56;
        int titleLines = wrapLines(shownTitle, titlePaint, contentWidth).size();
        int titleBlock = Math.max(70, titleLines * 66);
        int metaH = 42;
        int headerH = 24 + badgeH + 18 + titleBlock + 12 + metaH + 28;

        int bodyH = 0;
        List<String> leadLines = new ArrayList<>();
        if (!TextUtils.isEmpty(parsed.lead)) {
            leadLines = wrapLines(parsed.lead, leadPaint, contentWidth - 28);
            bodyH += 24 + (leadLines.size() * 42) + 18;
        }

        int rowIcon = 70;
        int rowGap = 10;
        List<List<String>> rowValueLines = new ArrayList<>();
        for (FieldRow row : parsed.rows) {
            int textW = contentWidth - rowIcon - 28;
            List<String> lines = wrapLines(row.value, valuePaint, textW);
            rowValueLines.add(lines);
            int textH = 30 + (lines.size() * 42);
            bodyH += Math.max(rowIcon + 16, textH + 20) + rowGap;
        }

        List<String> leftoverLines = new ArrayList<>();
        if (parsed.rows.isEmpty()) {
            leftoverLines = wrapLines(
                    TextUtils.isEmpty(parsed.leftover) ? message : parsed.leftover,
                    valuePaint,
                    contentWidth
            );
            bodyH += Math.max(80, leftoverLines.size() * 46 + 24);
        }

        int height = outerPad * 2 + cardPad * 2 + headerH + bodyH + 36;
        Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        canvas.drawColor(Color.parseColor("#0f172a"));

        Paint cardPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
        cardPaint.setColor(Color.WHITE);
        float left = outerPad;
        float top = outerPad;
        float right = width - outerPad;
        float bottom = height - outerPad;
        canvas.drawRoundRect(left, top, right, bottom, 40f, 40f, cardPaint);

        float x = left + cardPad;
        float y = top + cardPad;

        Paint badgeBg = new Paint(Paint.ANTI_ALIAS_FLAG);
        badgeBg.setColor(Color.parseColor("#eff6ff"));
        String badgeLabel = "ufone_task_event".equals(source) ? "Task Notification" : "Notification";
        float badgeW = badgeText.measureText(badgeLabel) + 36f;
        canvas.drawRoundRect(x, y, x + badgeW, y + badgeH, 28f, 28f, badgeBg);
        canvas.drawText(badgeLabel, x + 18f, y + 38f, badgeText);
        y += badgeH + 22f;

        y = drawWrappedText(canvas, shownTitle, x, y + 48f, contentWidth, titlePaint, 66) + 18f;
        canvas.drawText(shownMeta, x, y, metaPaint);
        y += metaH + 18f;

        Paint divider = new Paint(Paint.ANTI_ALIAS_FLAG);
        divider.setColor(Color.parseColor("#eef2f7"));
        divider.setStrokeWidth(3f);
        canvas.drawLine(left + 24f, y, right - 24f, y, divider);
        y += 22f;

        if (!leadLines.isEmpty()) {
            Paint leadBg = new Paint(Paint.ANTI_ALIAS_FLAG);
            leadBg.setColor(Color.parseColor("#f8fafc"));
            float leadH = 24f + leadLines.size() * 42f;
            canvas.drawRoundRect(x, y, x + contentWidth, y + leadH, 18f, 18f, leadBg);
            float leadY = y + 34f;
            for (String line : leadLines) {
                canvas.drawText(line, x + 14f, leadY, leadPaint);
                leadY += 42f;
            }
            y += leadH + 16f;
        }

        for (int i = 0; i < parsed.rows.size(); i++) {
            FieldRow row = parsed.rows.get(i);
            List<String> valueLines = rowValueLines.get(i);
            int textH = 30 + (valueLines.size() * 42);
            float rowH = Math.max(rowIcon + 16, textH + 20);

            if (i % 2 == 0) {
                Paint zebra = new Paint(Paint.ANTI_ALIAS_FLAG);
                zebra.setColor(Color.parseColor("#f8fafc"));
                canvas.drawRoundRect(x - 4f, y, x + contentWidth + 4f, y + rowH, 18f, 18f, zebra);
            }

            Paint iconBg = new Paint(Paint.ANTI_ALIAS_FLAG);
            iconBg.setColor(row.iconBg);
            float iconTop = y + (rowH - rowIcon) / 2f;
            canvas.drawRoundRect(x, iconTop, x + rowIcon, iconTop + rowIcon, 18f, 18f, iconBg);
            Paint.FontMetrics fm = emojiPaint.getFontMetrics();
            float emojiBaseline = iconTop + rowIcon / 2f - (fm.ascent + fm.descent) / 2f;
            canvas.drawText(row.emoji, x + rowIcon / 2f, emojiBaseline, emojiPaint);

            float textX = x + rowIcon + 22f;
            float textY = y + 36f;
            canvas.drawText(row.label, textX, textY, labelPaint);
            textY += 42f;
            for (String line : valueLines) {
                canvas.drawText(line, textX, textY, valuePaint);
                textY += 42f;
            }
            y += rowH + rowGap;
        }

        if (!leftoverLines.isEmpty()) {
            float textY = y + 36f;
            for (String line : leftoverLines) {
                canvas.drawText(line, x, textY, valuePaint);
                textY += 46f;
            }
        }

        return bitmap;
    }

    private List<String> wrapLines(String text, Paint paint, int maxWidth) {
        List<String> lines = new ArrayList<>();
        if (text == null || text.trim().isEmpty()) {
            return lines;
        }
        String[] words = text.trim().split("\\s+");
        StringBuilder line = new StringBuilder();
        for (String word : words) {
            // Hard-split very long tokens so nothing gets clipped.
            if (paint.measureText(word) > maxWidth) {
                if (line.length() > 0) {
                    lines.add(line.toString());
                    line = new StringBuilder();
                }
                String remaining = word;
                while (paint.measureText(remaining) > maxWidth && remaining.length() > 1) {
                    int cut = remaining.length();
                    while (cut > 1 && paint.measureText(remaining.substring(0, cut)) > maxWidth) {
                        cut--;
                    }
                    lines.add(remaining.substring(0, cut));
                    remaining = remaining.substring(cut);
                }
                line = new StringBuilder(remaining);
                continue;
            }
            String trial = line.length() == 0 ? word : (line + " " + word);
            if (paint.measureText(trial) > maxWidth && line.length() > 0) {
                lines.add(line.toString());
                line = new StringBuilder(word);
            } else {
                line = new StringBuilder(trial);
            }
        }
        if (line.length() > 0) {
            lines.add(line.toString());
        }
        if (lines.isEmpty()) {
            lines.add(text);
        }
        return lines;
    }

    private float drawWrappedText(Canvas canvas, String text, float x, float y, int maxWidth, Paint paint, int lineHeight) {
        List<String> lines = wrapLines(text, paint, maxWidth);
        float drawY = y;
        for (String line : lines) {
            canvas.drawText(line, x, drawY, paint);
            drawY += lineHeight;
        }
        return drawY - lineHeight;
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
