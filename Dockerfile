FROM python:3.12-slim

# Install build dependencies and CA certificates
RUN apt-get update && apt-get install -y \
    gcc \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application code
COPY agent_gateway.py .

# Expose the port that Uvicorn will listen on (default: 8000)
EXPOSE 8000

# Start the FastAPI app with Uvicorn using your agent_gateway.py file.
CMD ["uvicorn", "agent_gateway:app", "--host", "0.0.0.0", "--port", "8000"]
