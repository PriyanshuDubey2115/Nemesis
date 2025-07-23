#!/bin/bash
# Setup script for Nemesis dark web crawler

# Exit on error
set -e

# Detect OS
DISTRO=$(lsb_release -is 2>/dev/null || echo "Unknown")

echo "Detected Linux Distribution: $DISTRO"

# Define installation directory
INSTALL_DIR="$HOME/nemesis"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="/usr/local/bin"
NEMESIS_SCRIPT="$INSTALL_DIR/nemesis.py"

# Display ASCII banner
cat << 'EOF'
     _   __________  ______________ _________
   / | / / ____/  |/  / ____/ ___//  _/ ___/
  /  |/ / __/ / /|_/ / __/  \__ \ / / \__ \
 / /|  / /___/ /  / / /___ ___/ // / ___/ /
/_/ |_/_____/_/  /_/_____//____/___//____/
EOF

echo "Installing Nemesis dark web crawler..."

# Install dependencies based on distribution
if [[ "$DISTRO" == "Kali" ]]; then
    echo "Installing dependencies for Kali Linux..."
    sudo apt-get update
    sudo apt-get install -y tor mongodb python3 python3-pip python3-venv

elif [[ "$DISTRO" == "Ubuntu" ]]; then
    echo "Installing dependencies for Ubuntu..."
    sudo apt-get update
    sudo apt-get install -y tor python3 python3-pip python3-venv curl gnupg lsb-release ca-certificates wget

    # Install MongoDB 7.0
    echo "Installing MongoDB 7.0 for Ubuntu..."

    # Step 1: Import the MongoDB public GPG key
    curl -fsSL https://pgp.mongodb.com/server-7.0.asc | \
      sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor

    # Step 2: Add the MongoDB repository
    echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu $(lsb_release -cs)/mongodb-org/7.0 multiverse" | \
      sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

    # Step 3: Update the package list
    sudo apt-get update

    # Step 4: Install MongoDB
    sudo apt-get install -y mongodb-org
fi

# Step 5: Start and enable services
echo "Starting Tor and MongoDB services..."
sudo systemctl start tor
sudo systemctl enable tor

if [[ "$DISTRO" == "Kali" ]]; then
    sudo systemctl start mongodb
    sudo systemctl enable mongodb
elif [[ "$DISTRO" == "Ubuntu" ]]; then
    sudo systemctl start mongod
    sudo systemctl enable mongod
fi

# Create installation directory
echo "Creating installation directory at $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Copy nemesis.py to installation directory
echo "Copying nemesis.py to $INSTALL_DIR..."
cp nemesis.py "$NEMESIS_SCRIPT"

# Set up virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create global command
echo "Creating global command at $BIN_DIR/nemesis..."
cat << 'EOF' | sudo tee "$BIN_DIR/nemesis" > /dev/null
#!/bin/bash
# Nemesis: Bash wrapper for Nemesis Python crawler
NEMESIS_DIR="$HOME/nemesis"

if [ ! -f "$NEMESIS_DIR/nemesis.py" ] || [ ! -f "$NEMESIS_DIR/venv/bin/activate" ]; then
    echo "Error: nemesis.py or virtual environment not found in $NEMESIS_DIR" >&2
    exit 1
fi

# Activate virtual environment
source "$NEMESIS_DIR/venv/bin/activate"

# Run the Python script
python "$NEMESIS_DIR/nemesis.py" "$@"
EOF

# Set permissions
sudo chmod +x "$BIN_DIR/nemesis"
chmod +x "$NEMESIS_SCRIPT"

# Clean up
deactivate

echo "✅ Installation complete!"
echo "Run 'nemesis -h' to see usage instructions."
echo "Ensure Tor and MongoDB are running with:"
if [[ "$DISTRO" == "Kali" ]]; then
    echo "  sudo systemctl status tor"
    echo "  sudo systemctl status mongodb"
elif [[ "$DISTRO" == "Ubuntu" ]]; then
    echo "  sudo systemctl status tor"
    echo "  sudo systemctl status mongod"
    echo "  Run 'mongosh' to enter MongoDB shell"
fi
