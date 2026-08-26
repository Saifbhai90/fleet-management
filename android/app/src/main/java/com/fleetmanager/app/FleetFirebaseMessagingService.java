package com.fleetmanager.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.core.app.NotificationCompat;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

public class FleetFirebaseMessagingService extends FirebaseMessagingService {

    private static final String PREFS_NAME = "fcm_prefs";
    private static final String KEY_FCM_TOKEN = "fcm_token";
    private static final String KEY_USE_POLLING = "use_polling";
    private static final String CHANNEL_ID = "fleet_attendance";
    private static final String CHANNEL_NAME = "Fleet Notifications";

    @Override
    public void onNewToken(String token) {
        super.onNewToken(token);

        SharedPreferences prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        prefs.edit()
                .putString(KEY_FCM_TOKEN, token)
                .putBoolean(KEY_USE_POLLING, false)
                .apply();

        try {
            Intent stopPolling = new Intent(this, NotificationPollingService.class);
            stopService(stopPolling);
        } catch (Exception ignored) {}
    }

    @Override
    public void onMessageReceived(RemoteMessage message) {
        super.onMessageReceived(message);

        java.util.Map<String, String> data = message.getData();

        if (AttendanceReminderNotifications.ACTION_DISMISS.equals(data.get("fleet_action"))) {
            AttendanceReminderNotifications.cancel(
                    (NotificationManager) getSystemService(NOTIFICATION_SERVICE),
                    AttendanceReminderNotifications.kindFor(data.get("reminder_kind"), null));
            return;
        }

        String title = "Fleet Manager";
        String body = "";
        String link = null;

        if (message.getNotification() != null) {
            title = message.getNotification().getTitle() != null
                    ? message.getNotification().getTitle() : title;
            body = message.getNotification().getBody() != null
                    ? message.getNotification().getBody() : "";
        }

        if (data.containsKey("title")) {
            title = data.get("title");
        }
        if (data.containsKey("body")) {
            body = data.get("body");
        }
        if (data.containsKey("link")) {
            link = data.get("link");
        }

        String reminderKind = AttendanceReminderNotifications.kindFor(data.get("reminder_kind"), title);
        if (reminderKind != null && AttendanceReminderNotifications.isStale(data.get("valid_until"))) {
            AttendanceReminderNotifications.cancel(
                    (NotificationManager) getSystemService(NOTIFICATION_SERVICE), reminderKind);
            return;
        }

        showNotification(title, body, link, data);
    }

    private void showNotification(String title, String body, String link, java.util.Map<String, String> data) {
        NotificationManager manager =
                (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager == null) return;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription("Fleet management alerts and attendance notifications");
            channel.enableVibration(true);
            manager.createNotificationChannel(channel);
        }

        boolean saveEnabled = data != null && "1".equals(data.get("save_enabled"));
        String popupSource = data != null && data.get("popup_source") != null
                ? data.get("popup_source") : "generic";
        String createdAt = data != null && data.get("created_at") != null
                ? data.get("created_at") : "";

        String reminderKind = AttendanceReminderNotifications.kindFor(
                data != null ? data.get("reminder_kind") : null, title);
        int notificationId = reminderKind != null
                ? AttendanceReminderNotifications.notificationId(reminderKind)
                : (int) System.currentTimeMillis();

        Intent intent = (link != null && !link.trim().isEmpty())
                ? NotificationPopupActivity.createIntent(
                        this, link, title, body, saveEnabled, popupSource, createdAt)
                : new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);

        PendingIntent pendingIntent = PendingIntent.getActivity(this, notificationId, intent,
                PendingIntent.FLAG_ONE_SHOT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(title)
                .setContentText(body)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setContentIntent(pendingIntent);

        if (body.length() > 50) {
            builder.setStyle(new NotificationCompat.BigTextStyle().bigText(body));
        }

        manager.notify(notificationId, builder.build());
    }
}
