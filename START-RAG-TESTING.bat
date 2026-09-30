@echo off
setlocal
cd /d "%~dp0"
title Synapse RAG Testing Launcher

echo [1/4] Checking Docker...
docker info >nul 2>&1
if errorlevel 1 (
  echo Starting Docker Desktop...
  start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
  echo Wait until Docker Desktop says Engine running, then run this file again.
  pause
  exit /b 1
)

echo [2/4] Starting n8n...
docker compose -f docker-compose.n8n.yml up -d

echo [3/4] Starting Synapse RAG API and web if needed...
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if errorlevel 1 start "Synapse RAG API - keep open" cmd /k "cd /d %~dp0 && .venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000"

netstat -ano | findstr /R /C:":3000 .*LISTENING" >nul
if errorlevel 1 start "Synapse RAG Web - keep open" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 3 /nobreak >nul

echo [4/4] Starting Cloudflare Quick Tunnel...
tasklist | findstr /I "cloudflared.exe" >nul
if errorlevel 1 start "Cloudflare Tunnel - copy public URL from here" cmd /k "cloudflared tunnel --url http://127.0.0.1:3000 --no-autoupdate"

start "" http://127.0.0.1:3000
start "" http://127.0.0.1:5678

echo.
echo Synapse RAG local: http://127.0.0.1:3000
echo API local: http://127.0.0.1:8000
echo n8n local: http://127.0.0.1:5678
echo Public URL appears in the Cloudflare Tunnel window.
echo Administrator mode is NOT required.
pause
