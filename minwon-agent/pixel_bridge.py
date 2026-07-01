"""민원앱 → pixel-agents 실시간 동기화.
왼쪽 워크벤치의 '실제' 파이프라인 단계를 그대로 오른쪽 사무실에 밀어, 같은 캐릭터가
같은 순간에 움직이게 한다. 오른쪽은 더 이상 자체 LLM 시뮬레이션을 돌리지 않는다(중복 비용·타이밍 어긋남 제거).
단계 키(classify/law/issues/tone/write/review)는 오른쪽 캐릭터 6명과 1:1로 대응.
환경변수 PIXEL=1 일 때만 활성. 서버 없으면 조용히 무시(민원앱 본업엔 무영향)."""
import os, json, ssl, threading
from urllib import request as urlreq
import certifi

_SSL = ssl.create_default_context(cafile=certifi.where())
_BASE = os.environ.get("OFFICE_LOCAL", "http://127.0.0.1:3100") + "/api/internal"
# 오른쪽 캐릭터가 되는 6개 단계만 전달(매크로 'search'·'final'·'input' 등은 무시)
_ROLES = {"classify", "law", "issues", "tone", "write", "review"}

class PixelBridge:
    def __init__(self):
        self.ok = os.environ.get("PIXEL") == "1"

    def _post(self, path, payload):
        """비차단 fire-and-forget — 시각화 실패가 본업(민원 처리)을 절대 막지 않도록."""
        if not self.ok:
            return
        def fire():
            try:
                req = urlreq.Request(_BASE + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
                urlreq.urlopen(req, timeout=8, context=_SSL).read()
            except Exception:
                pass
        threading.Thread(target=fire, daemon=True).start()

    def start_run(self, m):
        """민원 처리 시작 → 6개 캐릭터 등장(대기)."""
        self._post("/start", {"title": m.get("title", ""), "body": m.get("body", "")})

    def on(self, stage, status):
        """실제 단계 전환을 해당 캐릭터에 반영. 'token'(스트리밍 글자)·매크로 단계는 무시."""
        if stage not in _ROLES:
            return
        if status == "start":
            self._post("/stage", {"role": stage, "status": "start"})
        elif status in ("done", "subdone"):  # 병렬 전문가는 subdone으로 끝남
            self._post("/stage", {"role": stage, "status": "done"})

    def end_run(self):
        """처리 종료 → 모든 캐릭터 대기."""
        self._post("/end", {})
