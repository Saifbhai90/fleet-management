package com.fleetmanager.app;

import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import androidx.exifinterface.media.ExifInterface;

import java.io.File;
import java.io.FileOutputStream;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.Executor;

/**
 * Front camera only (CameraX). No rear switch, no gallery.
 */
public class AttendanceCameraActivity extends AppCompatActivity {

    public static final String EXTRA_PHOTO_PATH = "photoPath";
    public static final String EXTRA_LINE1_PREFIX = "line1Prefix";
    public static final String EXTRA_LAT = "lat";
    public static final String EXTRA_LNG = "lng";
    public static final String EXTRA_ACCURACY = "accuracyMeters";

    private PreviewView previewView;
    private ImageCapture imageCapture;
    private ProcessCameraProvider cameraProvider;
    private Executor mainExecutor;
    private boolean capturing;

    private TextView gpsStampLine1;
    private TextView gpsStampLine2;
    private TextView gpsStampLine3;
    private TextView gpsStampLine4;
    private final Handler stampHandler = new Handler(Looper.getMainLooper());
    private String line1Prefix = "GPS+Cam";
    private Double stampLat;
    private Double stampLng;
    private Double stampAccuracy;

    private final Runnable stampTicker = new Runnable() {
        @Override
        public void run() {
            refreshGpsStampOverlay();
            stampHandler.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_attendance_camera);
        previewView = findViewById(R.id.previewView);
        gpsStampLine1 = findViewById(R.id.gpsStampLine1);
        gpsStampLine2 = findViewById(R.id.gpsStampLine2);
        gpsStampLine3 = findViewById(R.id.gpsStampLine3);
        gpsStampLine4 = findViewById(R.id.gpsStampLine4);
        Button btnCapture = findViewById(R.id.btnCapture);
        Button btnCancel = findViewById(R.id.btnCancel);
        mainExecutor = ContextCompat.getMainExecutor(this);

        readStampExtras(getIntent());

        btnCancel.setOnClickListener(v -> {
            setResult(RESULT_CANCELED);
            finish();
        });

        btnCapture.setOnClickListener(v -> capturePhoto());

        previewView.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE);
        startFrontCamera();
        stampHandler.post(stampTicker);
    }

    private void readStampExtras(Intent intent) {
        if (intent == null) return;
        String prefix = intent.getStringExtra(EXTRA_LINE1_PREFIX);
        if (prefix != null && !prefix.isEmpty()) line1Prefix = prefix;
        if (intent.hasExtra(EXTRA_LAT)) stampLat = intent.getDoubleExtra(EXTRA_LAT, 0);
        if (intent.hasExtra(EXTRA_LNG)) stampLng = intent.getDoubleExtra(EXTRA_LNG, 0);
        if (intent.hasExtra(EXTRA_ACCURACY)) stampAccuracy = intent.getDoubleExtra(EXTRA_ACCURACY, 0);
    }

    private void refreshGpsStampOverlay() {
        SimpleDateFormat df = new SimpleDateFormat("dd-MM-yyyy EEE", Locale.getDefault());
        SimpleDateFormat tf = new SimpleDateFormat("hh:mm:ss a", Locale.getDefault());
        Date now = new Date();
        gpsStampLine1.setText(line1Prefix);
        gpsStampLine2.setText(df.format(now) + "  " + tf.format(now));
        if (stampLat != null && stampLng != null && !stampLat.isNaN() && !stampLng.isNaN()) {
            gpsStampLine3.setText(String.format(Locale.US,
                    "Lat %.6f°   Long %.6f°", stampLat, stampLng));
            gpsStampLine3.setVisibility(View.VISIBLE);
        } else {
            gpsStampLine3.setVisibility(View.GONE);
        }
        if (stampAccuracy != null && !stampAccuracy.isNaN() && Double.isFinite(stampAccuracy)) {
            gpsStampLine4.setText("Accuracy: ~" + Math.round(stampAccuracy) + " m");
            gpsStampLine4.setVisibility(View.VISIBLE);
        } else {
            gpsStampLine4.setVisibility(View.GONE);
        }
    }

    private void startFrontCamera() {
        ProcessCameraProvider.getInstance(this).addListener(() -> {
            try {
                cameraProvider = ProcessCameraProvider.getInstance(this).get();
                cameraProvider.unbindAll();

                Preview preview = new Preview.Builder().build();
                preview.setSurfaceProvider(previewView.getSurfaceProvider());

                imageCapture = new ImageCapture.Builder()
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
                        .setTargetRotation(getWindowManager().getDefaultDisplay().getRotation())
                        .build();

                CameraSelector selector = new CameraSelector.Builder()
                        .requireLensFacing(CameraSelector.LENS_FACING_FRONT)
                        .build();

                cameraProvider.bindToLifecycle(this, selector, preview, imageCapture);
            } catch (Exception e) {
                Toast.makeText(this, "Camera failed: " + e.getMessage(), Toast.LENGTH_LONG).show();
                setResult(RESULT_CANCELED);
                finish();
            }
        }, mainExecutor);
    }

    private void capturePhoto() {
        if (imageCapture == null || capturing) return;
        capturing = true;
        findViewById(R.id.btnCapture).setEnabled(false);

        File photoFile = new File(getCacheDir(), "attendance_front_" + System.currentTimeMillis() + ".jpg");
        ImageCapture.OutputFileOptions options =
                new ImageCapture.OutputFileOptions.Builder(photoFile).build();

        imageCapture.takePicture(options, mainExecutor, new ImageCapture.OnImageSavedCallback() {
            @Override
            public void onImageSaved(@NonNull ImageCapture.OutputFileResults outputFileResults) {
                fixImageOrientation(photoFile);
                if (cameraProvider != null) {
                    cameraProvider.unbindAll();
                }
                Intent data = new Intent();
                data.putExtra(EXTRA_PHOTO_PATH, photoFile.getAbsolutePath());
                setResult(RESULT_OK, data);
                finish();
            }

            @Override
            public void onError(@NonNull ImageCaptureException exception) {
                capturing = false;
                findViewById(R.id.btnCapture).setEnabled(true);
                Toast.makeText(
                        AttendanceCameraActivity.this,
                        "Capture failed",
                        Toast.LENGTH_SHORT).show();
            }
        });
    }

    private void fixImageOrientation(File file) {
        try {
            ExifInterface exif = new ExifInterface(file.getAbsolutePath());
            int orientation = exif.getAttributeInt(
                    ExifInterface.TAG_ORIENTATION,
                    ExifInterface.ORIENTATION_NORMAL);
            int rotation = 0;
            if (orientation == ExifInterface.ORIENTATION_ROTATE_90) {
                rotation = 90;
            } else if (orientation == ExifInterface.ORIENTATION_ROTATE_180) {
                rotation = 180;
            } else if (orientation == ExifInterface.ORIENTATION_ROTATE_270) {
                rotation = 270;
            }
            if (rotation == 0) {
                return;
            }
            Bitmap bmp = BitmapFactory.decodeFile(file.getAbsolutePath());
            if (bmp == null) {
                return;
            }
            Matrix matrix = new Matrix();
            matrix.postRotate(rotation);
            Bitmap rotated = Bitmap.createBitmap(bmp, 0, 0, bmp.getWidth(), bmp.getHeight(), matrix, true);
            bmp.recycle();
            try (FileOutputStream out = new FileOutputStream(file)) {
                rotated.compress(Bitmap.CompressFormat.JPEG, 95, out);
            }
            rotated.recycle();
            ExifInterface outExif = new ExifInterface(file.getAbsolutePath());
            outExif.setAttribute(
                    ExifInterface.TAG_ORIENTATION,
                    String.valueOf(ExifInterface.ORIENTATION_NORMAL));
            outExif.saveAttributes();
        } catch (Exception ignored) {
            // keep original file
        }
    }

    @Override
    protected void onDestroy() {
        stampHandler.removeCallbacks(stampTicker);
        if (cameraProvider != null) {
            cameraProvider.unbindAll();
        }
        super.onDestroy();
    }
}
