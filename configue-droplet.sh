# Update the droplet's package manager
sudo apt-get update
sudo apt-get upgrade

# Install required packages
sudo apt-get install -y git python3 python3-pip python3-venv

# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

# Install Docker:
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Test installations
docker --version
docker compose version

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Configure git
git config --global user.email "aa@agmtechnology.com"
git config --global user.name "AGM Developer"

# Create a directory for the Trader
mkdir -p ~/Trader
cd ~/Trader

# Clone the IBKR Gateway
git clone https://github.com/agmtrader/ibkr-gateway.git

# Clone the AGM Trader
git clone https://github.com/agmtrader/agm-trader.git
cd agm-trader

# Create a .env file
cp template.env .env
nano .env

# Build and start the containers
docker compose build
docker compose up -d

# Test the containers
docker ps
docker logs agm-trader-ibkr-gateway-1
docker logs agm-trader-agm-trader-1