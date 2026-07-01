// 내부 OpenRouter 에이전트 엔진 — 클로드/훅 없이 store에 직접 캐릭터를 만들고 구동.
// store.set() → agentCreated 브로드캐스트 → 캐릭터 등장.
// store.broadcast(agentStatus/agentToolStart/...) → 캐릭터가 일하는 모습.
import * as crypto from 'crypto';

import type { AgentStateStore } from '../agentStateStore.js';
import { readConfig } from '../configPersistence.js';
import type { AgentState } from '../types.js';
import { OpenRouterModelProvider } from './modelProvider.js';

// 민원 처리 6개 역할(= 캐릭터 6명)
export const COMPLAINT_ROLES = [
  {
    key: 'classify',
    name: '분류',
    sys: '민원을 읽고 소관 부서·유형·난이도를 한두 줄로 분류하세요.',
  },
  {
    key: 'law',
    name: '법령',
    sys: '민원과 관련된 법령·규정·지침 후보를 제시하세요. 불확실하면 [확인필요].',
  },
  { key: 'issues', name: '쟁점', sys: '민원인이 실제로 묻는 핵심 질문을 1~3개로 정리하세요.' },
  { key: 'tone', name: '톤', sys: '민원의 감정·긴급도를 판단하고 답변 어조를 한 줄로 제안하세요.' },
  {
    key: 'write',
    name: '작성',
    sys: '앞 분석을 종합해 공손한 행정 공문체 답변 초안을 작성하세요. 근거 없는 단정 금지, 불확실하면 [담당자 확인].',
  },
  {
    key: 'review',
    name: '검수',
    sys: '답변 초안의 정확성·근거·말투를 점검하고 한 줄 총평을 다세요.',
  },
] as const;

// 단계 키 → 진행 라벨(캐릭터 말풍선)
const STAGE_LABEL: Record<string, string> = {
  classify: '민원 분류 중',
  law: '관련 법령 검토 중',
  issues: '핵심 쟁점 분석 중',
  tone: '톤·민감도 분석 중',
  write: '답변 초안 작성 중',
  review: '답변 검수 중',
};

export class InternalAgentEngine {
  /** 외부(왼쪽 워크벤치) 파이프라인이 단계를 밀어줄 때, 캐릭터별 현재 toolId 추적. */
  private readonly stageTools = new Map<string, string>();

  constructor(private readonly store: AgentStateStore) {}

  /** 6개 역할 캐릭터를 보장(없으면 생성)하고 role.key → agentId 맵을 돌려줌. */
  ensureCharacters(): Map<string, number> {
    const ids = new Map<string, number>();
    for (const role of COMPLAINT_ROLES) {
      let agent = [...this.store.values()].find(
        (a) => a.folderName === role.name && a.providerId === 'internal',
      );
      if (!agent) agent = this.createAgent(role.name);
      ids.set(role.key, agent.id);
    }
    return ids;
  }

  /** 왼쪽 실제 파이프라인 단계에 맞춰 해당 캐릭터만 움직임(LLM 호출 없음). */
  setStage(roleKey: string, status: 'start' | 'done'): void {
    const role = COMPLAINT_ROLES.find((r) => r.key === roleKey);
    if (!role) return; // 캐릭터 없는 단계(search/final 등)는 무시
    const ids = this.ensureCharacters();
    const agentId = ids.get(roleKey)!;
    const agent = this.store.get(agentId);
    if (!agent) return;

    if (status === 'start') {
      const toolId = `stage-${Date.now()}-${agentId}`;
      this.stageTools.set(roleKey, toolId);
      agent.isWaiting = false;
      agent.lastDataAt = Date.now();
      this.store.broadcast({ type: 'agentStatus', id: agentId, status: 'active' });
      this.store.broadcast({
        type: 'agentToolStart',
        id: agentId,
        toolId,
        status: STAGE_LABEL[roleKey] ?? role.name,
        toolName: 'Thinking',
      });
    } else {
      const toolId = this.stageTools.get(roleKey) ?? `stage-${Date.now()}-${agentId}`;
      this.stageTools.delete(roleKey);
      agent.isWaiting = true;
      agent.lastDataAt = Date.now();
      this.store.broadcast({ type: 'agentToolDone', id: agentId, toolId });
      this.store.broadcast({ type: 'agentStatus', id: agentId, status: 'waiting' });
    }
    this.store.persist();
  }

  /** 처리 종료 — 모든 캐릭터를 대기 상태로. */
  idleAll(): void {
    const ids = this.ensureCharacters();
    for (const [roleKey, agentId] of ids) {
      const agent = this.store.get(agentId);
      if (!agent) continue;
      const toolId = this.stageTools.get(roleKey);
      if (toolId) {
        this.store.broadcast({ type: 'agentToolDone', id: agentId, toolId });
        this.stageTools.delete(roleKey);
      }
      agent.isWaiting = true;
      agent.lastDataAt = Date.now();
      this.store.broadcast({ type: 'agentStatus', id: agentId, status: 'waiting' });
    }
    this.store.persist();
  }

