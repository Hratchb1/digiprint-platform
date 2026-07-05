@echo off
echo.
echo  ==========================================
echo   digiPrint Platform - Setup ^& Run
echo  ==========================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install from python.org
    pause & exit /b 1
)

:: Check Node
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found. Install from nodejs.org
    pause & exit /b 1
)

:: Check PostgreSQL
psql --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] psql not in PATH. Make sure PostgreSQL is running.
)

echo [1/4] Installing Python dependencies...
cd /d "%~dp0"
pip install -r requirements.txt --quiet

echo [2/4] Setting up .env...
if not exist .env (
    copy .env.example .env
    echo [ACTION REQUIRED] Edit .env and set your DATABASE_URL then re-run this script.
    notepad .env
    pause & exit /b 0
)

echo [3/4] Installing frontend dependencies...
cd frontend
call npm install --silent
cd ..

echo [4/4] Starting servers...
echo.
echo  Backend  : http://localhost:8000
echo  Frontend : http://localhost:3000
echo  API Docs : http://localhost:8000/docs
echo.

:: Start backend in new window
cd backend
start "digiPrint Backend" cmd /k "python -m uvicorn app.main:app --reload --port 8000"
cd ..

:: Wait a moment then start frontend
timeout /t 2 /nobreak >nul
cd frontend
start "digiPrint Frontend" cmd /k "npm run dev"
cd ..

echo Both servers starting. Opening browser...
timeout /t 3 /nobreak >nul
start http://localhost:3000
