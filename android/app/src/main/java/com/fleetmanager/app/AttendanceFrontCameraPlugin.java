package com.fleetmanager.app;

import android.app.Activity;
import android.content.Intent;
import android.util.Base64;

import androidx.activity.result.ActivityResult;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileInputStream;

/**
 * Front-only CameraX capture (no rear switch, no gallery).
 */
@CapacitorPlugin(name = "AttendanceFrontCamera")
public class AttendanceFrontCameraPlugin extends Plugin {

    private static final String REQUEST_CAPTURE = "attendanceFrontCapture";

    @PluginMethod
    public void capture(PluginCall call) {
        if (getActivity() == null) {
            call.reject("No activity");
            return;
        }
        Intent intent = new Intent(getActivity(), AttendanceCameraActivity.class);
        String prefix = call.getString("line1Prefix");
        if (prefix != null && !prefix.isEmpty()) {
            intent.putExtra(AttendanceCameraActivity.EXTRA_LINE1_PREFIX, prefix);
        }
        Double lat = call.getDouble("lat");
        Double lng = call.getDouble("lng");
        Double acc = call.getDouble("accuracyMeters");
        if (lat != null && lng != null) {
            intent.putExtra(AttendanceCameraActivity.EXTRA_LAT, lat);
            intent.putExtra(AttendanceCameraActivity.EXTRA_LNG, lng);
        }
        if (acc != null) {
            intent.putExtra(AttendanceCameraActivity.EXTRA_ACCURACY, acc);
        }
        startActivityForResult(call, intent, REQUEST_CAPTURE);
    }

    @ActivityCallback
    private void attendanceFrontCapture(PluginCall call, ActivityResult result) {
        if (call == null) return;
        if (result.getResultCode() == Activity.RESULT_CANCELED) {
            call.reject("User cancelled photos app");
            return;
        }
        if (result.getResultCode() != Activity.RESULT_OK || result.getData() == null) {
            call.reject("Capture failed");
            return;
        }
        String path = result.getData().getStringExtra(AttendanceCameraActivity.EXTRA_PHOTO_PATH);
        if (path == null || path.isEmpty()) {
            call.reject("No photo path");
            return;
        }
        try {
            File file = new File(path);
            byte[] bytes = readFileBytes(file);
            if (!file.delete()) {
                file.deleteOnExit();
            }
            if (bytes == null || bytes.length == 0) {
                call.reject("Empty image");
                return;
            }
            JSObject ret = new JSObject();
            ret.put("base64", Base64.encodeToString(bytes, Base64.NO_WRAP));
            call.resolve(ret);
        } catch (Exception e) {
            call.reject(e.getMessage() != null ? e.getMessage() : "Failed to read image");
        }
    }

    private static byte[] readFileBytes(File file) throws java.io.IOException {
        FileInputStream in = new FileInputStream(file);
        try {
            byte[] data = new byte[(int) file.length()];
            int read = in.read(data);
            if (read <= 0) return new byte[0];
            if (read == data.length) return data;
            byte[] trimmed = new byte[read];
            System.arraycopy(data, 0, trimmed, 0, read);
            return trimmed;
        } finally {
            in.close();
        }
    }
}
