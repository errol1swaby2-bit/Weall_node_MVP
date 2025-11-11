[app]

# (str) Title of your application
title = WeAll Node

# (str) Package name
package.name = weallnode

# (str) Package domain
package.domain = network.weall

# (str) Source code where the main.py lives
source.dir = .

# (list) Files to include
source.include_exts = py,html,js,css,json,yaml

# (list) Directories to exclude (optional)
source.exclude_dirs = tests,bin,venv,__pycache__

# (str) Application version
version = 0.1.0

# (list) Application requirements
# You already use FastAPI (backend) + Kivy (GUI layer) + pywebview for WebView.
requirements = python3,kivy,pywebview,fastapi,uvicorn,pydantic,ipfshttpclient,pyyaml

# (str) Entry point
# This should point to your launcher file that starts uvicorn + webview
# We'll create 'main.py' next to this spec file.
entrypoint = main.py

# (str) Orientation
orientation = portrait

# (bool) Fullscreen mode
fullscreen = 0

# (list) Android permissions
android.permissions = INTERNET,FOREGROUND_SERVICE,WAKE_LOCK

# (list) Android architectures to build
android.archs = arm64-v8a,armeabi-v7a

# (int) Minimum API your APK will support
android.minapi = 21

# (bool) Copy libraries instead of packing them into a .so
android.copy_libs = 1

# (bool) Automatically accept SDK licenses
android.accept_sdk_license = True

# (bool) Enable AndroidX support
android.enable_androidx = True

# (bool) Use --private data storage (default True)
android.private_storage = True

# (str) Logcat filter (useful for debugging)
android.logcat_filters = *:S python:D

# (str) Package format for debug builds
android.debug_artifact = apk

# (bool) Keep the screen awake while running node
android.wakelock = True


[buildozer]

# (int) Log level (0 = errors only, 1 = info, 2 = full debug)
log_level = 2

# (int) Warn if buildozer runs as root (1 = yes)
warn_on_root = 1
