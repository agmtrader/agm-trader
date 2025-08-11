#!/bin/bash

# If not already running over SSH, connect to the remote host and execute this script there
droplet_ip="agm-trader-node"
email="aa@agmtechnology.com"
name="AGM Developer"

if [ -z "$SSH_CONNECTION" ]; then
  scp .env $droplet_ip:/tmp/agm-trader.env
  ssh $droplet_ip "bash -s" < "$0"
  exit $?
fi

# This script is used to configure a new droplet for the AGM Auto Trader.

set -e
set -o pipefail

# Update the droplet's package manager
sudo apt-get update
sudo apt-get upgrade -y

# Install required packages
sudo apt-get install -y git python3 python3-pip python3-venv neovim

# Configure git
git config --global user.email $email
git config --global user.name $name

# Add Docker's official GPG key:
if ! command -v docker &> /dev/null; then
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

# Install Docker:
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker
fi

# Create a directory for the Trader
mkdir -p ~/Trader
cd ~/Trader

# Clone the IBKR Gateway
git clone https://github.com/agmtrader/ibkr-gateway.git

# Clone the AGM Trader
git clone https://github.com/agmtrader/agm-trader.git
cd agm-trader

# Place the .env that was copied over before SSH
if [ -f /tmp/agm-trader.env ]; then
  mv /tmp/agm-trader.env .env
fi

# Test installations
docker --version
docker compose version

# Build and start the containers
docker compose build
docker compose up -d

# Test the containers
docker ps