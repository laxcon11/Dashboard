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

REM Install dependencies
echo 📦 Installing required packages...
echo.
pip install -r requirements.txt

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
echo   streamlit run nse_dashboard.py
echo.
echo Press any key to launch the dashboard now...
pause >nul

streamlit run nse_dashboard.py
