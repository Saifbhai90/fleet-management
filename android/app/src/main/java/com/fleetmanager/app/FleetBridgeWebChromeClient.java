package com.fleetmanager.app;

import android.util.Log;
import android.webkit.ConsoleMessage;

import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebChromeClient;

/**
 * Capacitor WebChromeClient with Logcat console forwarding.
 * Do not replace with a plain WebChromeClient — that breaks GPS, camera, and file picker.
 */
public class FleetBridgeWebChromeClient extends BridgeWebChromeClient {

    public FleetBridgeWebChromeClient(Bridge bridge) {
        super(bridge);
    }

    @Override
    public boolean onConsoleMessage(ConsoleMessage msg) {
        Log.d("FleetWebConsole", msg.message() + " -- line "
                + msg.lineNumber() + " of " + msg.sourceId());
        return super.onConsoleMessage(msg);
    }
}
