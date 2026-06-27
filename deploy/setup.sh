#!/bin/bash
# setup.sh — Oracle Cloud Free Tier Autopilot Deployment
# Run this ONCE on your Oracle Cloud VM (Ubuntu 22.04+)
#
# Before running:
#   1. SCP the project from your local machine:
#      scp -r yt_autopilot.zip user@<vm-ip>:~
#      (include yt_token.pickle so YouTube auth is already done)
#   2. SSH into the VM and unzip:
#      unzip yt_autopilot.zip -d ~/yt_autopilot
#   3. Run this script:
#      bash deploy/setup.sh

set -e

echo "=== Installing system dependencies ==="
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg unzip

echo "=== Setting up Python environment ==="
cd ~/yt_autopilot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Setting up environment variables ==="
# Add API keys to .bashrc so they persist across SSH sessions
cat >> ~/.bashrc << 'EOF'

# YouTube Autopilot API Keys
export LLM_PROVIDER="openai_compat"
export LLM_BASE_URL="https://api.groq.com/openai"
# Set these via environment or .env file:
# export LLM_API_KEY="your_groq_key"
# export LLM_MODEL="llama-3.3-70b-versatile"
# export PEXELS_API_KEY="your_pexels_key"
EOF

source ~/.bashrc

echo "=== Verifying YouTube auth token ==="
if [ -f data/yt_token.pickle ]; then
    echo "YouTube token found. Auth is already set up."
else
    echo "WARNING: No YouTube token found."
    echo "Run locally: python main.py --setup"
    echo "Then copy data/yt_token.pickle to this VM."
fi

echo "=== Setting up systemd service ==="
cat > /tmp/autopilot.service << 'SERVICEOF'
[Unit]
Description=YouTube Autopilot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/yt_autopilot
Environment=LLM_PROVIDER=openai_compat
Environment=LLM_BASE_URL=https://api.groq.com/openai
# Add your API keys here or use an EnvironmentFile=
# Environment=LLM_API_KEY=your_key
# Environment=LLM_MODEL=llama-3.3-70b-versatile
# Environment=PEXELS_API_KEY=your_key
ExecStart=/home/ubuntu/yt_autopilot/venv/bin/python /home/ubuntu/yt_autopilot/main.py --loop --interval=4
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
SERVICEOF

sudo mv /tmp/autopilot.service /etc/systemd/system/autopilot.service
sudo systemctl daemon-reload
sudo systemctl enable autopilot

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start the autopilot now:"
echo "  sudo systemctl start autopilot"
echo ""
echo "To check status:"
echo "  sudo systemctl status autopilot"
echo ""
echo "To view logs:"
echo "  journalctl -u autopilot -f"
echo ""
echo "To stop:"
echo "  sudo systemctl stop autopilot"
echo ""
echo "The autopilot will auto-start on boot."
echo ""
echo "To test manually first:"
echo "  cd ~/yt_autopilot && source venv/bin/activate && python main.py --status"
