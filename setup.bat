@echo off
echo ==========================================
echo NSE Market Dashboard - Quick Setup
echo ==========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python is not installed. Please install Python 3.8 or higher.
    pause
    exit /b 1
)

echo ✅ Python found
echo.

REM Create and activate virtual environment
echo 🐍 Setting up virtual environment...
if not exist ".venv" (
    python -m venv .venv
)
call .venv\Scripts\activate
echo ✅ Virtual environment active: .venv
echo.

REM Install dependencies
echo 📦 Installing required packages...
echo.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ❌ Error installing packages. Please check the error messages above.
    pause
    exit /b 1
)

echo.
echo ✅ All packages installed successfully!
echo.

REM Create directories
echo 📁 Creating directories...
if not exist "exports" mkdir exports
if not exist "notes" mkdir notes
echo ✅ Directories created
echo.

echo ==========================================
echo ✅ Setup Complete!
echo ==========================================
echo.
echo To run the dashboard:
echo   .venv\Scripts\activate ^&^& streamlit run app.py
echo.
echo Press any key to launch the dashboard now...
pause >nul

streamlit run app.py
