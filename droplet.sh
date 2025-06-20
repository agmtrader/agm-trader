# Setup an Auto Trading Node
if [ -f .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ $line =~ ^[^#] ]]; then
            eval "export $line"
        fi
    done < .env
fi

# TODO: Create a new droplet
# TODO: Create a new ssh key for the droplet - find way of storing securely
# TODO: Provision the droplet

# Connect to droplet
droplet_ip="167.71.94.59"
ssh -i keys/droplet.pub root@${droplet_ip} 

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

sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Test installations
docker --version
docker compose version

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Create a directory for the Trader
mkdir -p ~/Trader
cd ~/Trader

# Clone the IBKR Gateway
git clone https://github.com/agmtrader/ibkr-gateway.git
cd ibkr-gateway

# WE ARE HERE!!!!!
# TODO: Create an ssh key for github - find way of storing securely
git config --global user.email "aa@agmtechnology.com"
git config --global user.name "AGM Developer"

# Clone the AGM Trader
git clone https://github.com/agmtrader/agm-trader.git
cd agm-trader

# Build and start the containers
docker compose build
docker compose up -d

# Test the containers
docker ps
docker logs agm-trader-ibkr-gateway-1
docker logs agm-trader-agm-trader-1