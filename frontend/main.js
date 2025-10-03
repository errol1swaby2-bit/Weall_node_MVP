@@
-async function encryptAndUpload(fileBlob, userId, content, visibility = "public", groups = []) {
-  // generate AES-GCM key
-  const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]);
-  const rawKey = await crypto.subtle.exportKey("raw", key); // ArrayBuffer
-  const iv = crypto.getRandomValues(new Uint8Array(12));
-
-  const encrypted = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, await fileBlob.arrayBuffer());
-
-  const form = new FormData();
-  form.append("user_id", userId);
-  form.append("content", content);
-  form.append("key_b64", buf2b64(rawKey));
-  form.append("iv_b64", buf2b64(iv));
-  form.append("visibility", visibility);
-  form.append("groups", groups.join(","));
-  // attach encrypted blob (octet-stream)
-  form.append("file", new Blob([new Uint8Array(encrypted)], { type: "application/octet-stream" }), "recording.enc");
-
-  const res = await fetch("/post_with_encrypted_file", { method: "POST", body: form });
-  return await res.json();
-}
// placeholder to call the real E2E encryption flow
async function encryptAndUpload(fileBlob, userId, content, visibility = "private", groups = []) {
  return await encryptWrapAndUpload({ userId, fileBlob, content, visibility, groups });
}
