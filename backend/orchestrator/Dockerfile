FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for torch/sentence-transformers
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# No COPY . . - we'll mount code via volume

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]