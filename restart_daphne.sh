#!/usr/bin/env bash
# Reinicia el daphne de FastChat DJ.
# Mata cualquier daphne que este escuchando en el puerto y levanta uno nuevo en
# foreground para que veas los logs. Ctrl+C lo detiene.
#
# Uso:
#   ./restart_daphne.sh            # puerto 8000 por defecto
#   ./restart_daphne.sh 8080       # puerto custom
set -euo pipefail

PORT="${1:-8000}"
HOST="0.0.0.0"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$PROJECT_DIR"

echo "[restart-daphne] Buscando procesos daphne en puerto $PORT..."

# --- Kill previo ---
# En Git Bash (Windows) netstat + taskkill. En Linux/Mac lsof + kill.
if command -v taskkill >/dev/null 2>&1; then
    # Windows
    PIDS="$(netstat -aon 2>/dev/null | grep -E ":${PORT}\s" | grep LISTENING | awk '{print $NF}' | sort -u || true)"
    if [ -n "$PIDS" ]; then
        echo "[restart-daphne] PIDs escuchando en :$PORT → $PIDS"
        for PID in $PIDS; do
            taskkill //F //PID "$PID" 2>/dev/null || taskkill /F /PID "$PID" 2>/dev/null || true
        done
        sleep 1
    else
        echo "[restart-daphne] Nadie escuchando en :$PORT."
    fi
    # Mata tambien cualquier daphne.exe huerfano
    taskkill //F //IM daphne.exe 2>/dev/null || taskkill /F /IM daphne.exe 2>/dev/null || true
else
    # Linux / macOS
    PIDS="$(lsof -ti :"$PORT" 2>/dev/null || true)"
    if [ -n "$PIDS" ]; then
        echo "[restart-daphne] PIDs escuchando en :$PORT → $PIDS"
        kill -9 $PIDS 2>/dev/null || true
        sleep 1
    else
        echo "[restart-daphne] Nadie escuchando en :$PORT."
    fi
    pkill -9 -f "daphne.*fastchatdj.asgi" 2>/dev/null || true
fi

# --- Activar venv ---
if [ -f ".venv/Scripts/activate" ]; then
    # Windows venv
    source .venv/Scripts/activate
elif [ -f ".venv/bin/activate" ]; then
    # Unix venv
    source .venv/bin/activate
else
    echo "[restart-daphne] WARNING: no encontre .venv — usando el python global."
fi

echo "[restart-daphne] Levantando daphne en $HOST:$PORT..."
echo "[restart-daphne] Ctrl+C para detener."
echo ""

exec daphne -b "$HOST" -p "$PORT" fastchatdj.asgi:application
