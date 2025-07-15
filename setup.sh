#!/bin/bash
set -x
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv tor mongodb
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate
echo "Installing Python dependencies..."
pip install -r requirments.txt
deactivate
echo "Starting Tor service..."
sudo systemctl start tor
echo "Installing Nemesis CLI..."
sudo cp nemesis /usr/local/bin/nemesis
sudo chmod +x /usr/local/bin/nemesis
echo "Nemesis setup complete."
echo "To run 'nemesis' globally, set the NEMESIS_DIR environment variable:"
echo "  export NEMESIS_DIR=$(pwd)"
echo "Add it to ~/.bashrc for persistence: echo 'export NEMESIS_DIR=$(pwd)' >> ~/.bashrc"
echo "Then run 'nemesis -h' for usage."
