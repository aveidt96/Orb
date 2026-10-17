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
ORB_AI_MODEL=gemini-2.5-flash

# Zero-cost SQLite mode on AWS Graviton EC2 (use ORB_ENV=production if using managed Postgres)
ORB_ENV=local
ORB_COMPUTE_ENV=AWS

# OpenCV AI Competition 2026 — Judge Demo Mode
ORB_JUDGE_DEMO_CODE=OPENCV2026
ORB_JUDGE_DAILY_CAP=150
ORB_JUDGE_IP_DAILY_LIMIT=5

# Frontend CORS origin (Vercel production UI)
ORB_PUBLIC_ORIGIN=https://orb-azure-ten.vercel.app

# Optional: Arbitrum Sepolia Web3 credit gate variables
ORB_CREDITS_ENABLED=0
ORB_ARBITRUM_RPC_URL=
ORB_CREDIT_RECEIVER=
ORB_CREDIT_PRICE_WEI=1000000000000
EOF
  echo "Created .env — populate GEMINI_API_KEY in .env before starting in production."
else
  echo "[3/5] Using existing .env file."
fi

echo "[4/5] Building and launching Orb OpenCV 5.0 API container on port 8000..."
sudo docker compose -f docker-compose.aws.yml up -d --build

echo "[5/5] Verifying /api/health endpoint..."
sleep 4
curl -fsS http://127.0.0.1:8000/api/health | python3 -m json.tool

echo ""
echo "=============================================================================="
echo "Orb OpenCV 5.0 API is live on port 8000!"
echo "For automatic HTTPS (required by Vercel's VITE_API_BASE_URL check):"
echo "  sudo apt-get install -y caddy"
echo "  sudo caddy reverse-proxy --from <your-domain-or-nip.io> --to 127.0.0.1:8000"
echo "=============================================================================="
