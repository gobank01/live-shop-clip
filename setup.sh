#!/usr/bin/env bash
# ตัวติดตั้งสำหรับ Mac (และ Linux) — รันครั้งเดียว:  bash setup.sh
set -e
cd "$(dirname "$0")"
HEADLESS="chrome-headless-shell@151.0.7922.47"   # รุ่นที่ทดสอบแล้วว่าเรนเดอร์ผ่าน

say() { printf "\n\033[1;36m▶ %s\033[0m\n" "$1"; }

if [ "$(uname -s)" = "Darwin" ]; then
  if ! command -v brew >/dev/null; then
    say "ติดตั้ง Homebrew (ระบบจะถามรหัสผ่านเครื่อง Mac)"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
  fi
  for pkg in ffmpeg node python; do
    say "เช็ก/ติดตั้ง $pkg"
    brew list "$pkg" >/dev/null 2>&1 || brew install "$pkg"
  done
else
  say "ติดตั้ง ffmpeg / Node.js / Python (Linux)"
  sudo apt-get update && sudo apt-get install -y ffmpeg python3 python3-venv curl
  command -v node >/dev/null || { curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt-get install -y nodejs; }
fi

say "สร้าง Python ของโปรเจกต์ + ติดตั้งตัวตัดคำภาษาไทย (pythainlp)"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet pythainlp

say "ติดตั้งเครื่องมือทำวิดีโอ (HyperFrames)"
npm install --no-fund --no-audit

say "ติดตั้งเบราว์เซอร์สำหรับเรนเดอร์"
npx --yes @puppeteer/browsers install "$HEADLESS" --path "$PWD/.browsers"

if [ ! -f .env ]; then
  cp .env.example .env
  if [ -t 0 ]; then
    printf "\nวางคีย์ ElevenLabs (ได้จาก https://elevenlabs.io/app/settings/api-keys) แล้วกด Enter\n(ข้ามได้ ใส่ทีหลังในไฟล์ .env): "
    read -r KEY
    KEY="$(echo "$KEY" | tr -d '[:space:]')"
    [ -n "$KEY" ] && sed -i.bak "s|^ELEVENLABS_API_KEY=.*|ELEVENLABS_API_KEY=$KEY|" .env && rm -f .env.bak
  fi
fi

say "ตรวจความพร้อม"
.venv/bin/python make.py check || true
