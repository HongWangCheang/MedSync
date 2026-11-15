#!/usr/bin/env bash
# One command from a fresh clone to a running system:
#
#   scripts/up.sh            # services + end-to-end smoke test
#   scripts/up.sh --model    # also fetch the on-device model (Qwen3-0.6B, 328 MB, checksum verified)
#   scripts/up.sh --app      # also open the desktop app (needs JDK 21)
#
# A missing .env is created with random local passwords; GEMINI_API_KEY stays empty (medication questions then
# answer "药学服务未配置"; everything else works). An existing .env is never touched.
set -euo pipefail
cd "$(dirname "$0")/.."

want_model=false want_app=false
for arg in "$@"; do
  case "$arg" in
    --model) want_model=true ;;
    --app) want_app=true ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if [[ ! -f .env ]]; then
  say "Creating .env with random local passwords"
  rand() { openssl rand -hex 16; }
  sed -e "s/^MYSQL_ROOT_PASSWORD=.*/MYSQL_ROOT_PASSWORD=$(rand)/" \
      -e "s/^MYSQL_PASSWORD=.*/MYSQL_PASSWORD=$(rand)/" \
      -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(rand)/" \
      -e "s/^MEDSYNC_INTERNAL_SECRET=.*/MEDSYNC_INTERNAL_SECRET=$(openssl rand -hex 32)/" \
      .env.example > .env
  echo "Add GEMINI_API_KEY to .env to answer medication questions."
fi

say "Starting services (first build takes a few minutes)"
docker compose up --build -d --wait --wait-timeout 600

say "End-to-end smoke test"
python3 scripts/smoke.py

if $want_model; then
  model="${MEDSYNC_MODEL:-$HOME/.medsync/models/Qwen3-0.6B_dynamic_wi4b32_afp32.litertlm}"
  sha=bf1aba9ce8d963124407353c6aa4cbf72eba78db21ae133de983eac672ce83e0
  if [[ -f "$model" ]] && shasum -a 256 "$model" | grep -q "$sha"; then
    say "On-device model already present: $model"
  else
    say "Fetching the on-device model (Qwen3-0.6B int4, Apache-2.0, 328 MB)"
    mkdir -p "$(dirname "$model")"
    curl -fL --progress-bar -o "$model.part" \
      "https://huggingface.co/litert-community/Qwen3-0.6B/resolve/8d42ab5f1db14cad987fac57aeb17d070f9e180d/Qwen3-0.6B_dynamic_wi4b32_afp32.litertlm"
    shasum -a 256 "$model.part" | grep -q "$sha" || { echo "checksum mismatch, keeping nothing" >&2; rm -f "$model.part"; exit 1; }
    mv "$model.part" "$model"
  fi
fi

if $want_app; then
  say "Opening the desktop app"
  (cd client && ./gradlew :desktopApp:run)
else
  say "Ready"
  echo "Desktop app:  cd client && ./gradlew :desktopApp:run"
  echo "Demo script:  docs/demo.md"
fi
