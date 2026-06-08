# Use the official lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Fix DNS resolution inside the container (critical for sandbox.okx.com)
RUN echo "nameserver 8.8.8.8" > /etc/resolv.conf

# Copy requirements first (better layer caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY bot.py .

# Command to run the bot
CMD ["python", "bot.py"]
