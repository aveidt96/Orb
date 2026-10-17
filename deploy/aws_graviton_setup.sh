#!/usr/bin/env bash
# ==============================================================================
# Orb — AWS Graviton2 (t4g.small, Ubuntu 24.04 LTS arm64) Zero-Cost Setup Script
# OpenCV AI Competition 2026 (Powered by AWS)
# ==============================================================================
set -euo pipefail

echo "[1/5] Updating apt packages and installing Docker + Compose plugin..."
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker "${USER}" || true

echo "[2/5] Verifying host architecture (expected: aarch64 / AWS Graviton)..."
uname -m

if [ ! -f .env ]; then
  echo "[3/5] Creating template .env file..."
  cat <<'EOF' > .env
# Required: Gemini VLM API key
GEMINI_API_KEY=replace_with_your_gemini_api_key
ORB_AI_PROVIDER=gemini
ORB_AI_MODEL=gemini-flash-lite-latest

# Zero-cost SQLite mode on AWS Graviton EC2 (use ORB_ENV=production if using managed Postgres)
ORB_ENV=local
ORB_COMPUTE_ENV=AWS

# OpenCV AI Competition 2026 — Judge Demo Mode
ORB_JUDGE_DEMO_CODE=OPENCV2026
ORB_JUDGE_DAILY_CAP=150
ORB_JUDGE_IP_DAILY_LIMIT=25

# Frontend CORS origin (Vercel production UI)
ORB_PUBLIC_ORIGIN=https://orb-azure-ten.vercel.app

# Arbitrum Sepolia Web3 credit gate variables
ORB_CREDITS_ENABLED=1
ORB_ARBITRUM_RPC_URL=https://sepolia-rollup.arbitrum.io/rpc
ORB_CREDIT_RECEIVER=0xc855D21175D81C852E657169424FA974171394F1
ORB_TREASURY_ADDRESS=0xc855D21175D81C852E657169424FA974171394F1
ORB_CREDIT_PRICE_WEI=1000000000000
EOF
  echo "Created .env — populate GEMINI_API_KEY in .env before starting in production."
else
  echo "[3/5] Using existing .env file."
fi

echo "[4/5] Building and launching Orb OpenCV 5.0 API + Cloudflared HTTPS Tunnel..."
sudo docker compose -f docker-compose.aws.yml up -d --build

echo "[5/5] Verifying /api/health endpoint and fetching HTTPS tunnel URL..."
sleep 5
curl -fsS http://127.0.0.1:8000/api/health | python3 -m json.tool

TUNNEL_URL=""
for _ in $(seq 1 15); do
  TUNNEL_URL=$(sudo docker logs orb-cloudflared-tunnel 2>&1 | grep -oE 'https://[-a-zA-Z0-9]+\.trycloudflare\.com' | tail -n 1 || true)
  if [ -n "${TUNNEL_URL}" ]; then
    break
  fi
  sleep 2
done

echo ""
echo "=============================================================================="
echo "Orb OpenCV 5.0 API is live on AWS Graviton (port 8000)!"
if [ -n "${TUNNEL_URL}" ]; then
  echo ""
  echo "  HTTPS Tunnel URL (Copy-paste into Vercel VITE_API_BASE_URL):"
  echo "  >>> ${TUNNEL_URL} <<<"
  echo ""
  echo "  Test Health via HTTPS: ${TUNNEL_URL}/api/health"
else
  echo "  Cloudflared tunnel is still initializing. Run:"
  echo "  sudo docker logs orb-cloudflared-tunnel 2>&1 | grep -oE 'https://[-a-zA-Z0-9]+\\.trycloudflare\\.com'"
fi
echo "=============================================================================="
