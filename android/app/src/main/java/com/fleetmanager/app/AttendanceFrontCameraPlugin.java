package com.fleetmanager.app;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.MediaStore;
import android.util.Base64;

import androidx.activity.result.ActivityResult;
import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileInputStream;

/**
 * Opens the device default camera app (not a custom in-app UI).
 * Requests front camera via Intent extras where OEMs support it — flip may still
 * appear on some phones; full rear lock is not guaranteed with the stock camera app.
 */
@CapacitorPlugin(name = "AttendanceFrontCamera")
public class AttendanceFrontCameraPlugin extends Plugin {

    private static final String REQUEST_CAPTURE = "attendanceDefaultCapture";
    private File outputPhotoFile;

    @PluginMethod
    public void capture(PluginCall call) {
        if (getActivity() == null) {
            call.reject("No activity");
            return;
        }
        Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
        if (intent.resolveActivity(getContext().getPackageManager()) == null) {
            call.reject("No camera app installed");
            return;
        }

        try {
            outputPhotoFile = new File(
                    getContext().getCacheDir(),
                    "attendance_oem_" + System.currentTimeMillis() + ".jpg");
            Uri photoUri = FileProvider.getUriForFile(
                    getContext(),
                    getContext().getPackageName() + ".fileprovider",
                    outputPhotoFile);

            intent.putExtra(MediaStore.EXTRA_OUTPUT, photoUri);
            intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);

            // Best-effort front camera hints (device / OEM dependent)
            intent.putExtra("android.intent.extras.CAMERA_FACING", 1);
            intent.putExtra("android.intent.extra.USE_FRONT_CAMERA", true);
            intent.putExtra("android.intent.extra.LENS_FACING_FRONT", 1);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP_MR1) {
                intent.putExtra("android.intent.extras.LENS_FACING_FRONT", 1);
            }

            startActivityForResult(call, intent, REQUEST_CAPTURE);
        } catch (Exception e) {
            outputPhotoFile = null;
            call.reject(e.getMessage() != null ? e.getMessage() : "Could not start camera");
        }
    }

    @ActivityCallback
    private void attendanceDefaultCapture(PluginCall call, ActivityResult result) {
        if (call == null) return;
        if (result.getResultCode() == Activity.RESULT_CANCELED) {
            cleanupOutputFile();
            call.reject("User cancelled photos app");
            return;
        }
        if (outputPhotoFile == null || !outputPhotoFile.exists() || outputPhotoFile.length() == 0) {
            cleanupOutputFile();
            call.reject("Capture failed");
            return;
        }
        try {
            byte[] bytes = readFileBytes(outputPhotoFile);
            cleanupOutputFile();
            if (bytes.length == 0) {
                call.reject("Empty image");
                return;
            }
            JSObject ret = new JSObject();
            ret.put("base64", Base64.encodeToString(bytes, Base64.NO_WRAP));
            call.resolve(ret);
        } catch (Exception e) {
            cleanupOutputFile();
            call.reject(e.getMessage() != null ? e.getMessage() : "Failed to read image");
        }
    }

    private void cleanupOutputFile() {
        if (outputPhotoFile != null && outputPhotoFile.exists() && !outputPhotoFile.delete()) {
            outputPhotoFile.deleteOnExit();
        }
        outputPhotoFile = null;
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
