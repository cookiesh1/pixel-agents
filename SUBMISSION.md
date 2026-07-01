# 과제 제출 — Pixel Agents × OpenRouter

원본 **Pixel Agents**(원래 Claude CLI + 훅으로만 캐릭터가 동작)를 수정하여,
**OpenRouter의 모델을 직접 연결해 에이전트를 구동**하도록 구현했습니다.
추가로, 실제 **민원 답변 멀티에이전트 워크벤치**(`minwon-agent/`)를 붙여 좌(워크벤치)→우(픽셀 사무실)
**실시간 동기화 combo 데모**까지 재현되게 했습니다.

## 핵심 추가/수정 파일 (OpenRouter 연동 = 과제 본질)
- `server/src/internal/modelProvider.ts` — **OpenRouter 모델 호출 provider** (streamChat, 토큰 집계)
- `server/src/internal/agentEngine.ts` — **OpenRouter 기반 내부 에이전트 엔진**. Claude CLI 없이
  store에 직접 캐릭터(에이전트)를 만들고, 민원 1건을 6개 역할(분류·법령·쟁점·톤·작성·검수)로 처리.
  외부 파이프라인 단계에 맞춰 캐릭터를 실시간 동기화하는 `setStage / ensureCharacters / idleAll` 포함.
- `server/src/httpServer.ts` — `/api/internal/run`, `/start`, `/stage`, `/end` 라우트.
- `server/src/cli.ts`, `server/src/server.ts`, `server/src/configPersistence.ts` — internalEngine 배선 + OpenRouter 설정(`internalModel`, `OPENROUTER_API_KEY`).
- `webview-ui/src/components/BottomToolbar.tsx` 외 — 민원 처리 UI.
- `minwon-agent/` — 민원 답변 워크벤치(Python). 실제 파이프라인 단계를 오른쪽 사무실에 실시간 push.

## 실행 A — 픽셀 사무실 단독 (과제 핵심만)
```bash
npm install
export OPENROUTER_API_KEY=sk-or-...      # 본인 OpenRouter 키
npm run build
node dist/cli.js --port 3100             # http://localhost:3100
```
우측 하단 **민원 처리** 버튼 → OpenRouter 모델로 6개 에이전트가 민원을 처리하며 화면에서 움직입니다.

## 실행 B — combo (localhost 데모 그대로: 좌 워크벤치 + 우 사무실 실시간 연동)
터미널 1 (사무실):
```bash
npm install && npm run build
export OPENROUTER_API_KEY=sk-or-...
node dist/cli.js --port 3100
```
터미널 2 (워크벤치):
```bash
cd minwon-agent
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-...
./start.sh                                # http://localhost:7878/combo 자동 오픈
```
combo 화면에서 왼쪽 민원 선택 → **초안 생성** → 오른쪽 캐릭터가 같은 단계(분류→법령·쟁점·톤→작성→검수)로 실시간 이동.

> 참고
> - `OPENROUTER_API_KEY` 는 **환경변수로만** 주입(코드·스크립트에 하드코딩 없음).
> - `dist/` 는 gitignore이므로 `npm run build`로 재생성(동작 동일).
> - 원본 저장소의 `.github/workflows/`(CI)는 제출 편의상 제외(기능·소스 무관).
