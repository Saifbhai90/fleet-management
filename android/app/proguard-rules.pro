# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.
#
# For more details, see
#   http://developer.android.com/guide/developing/tools/proguard.html

# If your project uses WebView with JS, uncomment the following
# and specify the fully qualified class name to the JavaScript interface
# class:
#-keepclassmembers class fqcn.of.javascript.interface.for.webview {
#   public *;
#}

# Uncomment this to preserve the line number information for
# debugging stack traces.
-keepattributes SourceFile,LineNumberTable

# If you keep the line number information, uncomment this to
# hide the original source file name.
#-renamesourcefileattribute SourceFile

# ── Google Play Services (GMS) ────────────────────────────────────────────────
# Prevents stripping of GMS proxy classes that handle FCM token negotiation.
# Critical for OPPO/Vivo/Xiaomi where GMS core proxies the registration.
-keep class com.google.android.gms.** { *; }
-dontwarn com.google.android.gms.**

# ── Firebase Core & Messaging ─────────────────────────────────────────────────
-keep class com.google.firebase.** { *; }
-dontwarn com.google.firebase.**

# ── Firebase Installations (FIS) ──────────────────────────────────────────────
# FIS is used as fallback identifier when FCM token generation hangs.
-keep class com.google.firebase.installations.** { *; }

# ── C2DM / GCM Legacy Registration ───────────────────────────────────────────
# Direct registration endpoint relies on these classes not being obfuscated.
-keep class com.google.android.c2dm.** { *; }

# ── Firebase Messaging Service ────────────────────────────────────────────────
-keep class com.google.firebase.messaging.FirebaseMessagingService { *; }
-keep class * extends com.google.firebase.messaging.FirebaseMessagingService { *; }

# ── Capacitor Bridge ─────────────────────────────────────────────────────────
-keep class com.getcapacitor.** { *; }
-dontwarn com.getcapacitor.**

# ── Fleet Manager App Classes ─────────────────────────────────────────────────
-keep class com.fleetmanager.app.** { *; }

# ── Google API Availability ───────────────────────────────────────────────────
-keep class com.google.android.gms.common.GoogleApiAvailability { *; }
-keep class com.google.android.gms.common.ConnectionResult { *; }
-keep class com.google.android.gms.tasks.** { *; }
