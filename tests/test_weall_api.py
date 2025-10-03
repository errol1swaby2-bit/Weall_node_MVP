#!/usr/bin/env python3
"""
Termux-friendly test script for patched WeAll API.
- Registers a test user
- Uploads a small file
- Retrieves it from IPFS
"""

import requests
import json
import base64
import os

API_URL = "http://127.0.0.1:8000"
API_KEY = "dev-local-api-key"

headers = {
    "X-API-KEY": API_KEY,
    "Content-Type": "application/json"
}

# ------------------------------
# 1. Register test user
# ------------------------------
user_id = "alice"
pubkey_pem = "TESTKEY"

print(f"Registering user '{user_id}'...")
resp = requests.post(f"{API_URL}/register_pubkey",
                     headers=headers,
                     data=json.dumps({"user_id": user_id, "pubkey_pem": pubkey_pem}))

print("Response:", resp.status_code, resp.json())

# ------------------------------
# 2. Upload a small encrypted file
# ------------------------------
print("\nUploading a small test file...")

# Create a small dummy file
dummy_filename = "test_file.txt"
with open(dummy_filename, "w") as f:
    f.write("Hello WeAll patch test!")

# Prepare multipart form data
files = {
    "file": (dummy_filename, open(dummy_filename, "rb"), "application/octet-stream")
}
data = {
    "user_id": user_id,
    "content": "Test post content",
    "iv_b64": base64.b64encode(b"dummyiv1234567").decode(),
    "wrapped_keys": json.dumps([]),
    "visibility": "private"
}

resp = requests.post(f"{API_URL}/post_encrypted_e2e",
                     headers={"X-API-KEY": API_KEY},
                     data=data,
                     files=files)

# Clean up dummy file
os.remove(dummy_filename)

print("Upload response:", resp.status_code, resp.json())

if resp.status_code == 200:
    post_info = resp.json()
    cid = post_info.get("cid")
    if cid:
        # ------------------------------
        # 3. Retrieve file via /ipfs_raw
        # ------------------------------
        print(f"\nFetching file from IPFS (CID: {cid})...")
        r = requests.get(f"{API_URL}/ipfs_raw/{cid}", stream=True)
        if r.status_code == 200:
            fetched_file = f"fetched_{dummy_filename}"
            with open(fetched_file, "wb") as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            print(f"File fetched and saved as {fetched_file}")
        else:
            print("Failed to fetch file from IPFS:", r.status_code, r.text)
else:
    print("File upload failed, skipping IPFS fetch.")
