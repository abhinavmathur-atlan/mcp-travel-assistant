FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the unified server
COPY unified_travel_server.py .
COPY pyproject.toml .

# Expose the default port
EXPOSE 8000

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default command to run the server in streamable-http mode
CMD ["python", "unified_travel_server.py", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000", "--path", "/"]
