package com.fleetmanager.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.IBinder;

import androidx.core.app.NotificationCompat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashSet;
import java.util.Set;
import java.util.Timer;
import java.util.TimerTask;

public class NotificationPollingService extends Service {

    private static final String PREFS_NAME = "fcm_prefs";
    private static final String KEY_USE_POLLING = "use_polling";
    private static final String KEY_SEEN_IDS = "polling_seen_notification_ids";

    private static final String SERVER_BASE = "https://fleet-management-xdvj.onrender.com";
    private static final long POLL_INTERVAL_MS = 2 * 60 * 1000;
    private static final long RETRY_AFTER_ERROR_MS = 5 * 60 * 1000;
    private static final String SYNC_CHANNEL_ID = "sync_service";
    private static final String NOTIF_CHANNEL_ID = "fleet_attendance";
    private static final int FOREGROUND_ID = 9001;

    private Timer pollTimer;
    private SharedPreferences prefs;
    private Set<String> seenIds;
    private int consecutiveErrors = 0;

    @Override
    public void onCreate() {
        super.onCreate();
        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        seenIds = new HashSet<>(prefs.getStringSet(KEY_SEEN_IDS, new HashSet<>()));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        showForegroundNotification();
        startPolling();
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    private void showForegroundNotification() {
        NotificationManager mgr = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (mgr == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(
                    SYNC_CHANNEL_ID, "Sync Service", NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("Keeps notification sync active");
            ch.setShowBadge(false);
            mgr.createNotificationChannel(ch);
        }
        Notification notif = new NotificationCompat.Builder(this, SYNC_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_popup_reminder)
                .setContentTitle("Fleet Manager")
                .setContentText("Notification sync active")
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setOngoing(true)
                .build();
        startForeground(FOREGROUND_ID, notif);
    }

    private void startPolling() {
        if (pollTimer != null) pollTimer.cancel();
        pollTimer = new Timer("NotifPoll", true);
        pollTimer.scheduleAtFixedRate(new TimerTask() {
            @Override
            public void run() {
                if (!prefs.getBoolean(KEY_USE_POLLING, false)) {
                    stopSelf();
                    return;
                }
                pollServer();
            }
        }, 5000, POLL_INTERVAL_MS);
    }

    private void pollServer() {
        try {
            String cookie = getSessionCookie();
            if (cookie == null || cookie.isEmpty()) return;

            URL url = new URL(SERVER_BASE + "/api/poll-notifications");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("GET");
            conn.setRequestProperty("Cookie", cookie);
            conn.setRequestProperty("X-Requested-With", "XMLHttpRequest");
            conn.setRequestProperty("Accept", "application/json");
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(15000);

            int code = conn.getResponseCode();

            if (code == 404) {
                consecutiveErrors++;
                if (consecutiveErrors >= 3) {
                    rescheduleWithInterval(RETRY_AFTER_ERROR_MS);
                }
                return;
            }
            if (code == 401) return;
            if (code != 200) {
                consecutiveErrors++;
                return;
            }

            consecutiveErrors = 0;

            BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) sb.append(line);
            reader.close();

            JSONObject resp = new JSONObject(sb.toString());
            JSONArray arr = resp.optJSONArray("notifications");
            if (arr == null) arr = resp.optJSONArray("data");
            if (arr == null || arr.length() == 0) return;

            int newCount = 0;
            for (int i = 0; i < arr.length(); i++) {
                JSONObject n = arr.getJSONObject(i);
                String id = String.valueOf(n.optInt("id", 0));
                if (seenIds.contains(id)) continue;
                seenIds.add(id);
                showNotification(
                        n.optString("title", "Fleet Manager"),
                        n.optString("message", n.optString("body", "")),
                        n.optString("link", null),
                        Integer.parseInt(id));
                newCount++;
            }
            if (newCount > 0) {
                prefs.edit().putStringSet(KEY_SEEN_IDS, seenIds).apply();
            }
        } catch (Exception e) {
            consecutiveErrors++;
        }
    }

    private void rescheduleWithInterval(long ms) {
        if (pollTimer != null) pollTimer.cancel();
        pollTimer = new Timer("NotifPoll", true);
        pollTimer.scheduleAtFixedRate(new TimerTask() {
            @Override
            public void run() {
                if (!prefs.getBoolean(KEY_USE_POLLING, false)) { stopSelf(); return; }
                pollServer();
            }
        }, ms, ms);
    }

    private String getSessionCookie() {
        try { return android.webkit.CookieManager.getInstance().getCookie(SERVER_BASE); }
        catch (Exception e) { return null; }
    }

    private void showNotification(String title, String body, String link, int id) {
        NotificationManager mgr = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (mgr == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(
                    NOTIF_CHANNEL_ID, "Fleet Notifications", NotificationManager.IMPORTANCE_HIGH);
            ch.enableVibration(true);
            mgr.createNotificationChannel(ch);
        }
        Intent intent = new Intent(this, MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (link != null) intent.putExtra("notification_link", link);
        PendingIntent pi = PendingIntent.getActivity(this, id, intent,
                PendingIntent.FLAG_ONE_SHOT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder b = new NotificationCompat.Builder(this, NOTIF_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(title)
                .setContentText(body)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setContentIntent(pi);
        if (body != null && body.length() > 50) {
            b.setStyle(new NotificationCompat.BigTextStyle().bigText(body));
        }
        mgr.notify(id, b.build());
    }

    @Override
    public void onDestroy() {
        if (pollTimer != null) { pollTimer.cancel(); pollTimer = null; }
        super.onDestroy();
    }
}