  /** 캐릭터(에이전트) 한 명 생성 → 화면에 등장. */
  createAgent(name: string): AgentState {
    const id = this.store.nextAgentId.current++;
    const agent: AgentState = {
      id,
      sessionId: crypto.randomUUID(),
      terminalRef: undefined,
      isExternal: false,
      projectDir: `/민원사무실/${name}`,
      jsonlFile: '',
      fileOffset: 0,
      lineBuffer: '',
      activeToolIds: new Set(),
      activeToolStatuses: new Map(),
      activeToolNames: new Map(),
      activeSubagentToolIds: new Map(),
      activeSubagentToolNames: new Map(),
      backgroundAgentToolIds: new Set(),
      isWaiting: true,
      permissionSent: false,
      hadToolsInTurn: false,
      folderName: name,
      lastDataAt: Date.now(),
      linesProcessed: 0,
      seenUnknownRecordTypes: new Set(),
      hookDelivered: true,
      hooksOnly: true,
      providerId: 'internal',
      inputTokens: 0,
      outputTokens: 0,
    };
    this.store.set(id, agent); // → 캐릭터 등장
    this.store.broadcast({ type: 'agentStatus', id, status: 'waiting', awaitingInput: true });
    this.store.persist();
    return agent;
  }

  /** 한 에이전트에게 메시지를 보내 OpenRouter로 응답 생성 + 캐릭터 애니메이션. */
  async run(
    agentId: number,
    sysPrompt: string,
    userMsg: string,
    statusLabel: string,
  ): Promise<string> {
    const agent = this.store.get(agentId);
    if (!agent) throw new Error(`에이전트 ${agentId} 없음`);
    const cfg = readConfig();
    const provider = new OpenRouterModelProvider(cfg.internalModel);
    const toolId = `internal-${Date.now()}-${agentId}`;

    agent.isWaiting = false;
    agent.lastDataAt = Date.now();
    this.store.broadcast({ type: 'agentStatus', id: agentId, status: 'active' });
    this.store.broadcast({
      type: 'agentToolStart',
      id: agentId,
      toolId,
      status: statusLabel,
      toolName: 'Thinking',
    });

    let out = '';
    try {
      const r = await provider.streamChat(
        [
          { role: 'system', content: sysPrompt },
          { role: 'user', content: userMsg },
        ],
        { onText: () => {} },
      );
      out = r.content;
      agent.inputTokens += r.inputTokens;
      agent.outputTokens += r.outputTokens;
      this.store.broadcast({
        type: 'agentTokenUsage',
        id: agentId,
        inputTokens: agent.inputTokens,
        outputTokens: agent.outputTokens,
      });
    } catch (err) {
      out = `(오류) ${err instanceof Error ? err.message : String(err)}`;
    } finally {
      agent.isWaiting = true;
      agent.lastDataAt = Date.now();
      this.store.broadcast({ type: 'agentToolDone', id: agentId, toolId });
      this.store.broadcast({ type: 'agentStatus', id: agentId, status: 'waiting' });
      this.store.persist();
    }
    return out;
  }

  /** 민원 1건을 6개 캐릭터가 순차 처리(분류→법령→쟁점→톤→작성→검수). */
  async runComplaint(title: string, body: string): Promise<{ draft: string; review: string }> {
    const ids = this.ensureCharacters(); // 캐릭터 없으면 생성(있으면 재사용)
    const minwon = `[제목] ${title}\n[본문] ${body}`;
    const get = (k: string) => COMPLAINT_ROLES.find((r) => r.key === k)!;

    const classify = await this.run(
      ids.get('classify')!,
      get('classify').sys,
      minwon,
      '민원 분류 중',
    );
    const [law, issues, tone] = await Promise.all([
      this.run(ids.get('law')!, get('law').sys, minwon, '관련 법령 검토 중'),
      this.run(ids.get('issues')!, get('issues').sys, minwon, '핵심 쟁점 분석 중'),
      this.run(ids.get('tone')!, get('tone').sys, minwon, '톤·민감도 분석 중'),
    ]);
    const writePrompt = `${minwon}\n[분류] ${classify}\n[법령] ${law}\n[쟁점] ${issues}\n[어조] ${tone}`;
    const draft = await this.run(
      ids.get('write')!,
      get('write').sys,
      writePrompt,
      '답변 초안 작성 중',
    );
    const review = await this.run(
      ids.get('review')!,
      get('review').sys,
      `${minwon}\n[초안] ${draft}`,
      '답변 검수 중',
    );
    return { draft, review };
  }
}
