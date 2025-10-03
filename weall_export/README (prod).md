# WeAll Node – Production Prep (v0.3.0)

## Install
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -r "weall_export/requirements (prod).txt"

Env

cp weall_export/.env.example .env
export $(grep -v '^#' .env | xargs)

Run (prod)

cd weall-node
gunicorn -w 4 -k uvicorn.workers.UvicornWorker \
  --timeout 90 --graceful-timeout 30 --keep-alive 30 \
  -b 0.0.0.0:8000 weall_api:app

Observability

/healthz → plain liveness

/ready → JSON readiness, includes GSM flag + peer count

/metrics → Prometheus format (requests, latency, peer count, orphan rate)

Logs → structured access logs to stdout


Genesis Safeguard Mode (GSM)

Config file: weall-node/genesis_params.json

Flags: gsm_active, gsm_expire_by_blocks, gsm_expire_by_days, poh_quorum_threshold, gsm_emergency_extra_jurors

Auto-disables after ~2 weeks or once 10+ Tier-3 jurors exist.


