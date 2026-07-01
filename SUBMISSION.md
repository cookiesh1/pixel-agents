# 과제 제출 — Pixel Agents × OpenRouter

원본 **Pixel Agents**(원래 Claude CLI + 훅으로만 캐릭터가 동작)를 수정하여,
**OpenRouter의 모델을 직접 연결해 에이전트를 구동**하도록 구현했습니다.

## 핵심 추가/수정 파일
- `server/src/internal/modelProvider.ts` — **OpenRouter 모델 호출 provider** (streamChat, 토큰 집계)
- `server/src/internal/agentEngine.ts` — **OpenRouter 기반 내부 에이전트 엔진**. Claude CLI 없이
  store에 직접 캐릭터(에이전트)를 만들고, 민원 1건을 6개 역할(분류·법령·쟁점·톤·작성·검수)로 처리.
  외부 파이프라인 단계에 맞춰 캐릭터를 실시간 동기화하는 `setStage / ensureCharacters / idleAll`도 포함.
- `server/src/httpServer.ts` — `/api/internal/run`, `/start`, `/stage`, `/end` 라우트 추가.
- `server/src/cli.ts`, `server/src/server.ts`, `server/src/configPersistence.ts` — internalEngine 배선 + OpenRouter 설정(`internalModel`, `OPENROUTER_API_KEY`).
- `webview-ui/src/components/BottomToolbar.tsx` 외 — 민원 처리 UI.

## 실행
```bash
npm install
export OPENROUTER_API_KEY=sk-or-...      # 본인 OpenRouter 키
npm run build
node dist/cli.js --port 3100             # http://localhost:3100
```
우측 하단 **민원 처리** 버튼 → OpenRouter 모델로 6개 에이전트가 민원을 처리하며 화면에서 움직입니다.

> 참고: 원본 저장소의 `.github/workflows/`(CI)는 제출 편의상 제외했습니다. 기능·소스에는 영향 없음.
