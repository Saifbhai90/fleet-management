package com.fleetmanager.app;

import android.app.NotificationManager;

/**
 * Attendance reminders occupy a fixed tray slot per kind, so a newer reminder
 * replaces the older one instead of stacking, and the server can clear a stale
 * one once the driver has actually checked in / out.
 */
final class AttendanceReminderNotifications {

    static final String KIND_CHECKIN = "checkin";
    static final String KIND_CHECKOUT = "checkout";

    static final String ACTION_DISMISS = "dismiss_reminder";

    private static final String TITLE_CHECKIN = "Check-in reminder";
    private static final String TITLE_CHECKOUT = "Check-out reminder";

    private static final int ID_CHECKIN = 8801;
    private static final int ID_CHECKOUT = 8802;

    private AttendanceReminderNotifications() {}

    /** Reminder kind from the push payload, falling back to the title. */
    static String kindFor(String reminderKind, String title) {
        if (KIND_CHECKIN.equals(reminderKind) || KIND_CHECKOUT.equals(reminderKind)) {
            return reminderKind;
        }
        if (TITLE_CHECKIN.equals(title)) return KIND_CHECKIN;
        if (TITLE_CHECKOUT.equals(title)) return KIND_CHECKOUT;
        return null;
    }

    static int notificationId(String kind) {
        return KIND_CHECKOUT.equals(kind) ? ID_CHECKOUT : ID_CHECKIN;
    }

    static void cancel(NotificationManager manager, String kind) {
        if (manager == null || kind == null) return;
        manager.cancel(notificationId(kind));
    }

    /**
     * True when the server's validity window has already passed — covers devices
     * that surface a queued data message after its FCM TTL should have expired.
     */
    static boolean isStale(String validUntilEpochSeconds) {
        if (validUntilEpochSeconds == null || validUntilEpochSeconds.trim().isEmpty()) {
            return false;
        }
        try {
            long validUntil = Long.parseLong(validUntilEpochSeconds.trim());
            return System.currentTimeMillis() / 1000L > validUntil;
        } catch (NumberFormatException e) {
            return false;
        }
    }
}
