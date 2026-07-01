#!/bin/zsh
# 민원 워크벤치 실행 — OpenRouter 키는 환경변수로 주입(코드/스크립트에 하드코딩 금지).
cd "$(dirname "$0")"

if [ -z "$OPENROUTER_API_KEY" ]; then
  echo "❌ OPENROUTER_API_KEY 가 설정되지 않았습니다."
  echo "   예) export OPENROUTER_API_KEY=sk-or-... 후 다시 실행하세요."
  exit 1
fi

export PIXEL=1                                   # 픽셀 사무실(오른쪽) 실시간 연동 ON
export OFFICE_URL="${OFFICE_URL:-http://localhost:3100}"   # /combo 에서 임베드할 사무실 주소
export OFFICE_LOCAL="${OFFICE_LOCAL:-http://127.0.0.1:3100}"

if [ -f server.pid ] && kill -0 "$(cat server.pid)" 2>/dev/null; then
  echo "이미 실행 중 (pid $(cat server.pid)) — http://localhost:7878"; exit 0
fi
nohup python3 app.py > server.log 2>&1 &
echo $! > server.pid; sleep 2
if kill -0 "$(cat server.pid)" 2>/dev/null; then
  echo "✅ 시작 (pid $(cat server.pid)) — http://localhost:7878  (combo: http://localhost:7878/combo)"
  open http://localhost:7878/combo 2>/dev/null
else echo "❌ 실패"; tail -5 server.log; fi
