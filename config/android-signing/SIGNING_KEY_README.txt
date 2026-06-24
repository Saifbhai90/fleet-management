Fleet Manager — Android release signing key
============================================
SAVE THIS FOLDER — do not delete. Required for every future APK build.

Keystore file: fleet-release.jks

  storePassword: FleetMgr2026!
  keyAlias:      fleet-release
  keyPassword:   FleetMgr2026!

Gradle uses: android/keystore.properties (points to this file)

First use: v1.9.6 (May 2026)
Certificate SHA-256: 53a3c9c4f123b2b52ec1f090d084e1f225dd497b25918e895c60ff4bd818e179
Note: Phones with OLD app (1.7 etc.) were signed with a DIFFERENT key.
      Those users must uninstall once, then install 1.9.6+.
      All NEW builds must use THIS keystore so in-app updates work.

Backup: copy this entire "New folder" to USB / cloud (private).

To print certificate fingerprint:
  keytool -list -v -keystore fleet-release.jks -alias fleet-release -storepass FleetMgr2026!
