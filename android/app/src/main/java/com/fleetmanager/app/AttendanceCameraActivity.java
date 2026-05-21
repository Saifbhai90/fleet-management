package com.fleetmanager.app;

import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
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

import java.io.File;
import java.util.concurrent.Executor;

/**
 * Full-screen front camera only — no rear switch (GPS attendance selfie).
 */
public class AttendanceCameraActivity extends AppCompatActivity {

    public static final String EXTRA_PHOTO_PATH = "photoPath";

    private PreviewView previewView;
    private ImageCapture imageCapture;
    private ProcessCameraProvider cameraProvider;
    private Executor mainExecutor;
    private boolean capturing;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_attendance_camera);
        previewView = findViewById(R.id.previewView);
        Button btnCapture = findViewById(R.id.btnCapture);
        Button btnCancel = findViewById(R.id.btnCancel);
        mainExecutor = ContextCompat.getMainExecutor(this);

        btnCancel.setOnClickListener(v -> {
            setResult(RESULT_CANCELED);
            finish();
        });

        btnCapture.setOnClickListener(v -> capturePhoto());

        previewView.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE);
        startFrontCamera();
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

    @Override
    protected void onDestroy() {
        if (cameraProvider != null) {
            cameraProvider.unbindAll();
        }
        super.onDestroy();
    }
}
