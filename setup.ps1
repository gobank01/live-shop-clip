# ตัวติดตั้งสำหรับ Windows — ดับเบิลคลิก 1-ติดตั้ง.bat (หรือรัน: powershell -ExecutionPolicy Bypass -File setup.ps1)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Headless = "chrome-headless-shell@151.0.7922.47"   # รุ่นที่ทดสอบแล้วว่าเรนเดอร์ผ่าน

function Say($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  Write-Host "ไม่พบ winget — ติดตั้ง 'App Installer' จาก Microsoft Store ก่อน แล้วรันไฟล์นี้ใหม่" -ForegroundColor Red
  exit 1
}

foreach ($p in @(@("ffmpeg", "Gyan.FFmpeg"), @("node", "OpenJS.NodeJS.LTS"), @("python", "Python.Python.3.12"))) {
  Say "เช็ก/ติดตั้ง $($p[0])  (ถ้ามีหน้าต่างขออนุญาต ให้กด Yes)"
  if (-not (Get-Command $p[0] -ErrorAction SilentlyContinue)) {
    winget install --id $p[1] -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
  }
}

Say "สร้าง Python ของโปรเจกต์ + ติดตั้งตัวตัดคำภาษาไทย (pythainlp)"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.\.venv\Scripts\python.exe -m pip install --quiet pythainlp

Say "ติดตั้งเครื่องมือทำวิดีโอ (HyperFrames)"
npm install --no-fund --no-audit

Say "ติดตั้งเบราว์เซอร์สำหรับเรนเดอร์"
npx --yes @puppeteer/browsers install $Headless --path "$PWD\.browsers"

if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
  $key = Read-Host "`nวางคีย์ ElevenLabs (ได้จาก https://elevenlabs.io/app/settings/api-keys) แล้วกด Enter (ข้ามได้)"
  $key = $key.Trim()
  if ($key) { (Get-Content .env) -replace '^ELEVENLABS_API_KEY=.*', "ELEVENLABS_API_KEY=$key" | Set-Content .env -Encoding UTF8 }
}

Say "ตรวจความพร้อม"
.\.venv\Scripts\python.exe make.py check
