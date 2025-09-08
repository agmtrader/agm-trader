# Use an official Python runtime as the base image
FROM python:3.12.8-slim

# Add labels for metadata
LABEL maintainer="AGM Trader"
LABEL name="agm-trader"
LABEL version="1.0"
LABEL description="AGM Trader"

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install the required packages
RUN pip install --no-cache-dir -r requirements.txt

# Create directory for persistent database storage
RUN mkdir -p /app/src/db
RUN mkdir -p /app/cache

# Create volume mount points
VOLUME /app/src/db
VOLUME /app/cache

# Copy the application code
COPY . .

# Make run script executable
RUN chmod +x run.sh

# ARGS
ARG PORT
ENV PORT=${PORT}
EXPOSE ${PORT}

ENTRYPOINT ["./run.sh"]