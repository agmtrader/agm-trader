#!/bin/bash

# This script is used to configure a new droplet for the AGM Auto Trader.

set -e
set -o pipefail

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
nvim .env

# Build and start the containers
docker compose build
docker compose up -d

# Test the containers
docker ps
docker logs agm-trader-ibkr-gateway-1
docker logs agm-trader-agm-trader-1