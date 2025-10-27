#!/bin/bash

set -e
set -o pipefail

#######################
# Check if we're on the droplet or local machine
#######################

# If we're already on the droplet (i.e., inside SSH), skip to remote setup
if [ -n "$SSH_CONNECTION" ]; then
  echo "=== Running on droplet - Installing prerequisites ==="
  
  # Function to wait for dpkg locks to be released
  wait_for_dpkg() {
    echo "Waiting for package manager to be available..."
    local max_wait=300  # Maximum 5 minutes
    local waited=0
    
    while [ $waited -lt $max_wait ]; do
      # Check if any dpkg/apt processes are running
      if ! sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 && \
         ! sudo fuser /var/lib/dpkg/lock >/dev/null 2>&1 && \
         ! pgrep -x apt-get >/dev/null 2>&1 && \
         ! pgrep -x dpkg >/dev/null 2>&1 && \
         ! pgrep -x needrestart >/dev/null 2>&1; then
        echo "Package manager is ready!"
        return 0
      fi
      
      if [ $((waited % 10)) -eq 0 ]; then
        echo "Still waiting for package manager... ($waited seconds elapsed)"
      fi
      
      sleep 2
      waited=$((waited + 2))
    done
    
    echo "Warning: Timed out waiting for package manager"
    return 1
  }
  
  #######################
  # Configure Non-Interactive Mode
  #######################
  export DEBIAN_FRONTEND=noninteractive
  
  # Disable needrestart to prevent it from holding locks
  sudo mkdir -p /etc/needrestart
  echo "\$nrconf{restart} = 'a';" | sudo tee /etc/needrestart/needrestart.conf > /dev/null
  
  #######################
  # Update System
  #######################
  echo "Updating package manager..."
  sudo -E apt-get update
  sudo -E apt-get upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
  
  # Wait for needrestart and other background processes to finish
  wait_for_dpkg

  #######################
  # Install Basic Packages
  #######################
  echo "Installing required packages..."
  sudo -E apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" git python3 python3-pip python3-venv neovim
  
  # Wait for any background processes to finish
  wait_for_dpkg

  #######################
  # Configure Git
  #######################
  echo "Configuring git..."
  email="aa@agmtechnology.com"
  username="AGM Developer"
  git config --global user.email $email
  git config --global user.name $username

  #######################
  # Install Docker
  #######################
  echo "Installing Docker..."
  if ! command -v docker &> /dev/null; then
    sudo -E apt-get update
    sudo -E apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    # Add the repository to Apt sources:
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo -E apt-get update

    # Install Docker:
    sudo -E apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Wait for any background processes to finish
    wait_for_dpkg

    # Add user to docker group
    sudo usermod -aG docker $USER
    newgrp docker
  fi

  # Test installations
  echo "Testing Docker installation..."
  docker --version
  docker compose version

  #######################
  # Install Trader
  #######################
  echo "Setting up Trader..."
  
  # Create a directory for the Trader
  mkdir -p ~/Trader
  cd ~/Trader

  # Clone the IBKR Gateway
  echo "Cloning IBKR Gateway..."
  git clone https://github.com/agmtrader/ibkr-gateway.git

  # Clone the AGM Trader
  echo "Cloning AGM Trader..."
  git clone https://github.com/agmtrader/agm-trader.git
  cd agm-trader

  # Place the .env that was copied over before SSH
  if [ -f /tmp/agm-trader.env ]; then
    echo "Moving .env file..."
    mv /tmp/agm-trader.env .env
  fi

  # Build and start the containers
  echo "Building Docker containers..."
  docker compose build
  
  echo "Starting IBKR Gateway..."
  docker compose up ibkr-gateway -d
  docker ps
  
  echo "Waiting 30 seconds for IBKR Gateway to initialize..."
  sleep 30
  
  echo "Starting Trader Socket..."
  docker compose up trader-socket -d
  docker ps
  
  echo "=== Droplet setup complete! ==="
  exit 0
fi

#######################
# LOCAL MACHINE - Provision and Connect
#######################

echo "=== Running on local machine - Provisioning droplet ==="

# -------- Configuration --------
NAME="agm-trader"
KEY_PATH="./keys/$NAME"

#######################
# Create SSH Keys
#######################
echo "Generating SSH keypair at $KEY_PATH..."
mkdir -p ./keys
rm -f "$KEY_PATH" "$KEY_PATH.pub"
ssh-keygen -q -t rsa -b 4096 -N "" -f "$KEY_PATH"
echo "SSH keys generated successfully"

#######################
# Authenticate with DigitalOcean
#######################
echo "Authenticating with DigitalOcean CLI..."
doctl auth init

#######################
# Provision Droplet
#######################
echo "Importing SSH key to DigitalOcean..."
ssh_key_id=$(doctl compute ssh-key import $NAME --public-key-file ${KEY_PATH}.pub --no-header --format ID)

echo "Creating droplet (this may take a few minutes)..."
droplet_ip=$(doctl compute droplet create $NAME \
  --region nyc3 \
  --image ubuntu-22-04-x64 \
  --size s-1vcpu-1gb \
  --ssh-keys $ssh_key_id \
  --wait \
  --no-header \
  --format PublicIPv4)

echo "Droplet created with IP: $droplet_ip"

#######################
# Wait for SSH to be Ready
#######################
echo "Waiting for SSH to become available..."
for i in {1..10}; do
  if ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 root@$droplet_ip "echo ssh-ok" &>/dev/null; then
    echo "SSH is available!"
    break
  fi
  echo "Waiting for SSH... attempt $i of 10"
  sleep 10
done

#######################
# Copy .env File to Droplet
#######################
if [ -f .env ]; then
  echo "Copying .env file to droplet..."
  scp -i "$KEY_PATH" \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      .env root@$droplet_ip:/tmp/agm-trader.env
  echo ".env file copied successfully"
else
  echo "Warning: .env file not found in current directory"
fi

#######################
# Connect to Droplet and Run Setup
#######################
echo "Connecting to droplet and running setup..."
ssh -i "$KEY_PATH" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    root@$droplet_ip "bash -s" < "$0"

echo "=== All done! Droplet is ready at $droplet_ip ==="
exit 0