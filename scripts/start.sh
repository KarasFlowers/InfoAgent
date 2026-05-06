#!/usr/bin/env bash
# =========================================
#   InfoAgent - One-Click Launcher
#   Supports macOS and Linux
# =========================================
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

VENV_DIR="$PROJECT_ROOT/venv"
PYTHON="${VENV_DIR}/bin/python"
PIP="${VENV_DIR}/bin/pip"
UVICORN="${VENV_DIR}/bin/uvicorn"
PORT=8000
URL="http://127.0.0.1:${PORT}"

# Terminal colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }

# ---- 0) Check Python ----
SYSTEM_PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        SYSTEM_PYTHON="$candidate"
        break
    fi
done
if [ -z "$SYSTEM_PYTHON" ]; then
    error "Python 3 not found. Please install Python 3.11+ first."
    exit 1
fi
PY_VERSION=$("$SYSTEM_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Found $SYSTEM_PYTHON ($PY_VERSION)"

# ---- 1) Create venv if missing ----
if [ ! -f "$PYTHON" ]; then
    info "Creating virtual environment..."
    "$SYSTEM_PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created at $VENV_DIR"
fi

# ---- 2) Install / update dependencies ----
if [ ! -f "$UVICORN" ]; then
    info "Installing dependencies (this may take a few minutes on first run)..."
    "$PIP" install --upgrade pip -q
    "$PIP" install -r requirements.txt -q
    ok "Dependencies installed."
else
    info "Dependencies already installed. Skipping pip install."
fi

# ---- 3) Auto-generate .env if missing ----
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    warn ".env file not found."
    if [ -t 0 ]; then
        # Interactive terminal — prompt for API key
        echo ""
        echo -e "${CYAN}First-time setup: please enter your DeepSeek API key.${NC}"
        echo -e "  (Get one at https://platform.deepseek.com/api_keys)"
        echo -n "  DEEPSEEK_API_KEY: "
        read -r api_key
        if [ -n "$api_key" ]; then
            cp "$PROJECT_ROOT/.env.template" "$PROJECT_ROOT/.env"
            # Replace placeholder with actual key
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s|sk-your-deepseek-api-key-here|${api_key}|" "$PROJECT_ROOT/.env"
            else
                sed -i "s|sk-your-deepseek-api-key-here|${api_key}|" "$PROJECT_ROOT/.env"
            fi
            ok ".env created with your API key."
        else
            cp "$PROJECT_ROOT/.env.template" "$PROJECT_ROOT/.env"
            warn ".env created from template. Please edit it to add your API key."
        fi
    else
        cp "$PROJECT_ROOT/.env.template" "$PROJECT_ROOT/.env"
        warn ".env created from template. Please edit it to add your DEEPSEEK_API_KEY."
    fi
fi

# ---- 4) Ensure data directories exist ----
mkdir -p "$PROJECT_ROOT/data/sqlite" "$PROJECT_ROOT/data/chroma" "$PROJECT_ROOT/logs"

# ---- 5) Check if port is already in use ----
if command -v lsof &>/dev/null && lsof -iTCP:$PORT -sTCP:LISTEN &>/dev/null; then
    info "Port $PORT is already in use. Opening the existing dashboard..."
    if command -v xdg-open &>/dev/null; then
        xdg-open "$URL"
    elif command -v open &>/dev/null; then
        open "$URL"
    else
        info "Open $URL in your browser."
    fi
    exit 0
fi

# ---- 6) Check Redis (optional, non-fatal) ----
if command -v redis-cli &>/dev/null; then
    if redis-cli ping &>/dev/null; then
        ok "Redis is running."
    else
        warn "Redis is installed but not running. Caching will be disabled."
        warn "Start Redis with: redis-server --daemonize yes"
    fi
else
    warn "Redis not found. Caching will be disabled. Install with: sudo apt install redis-server / brew install redis"
fi

# ---- 7) Pre-download models if not cached ----
if [ ! -d "${HF_HOME:-$HOME/.cache/huggingface}/hub/models--BAAI--bge-m3" ]; then
    info "Pre-downloading embedding models (first run only, ~500MB)..."
    "$PYTHON" -c "
from sentence_transformers import SentenceTransformer, CrossEncoder
print('  Downloading BAAI/bge-m3 ...')
SentenceTransformer('BAAI/bge-m3')
print('  Downloading cross-encoder/ms-marco-MiniLM-L-6-v2 ...')
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
print('  Done.')
" && ok "Models cached." || warn "Model download failed. They will be downloaded on first use."
fi

# ---- 8) Start backend ----
info "Starting InfoAgent backend on $URL ..."
"$UVICORN" main:app --host 127.0.0.1 --port "$PORT" --reload &
SERVER_PID=$!

# ---- 9) Wait for healthy ----
info "Waiting for server..."
for i in $(seq 1 30); do
    if curl -sf "$URL/api/v1/ping" >/dev/null 2>&1; then
        ok "Server is ready!"
        # Open browser
        if command -v xdg-open &>/dev/null; then
            xdg-open "$URL"
        elif command -v open &>/dev/null; then
            open "$URL"
        else
            info "Open $URL in your browser."
        fi
        break
    fi
    sleep 1
done

echo ""
echo "==========================================="
echo "  Dashboard: $URL"
echo "  Press Ctrl+C to stop the server."
echo "==========================================="
wait $SERVER_PID
