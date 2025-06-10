FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY run_server.py .

# Create directories for volumes
RUN mkdir -p appdata/config appdata/feeds appdata/podcasts

# Set environment variables
ENV BASE_URL=http://localhost:5000

# Expose port
EXPOSE 5000

# Run the application
CMD ["python", "run_server.py"]