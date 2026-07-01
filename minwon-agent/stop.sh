#!/bin/zsh
cd "$(dirname "$0")"
[ -f server.pid ] && kill "$(cat server.pid)" 2>/dev/null && echo "🛑 종료" && rm -f server.pid || echo "실행 중 아님"
