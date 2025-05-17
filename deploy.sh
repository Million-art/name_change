#!/bin/bash

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Python and pip
sudo apt-get install -y python3 python3-pip python3-venv

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install required packages
pip install -r requirements.txt

# Create systemd service
sudo tee /etc/systemd/system/name_change.service << EOF
[Unit]
Description=Telegram Name Tracker Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/name_change
Environment=PATH=/home/ubuntu/name_change/venv/bin
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/ubuntu/name_change/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Set proper permissions for .env file
chmod 600 .env

# Reload systemd and start service
sudo systemctl daemon-reload
sudo systemctl enable name_change
sudo systemctl restart name_change

# Check service status
sudo systemctl status name_change 