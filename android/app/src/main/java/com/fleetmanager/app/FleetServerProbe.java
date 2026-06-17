package com.fleetmanager.app;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Lightweight GET /health probe during splash — must finish within splash window. */
public final class FleetServerProbe {

    private static final String TAG = "FleetServerProbe";
    /** Keep within SPLASH_MIN_MS so probe completes before we decide to show the overlay. */
    private static final int PROBE_TIMEOUT_MS = 1100;
    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    public interface Callback {
        void onResult(boolean reachable);
    }

    private FleetServerProbe() {
    }

    public static void probeServerAsync(Context context, String baseUrl, Callback callback) {
        EXECUTOR.execute(() -> {
            boolean ok = probeServerSync(context, baseUrl);
            if (callback != null) {
                MAIN.post(() -> callback.onResult(ok));
            }
        });
    }

    public static String readServerBaseUrl(Context context) {
        try (InputStream in = context.getAssets().open("capacitor.config.json");
             BufferedReader reader = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line);
            }
            JSONObject root = new JSONObject(sb.toString());
            JSONObject server = root.optJSONObject("server");
            if (server != null) {
                String url = server.optString("url", "").trim();
                if (!url.isEmpty()) {
                    return trimTrailingSlashes(url);
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "Could not read capacitor.config.json", e);
        }
        return null;
    }

    public static boolean probeServerSync(Context context, String baseUrl) {
        if (baseUrl == null || baseUrl.isEmpty()) {
            baseUrl = readServerBaseUrl(context);
        }
        if (baseUrl == null || baseUrl.isEmpty()) {
            return false;
        }
        if (!hasDeviceInternet(context)) {
            return false;
        }
        HttpURLConnection conn = null;
        try {
            URL url = new URL(trimTrailingSlashes(baseUrl) + "/health");
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(PROBE_TIMEOUT_MS);
            conn.setReadTimeout(PROBE_TIMEOUT_MS);
            conn.setInstanceFollowRedirects(true);
            conn.setUseCaches(false);
            int code = conn.getResponseCode();
            return code >= 200 && code < 500;
        } catch (Exception e) {
            Log.d(TAG, "Server probe failed: " + e.getMessage());
            return false;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private static boolean hasDeviceInternet(Context context) {
        android.net.ConnectivityManager cm =
                (android.net.ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) {
            return false;
        }
        android.net.Network network = cm.getActiveNetwork();
        if (network == null) {
            return false;
        }
        android.net.NetworkCapabilities caps = cm.getNetworkCapabilities(network);
        return caps != null && caps.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }

    private static String trimTrailingSlashes(String url) {
        if (url == null) {
            return "";
        }
        return url.replaceAll("/+$", "");
    }
}
