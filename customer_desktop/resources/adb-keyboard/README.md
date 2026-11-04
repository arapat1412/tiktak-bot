# Bundled ADBKeyBoard
Official senzhk/ADBKeyBoard release v2.5-dev, with the upstream Android 16 fix.
APK URL: https://github.com/senzhk/ADBKeyBoard/releases/download/v2.5-dev/keyboardservice-debug.apk
The APK is renamed to ADBKeyboard.apk; no binary or source changes.
See provenance.json for verified release SHA-256, LICENSE for GPL-2.0, and source.zip for the tagged corresponding source (including build scripts).
The desktop installer uses exact device serial, installs only when no compatible keyboard exists, enables it and checks Android readback. It does not select the default IME. Existing attempt-scoped keyboard switching/restoration handles typing later.
