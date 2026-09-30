@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Python virtual environment not found. See README.md setup steps.
  pause
  exit /b 1
)

if not exist frontend\node_modules (
  echo Installing frontend dependencies...
  pushd frontend
  call npm install
  popd
)

start "Synapse RAG API" cmd /k ".venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000"
start "Synapse RAG Web" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:3000
echo Synapse RAG is starting at http://127.0.0.1:3000
pause
