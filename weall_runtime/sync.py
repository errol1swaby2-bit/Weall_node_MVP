# weall_runtime/sync.py
import requests
import time
import json
import base64
from cryptography.fernet import Fernet
from weall_runtime.storage import IPFSClient

class Node:
    def __init__(self, ledger, peers=None):
        self.ledger = ledger
        self.peers = peers or []
        self.ipfs = IPFSClient()
        self.key = Fernet.generate_key()
        self.fernet = Fernet(self.key)

    def register_peer(self, url):
        if url not in self.peers:
            self.peers.append(url)

    def broadcast_snapshot(self):
        snapshot = self.ledger.snapshot()
        for peer in self.peers:
            try:
                requests.post(f"{peer}/sync/push", json=snapshot, timeout=2)
            except Exception as e:
                print(f"[sync] failed to push to {peer}: {e}")

    def fetch_from_peers(self):
        for peer in self.peers:
            try:
                resp = requests.get(f"{peer}/sync/snapshot", timeout=2)
                if resp.ok:
                    remote = resp.json()
                    # TODO: merge strategy (CRDT / last-write-wins)
                    print(f"[sync] received snapshot from {peer}")
            except Exception as e:
                print(f"[sync] failed to fetch from {peer}: {e}")

    def encrypt_and_store(self, content: str):
        token = self.fernet.encrypt(content.encode())
        return self.ipfs.add_bytes(token)

    def retrieve_and_decrypt(self, cid: str):
        data = self.ipfs.cat(cid)
        return self.fernet.decrypt(data).decode()

    def sync_loop(self, interval=10):
        while True:
            self.broadcast_snapshot()
            self.fetch_from_peers()
            time.sleep(interval)
