class Settings:
    # --- Crypto settings ---
    POH_CRYPTO_PROVIDER = "fallback"  # "fallback" | "pynacl"
    POH_SESSION_DURATION_SEC = 20 * 60
    POH_MIN_VOTES = 7
    POH_FRAME_AUDIT_RATE = 1  # frames/sec to snapshot into audit log
    POH_MERKLE_FANOUT = 2     # binary merkle; keep it small for Termux

    # --- Juror selection ---
    JUROR_POOL_SIZE = 10
    JUROR_COOLDOWN_EPOCHS = 3
    JUROR_WEIGHTING = {"reputation": 0.6, "stake": 0.4}

    # --- Dispute policy ---
    DISPUTE_WINDOW_SEC = 48 * 3600
    DISPUTE_STAKE = 25.0      # challenger stake (WEC)
    JUROR_SLASH = 10.0        # mis-attesting juror slash (WEC)
    ATTEST_REWARD = 3.0       # honest attestation reward (WEC)

    # --- API / App config ---
    SERVICE_NAME = "weall-node"
    ALLOWED_ORIGINS = "*"                 # CORS
    MAX_UPLOAD_SIZE = 50 * 1024 * 1024    # 50 MB default
    REPLICATION_K = 3                     # IPFS replication factor
    API_KEY = "dev-local-api-key"         # simple dev key

    # --- Rate limiting ---
    RATE_WINDOW = 60        # seconds (default 1 minute window)
    RATE_LIMIT = 100        # max requests per window
    # --- IPFS ---
    IPFS_ADDR = "/ip4/127.0.0.1/tcp/5001"  # default IPFS API endpoint
