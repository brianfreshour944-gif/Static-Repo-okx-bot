# Use a lightweight official Python runtime base image
FROM python:3.11-slim

# Turn off Python log buffering so logs stream directly to the Coolify live terminal console instantly
ENV PYTHONUNBUFFERED=1

# Establish our working folder directory inside the container
WORKDIR /app

# Copy dependency requirements first to utilize Docker build caching
COPY requirements.txt .

# Install necessary python modules
RUN pip install --no-cache-dir -r requirements.txt

# Copy over the core bot application logic file
COPY bot.py .

# Fire up the engine execution thread on startup
CMD ["python", "bot.py"]
