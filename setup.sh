#!/bin/bash
# Setup script for Nemesis dark web crawler

set -e

DISTRO=$(lsb_release -is 2>/dev/null || echo "Unknown")

echo "Detected Linux Distribution: $DISTRO"

INSTALL_DIR="$HOME/nemesis"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="/usr/local/bin"
NEMESIS_SCRIPT="$INSTALL_DIR/nemesis.py"

cat << 'EOF'
     _   __________  ______________ _________
   / | / / ____/  |/  / ____/ ___//  _/ ___/
  /  |/ / __/ / /|_/ / __/  \__ \ / / \__ \
 / /|  / /___/ /  / / /___ ___/ // / ___/ /
/_/ |_/_____/_/  /_/_____//____/___//____/
EOF

echo "Installing Nemesis dark web crawler..."

# ---- DEPENDENCIES ----
if [[ "$DISTRO" == "Kali" ]]; then
    echo "Installing packages for Kali Linux..."
    sudo apt-get update
    sudo apt-get install -y tor mongodb python3 python3-pip python3-venv

elif [[ "$DISTRO" == "Ubuntu" ]]; then
    echo "Installing packages for Ubuntu..."
    sudo apt-get update
    sudo apt-get install -y tor python3 python3-pip python3-venv curl gnupg lsb-release ca-certificates

    echo "Installing MongoDB (Ubuntu)..."
    # Add MongoDB 7.0 official repo
    curl -fsSL https://pgp.mongodb.com/server-7.0.asc | sudo gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg

    echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu $(lsb_release -cs)/mongodb-org/7.0 multiverse" | \
        sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

    sudo apt-get update
    sudo apt-get install -y mongodb-org

    # Prevent MongoDB auto upgrade
    echo -e "mongodb-org hold\nmongodb-org-database hold\nmongodb-org-server hold\nmongodb-mongosh hold" | sudo dpkg --set-selections
else
    echo "Unsupported distribution: $DISTRO"
    exit 1
fi

# ---- START SERVICES ----
echo "Enabling services..."
sudo systemctl enable tor
sudo systemctl start tor

if [[ "$DISTRO" == "Kali" ]]; then
    sudo systemctl enable mongodb
    sudo systemctl start mongodb
elif [[ "$DISTRO" == "Ubuntu" ]]; then
    sudo systemctl enable mongod
    sudo systemctl start mongod
fi

# ---- INSTALL APP ----
echo "Creating install directory..."
mkdir -p "$INSTALL_DIR"

echo "Copying nemesis.py..."
cp nemesis.py "$NEMESIS_SCRIPT"

echo "Setting up virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Creating /usr/local/bin/nemesis command..."
cat << 'EOF' | sudo tee "$BIN_DIR/nemesis" > /dev/null
#!/bin/bash
NEMESIS_DIR="$HOME/nemesis"

if [ ! -f "$NEMESIS_DIR/nemesis.py" ]; then
    echo "Nemesis script not found in $NEMESIS_DIR"
    exit 1
fi

source "$NEMESIS_DIR/venv/bin/activate"
python "$NEMESIS_DIR/nemesis.py" "$@"
EOF

sudo chmod +x "$BIN_DIR/nemesis"
chmod +x "$NEMESIS_SCRIPT"
deactivate

echo ""
echo "✅ Installation complete!"
echo "You can now run: nemesis -h"
echo "Check services with:"
if [[ "$DISTRO" == "Ubuntu" ]]; then
    echo "  sudo systemctl status mongod"
else
    echo "  sudo systemctl status mongodb"
fi
