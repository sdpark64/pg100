#!/bin/bash

# ==============================================================================
# 설정 변수
# ==============================================================================
PROJECT_DIR="/home/ubuntu/stock/pg100"
SCRIPT_NAME="stock_bot.py"
VENV_ACTIVATE="/home/ubuntu/stock/bin/activate"
LOG_FILE="output.log"

# ==============================================================================
# 1. 기존 프로세스 종료 (강화된 로직)
# ==============================================================================
echo "Checking for running process: $SCRIPT_NAME..."

# 실행 중인 프로세스 ID 찾기
PID=$(pgrep -f "python3.*$SCRIPT_NAME")

if [ -n "$PID" ]; then
    echo "Found running process (PID: $PID). Sending SIGTERM..."
    kill $PID
    
    # 프로세스가 종료될 때까지 최대 10초간 대기하며 확인
    MAX_RETRIES=10
    COUNT=0
    while [ $COUNT -lt $MAX_RETRIES ]; do
        if ! ps -p $PID > /dev/null; then
            echo "Process $PID terminated gracefully."
            break
        fi
        echo "Waiting for process to exit... ($((COUNT+1))/$MAX_RETRIES)"
        sleep 1
        ((COUNT++))
    done

    # 10초 후에도 살아있다면 강제 종료 (SIGKILL)
    if ps -p $PID > /dev/null; then
        echo "Process $PID did not exit. Forcing kill -9..."
        kill -9 $PID
        sleep 1
    fi
else
    echo "No running process found."
fi

# ==============================================================================
# 2. 디렉토리 이동 및 가상환경 실행
# ==============================================================================
cd "$PROJECT_DIR" || { echo "Directory not found! Exiting."; exit 1; }

if [ -f "$VENV_ACTIVATE" ]; then
    source "$VENV_ACTIVATE"
else
    echo "Error: Virtual environment not found at $VENV_ACTIVATE"
    exit 1
fi

# ==============================================================================
# 3. 프로세스 재실행 (로그 누적 방식 변경)
# ==============================================================================
echo "Starting $SCRIPT_NAME..."

# [수정] '>' 대신 '>>'를 사용하여 로그를 누적(Append)합니다.
# 실행 시점 구분을 위해 로그에 구분선을 추가합니다.
echo "------------------------------------------" >> "$LOG_FILE"
echo "Restarted at: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "------------------------------------------" >> "$LOG_FILE"

nohup python3 -u "$SCRIPT_NAME" >> "$LOG_FILE" 2>&1 &

NEW_PID=$!
echo "Success! $SCRIPT_NAME started with PID: $NEW_PID"

# ==============================================================================
# 4. 가상환경 종료
# ==============================================================================
deactivate

