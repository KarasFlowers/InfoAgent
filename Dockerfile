# --- Stage 1: Build dependencies ---
FROM python:3.13-slim as builder

WORKDIR /app

# Install system dependencies for packages like chromadb/sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    gcc \
    # Needed for some SSL/scraping functionality
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install dependencies into a separate directory to keep image clean
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage 2: Final Image ---
FROM python:3.13-slim

WORKDIR /app

# Copy only the installed dependencies from builder
COPY --from=builder /install /usr/local

# Pre-warm sentence-transformers weights so the first user request is fast.
# The models are the exact ones used by app/services/rag_service.py.
ENV HF_HOME=/opt/hf-cache \
    SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache \
    TRANSFORMERS_OFFLINE=0
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; SentenceTransformer('BAAI/bge-m3'); CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# Copy the rest of the application
COPY . .

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# We use 0.0.0.0 so the app can be accessed from outside the container
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
