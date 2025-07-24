#!/bin/bash
# Setup script for Nemesis dark web crawler with robust error handling

set -euo pipefail  # Exit on error, unset variables, and pipe failures

# Detect OS
DISTRO=$(lsb_release -is 2>/dev/null || echo "Unknown")
UBUNTU_CODENAME=$(lsb_release -cs 2>/dev/null || echo "unknown")

echo "Detected Linux Distribution: $DISTRO"

# Define installation directory
INSTALL_DIR="$HOME/nemesis"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="/usr/local/bin"
NEMESIS_SCRIPT="$INSTALL_DIR/nemesis.py"
LOG_FILE="$INSTALL_DIR/install.log"

# Initialize log file
mkdir -p "$INSTALL_DIR"
echo "Nemesis Installation Log - $(date)" > "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

# Display ASCII banner
cat << 'EOF'
     _   __________  ______________ _________
   / | / / ____/  |/  / ____/ ___//  _/ ___/
  /  |/ / __/ / /|_/ / __/  \__ \ / / \__ \
 / /|  / /___/ /  / / /___ ___/ // / ___/ /
/_/ |_/_____/_/  /_/_____//____/___//____/
EOF

echo "Installing Nemesis dark web crawler..."

# Function to handle apt operations with error recovery
safe_apt_install() {
    local packages=$1
    echo "Attempting to install: $packages"
    
    if ! sudo apt-get install -y $packages; then
        echo "⚠️  Package installation failed, attempting recovery..."
        echo "🔄 Running apt-get update --fix-missing..."
        sudo apt-get update --fix-missing || true
        
        echo "🔄 Running apt --fix-broken install..."
        sudo apt-get --fix-broken install -y || true
        
        echo "🔄 Retrying package installation..."
        if ! sudo apt-get install -y $packages; then
            echo "❌ Critical error: Failed to install $packages after recovery attempts"
            exit 1
        fi
    fi
}

# Install dependencies with error handling
echo "Updating package lists with error handling..."
if ! sudo apt-get update; then
    echo "⚠️  Initial apt-get update failed, trying with --fix-missing..."
    sudo apt-get update --fix-missing || {
        echo "❌ Failed to update package lists. Check your internet connection."
        exit 1
    }
fi

if [[ "$DISTRO" == "Kali" ]]; then
    echo "Installing dependencies for Kali Linux..."
    safe_apt_install "tor mongodb python3 python3-pip python3-venv"

elif [[ "$DISTRO" == "Ubuntu" ]]; then
    echo "Installing dependencies for Ubuntu..."
    safe_apt_install "tor python3 python3-pip python3-venv curl gnupg lsb-release ca-certificates wget"

    echo "Installing MongoDB 7.0 for Ubuntu with error handling..."

    # MongoDB installation with error handling
    if ! curl -fsSL https://pgp.mongodb.com/server-7.0.asc | sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor; then
        echo "❌ Failed to import MongoDB GPG key"
        exit 1
    fi

    echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
        sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list || {
        echo "❌ Failed to add MongoDB repository"
        exit 1
    }

    echo "Updating package lists for MongoDB..."
    if ! sudo apt-get update; then
        echo "⚠️  MongoDB repo update failed, trying with --fix-missing..."
        sudo apt-get update --fix-missing || {
            echo "❌ Failed to update package lists for MongoDB"
            exit 1
        }
    fi

    safe_apt_install "mongodb-org"
fi

# Start and enable services with error handling
echo "Starting Tor and MongoDB services..."
if ! sudo systemctl start tor; then
    echo "⚠️  Failed to start Tor service"
    exit 1
fi

if ! sudo systemctl enable tor; then
    echo "⚠️  Failed to enable Tor service"
    exit 1
fi

if [[ "$DISTRO" == "Kali" ]]; then
    if ! sudo systemctl start mongodb; then
        echo "⚠️  Failed to start MongoDB service"
        exit 1
    fi
    
    if ! sudo systemctl enable mongodb; then
        echo "⚠️  Failed to enable MongoDB service"
        exit 1
    fi
elif [[ "$DISTRO" == "Ubuntu" ]]; then
    if ! sudo systemctl start mongod; then
        echo "⚠️  Failed to start MongoDB service"
        exit 1
    fi
    
    if ! sudo systemctl enable mongod; then
        echo "⚠️  Failed to enable MongoDB service"
        exit 1
    fi
fi

# Create installation directory
echo "Creating installation directory at $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR" || {
    echo "❌ Failed to create installation directory"
    exit 1
}

# Copy nemesis.py to installation directory
echo "Copying nemesis.py to $INSTALL_DIR..."
if ! cp nemesis.py "$NEMESIS_SCRIPT"; then
    echo "❌ Failed to copy nemesis.py"
    exit 1
fi

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
if ! python3 -m venv "$VENV_DIR"; then
    echo "❌ Failed to create Python virtual environment"
    exit 1
fi

source "$VENV_DIR/bin/activate" || {
    echo "❌ Failed to activate virtual environment"
    exit 1
}

# Install Python dependencies with error handling
echo "Installing Python dependencies..."
if ! pip install --upgrade pip; then
    echo "⚠️  Failed to upgrade pip, trying with --retries..."
    pip install --upgrade pip --retries 3 || {
        echo "❌ Failed to upgrade pip after retries"
        exit 1
    }
fi

if ! pip install -r requirements.txt; then
    echo "⚠️  Failed to install requirements, trying with --no-cache-dir..."
    pip install --no-cache-dir -r requirements.txt || {
        echo "❌ Failed to install Python requirements"
        exit 1
    }
fi

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
sudo chmod +x "$BIN_DIR/nemesis" || {
    echo "⚠️  Failed to set execute permissions on nemesis command"
    exit 1
}

chmod +x "$NEMESIS_SCRIPT" || {
    echo "⚠️  Failed to set execute permissions on nemesis.py"
    exit 1
}

# Clean up
deactivate

# Final message
echo "✅ Installation complete!"
echo "📄 Log file saved to: $LOG_FILE"
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
