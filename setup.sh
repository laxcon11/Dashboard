#!/bin/bash

# NSE Market Dashboard - Quick Start Script
# This script will help you set up and run the dashboard

echo "=========================================="
echo "NSE Market Dashboard - Quick Setup"
echo "=========================================="
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null
then
    echo "❌ Python3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

echo "✅ Python3 found: $(python3 --version)"
echo ""

# Check if pip is installed
if ! command -v pip3 &> /dev/null
then
    echo "❌ pip3 is not installed. Please install pip."
    exit 1
fi

echo "✅ pip3 found"
echo ""

# Create and activate virtual environment
echo "🐍 Setting up virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo "✅ Virtual environment active: .venv"
echo ""

# Install dependencies
echo "📦 Installing required packages..."
echo ""
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ All packages installed successfully!"
    echo ""
else
    echo ""
    echo "❌ Error installing packages. Please check the error messages above."
    exit 1
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p exports
mkdir -p notes
echo "✅ Directories created"
echo ""

echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""
echo "To run the dashboard:"
echo "  source .venv/bin/activate && streamlit run app.py"
echo ""
echo "Or use this command:"
read -p "Press Enter to launch the dashboard now, or Ctrl+C to exit..."

streamlit run app.py
