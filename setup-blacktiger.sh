#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "    BlackTiger Setup for Ubuntu & Linux"
echo "=================================================="

# Check for Python 3
PYTHON=""
for cmd in python3.11 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PYTHON="$(command -v "$cmd")"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "Error: Python 3 was not found. Please install Python 3:"
    echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi

echo "Using Python: $PYTHON ($($PYTHON --version))"

# Check for Tkinter
if ! "$PYTHON" -c "import tkinter" >/dev/null 2>&1; then
    echo "Notice: python3-tk is not installed. To run the GUI on Ubuntu desktop:"
    echo "  sudo apt install -y python3-tk"
    echo "BlackTiger will still work in CLI / headless mode."
else
    echo "Tkinter is available (GUI supported)."
fi

install_project_requirements() {
    local proj_path="$1"
    local req_file="${2:-requirements.txt}"
    local venv_path="$proj_path/.venv"
    local venv_py="$venv_path/bin/python"
    local req_full="$proj_path/$req_file"

    if [ ! -f "$req_full" ]; then
        return 0
    fi

    echo "--- Setting up $(basename "$proj_path") ---"
    if [ ! -f "$venv_py" ]; then
        echo "Creating virtual environment in $venv_path..."
        "$PYTHON" -m venv "$venv_path" || {
            echo "Failed to create venv. Ensure python3-venv is installed:"
            echo "  sudo apt install -y python3-venv"
            exit 1
        }
    fi

    echo "Installing requirements from $req_full..."
    "$venv_py" -m pip install -r "$req_full"
    echo "Ready: $proj_path"
}

# Setup subproject environments
install_project_requirements "$SCRIPT_DIR/spiderfoot"
install_project_requirements "$SCRIPT_DIR/BlackTiger/network_dashboard"
install_project_requirements "$SCRIPT_DIR/BlackTiger/enterprise_audit"
install_project_requirements "$SCRIPT_DIR/Bramhastra"

echo ""
echo "--- Checking system tools ---"
if command -v nmap >/dev/null 2>&1; then
    echo "[+] Nmap is installed: $(command -v nmap)"
else
    echo "[-] Nmap not found. Optional install: sudo apt install -y nmap"
fi

if command -v john >/dev/null 2>&1; then
    echo "[+] John the Ripper is installed: $(command -v john)"
else
    echo "[-] John not found. Optional install: sudo apt install -y john"
fi

if command -v docker >/dev/null 2>&1; then
    echo "[+] Docker is installed: $(command -v docker)"
else
    echo "[-] Docker not found (needed for osint-analyser container services)"
fi

if command -v earth >/dev/null 2>&1; then
    echo "[+] Earth language compiler is installed: $(command -v earth)"
else
    echo "[-] Earth compiler not found (Bramhastra will use Python engine)"
fi

# Ensure run scripts have executable permissions
chmod +x "$SCRIPT_DIR/run-blacktiger.sh" 2>/dev/null || true

echo ""
echo "=================================================="
echo "BlackTiger setup complete!"
echo "To run BlackTiger on Ubuntu:"
echo "  ./run-blacktiger.sh             (GUI or CLI)"
echo "  python3 blacktiger_app.py --help (CLI help)"
echo "=================================================="
