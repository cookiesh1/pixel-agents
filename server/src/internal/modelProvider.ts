// OpenRouter(OpenAI 호환) 스트리밍 모델 제공자.
// 클로드 CLI 대신 API 모델로 에이전트를 구동하기 위한 핵심.
import type { InternalModelSettings } from '../configPersistence.js';

export interface ModelMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}
export interface ModelStreamCallbacks {
  onText?: (text: string) => void;
  signal?: AbortSignal;
}
export interface ModelResponse {
  content: string;
  inputTokens: number;
  outputTokens: number;
}

export class OpenRouterModelProvider {
  constructor(private readonly settings: InternalModelSettings) {}

  async streamChat(
    messages: ModelMessage[],
    cb: ModelStreamCallbacks = {},
  ): Promise<ModelResponse> {
    const apiKey = process.env[this.settings.apiKeyEnv];
    if (!apiKey) throw new Error(`API 키 없음: 환경변수 ${this.settings.apiKeyEnv} 를 설정하세요.`);

    const headers: Record<string, string> = {
      authorization: `Bearer ${apiKey}`,
      'content-type': 'application/json',
    };
    if (this.settings.baseUrl.includes('openrouter.ai')) {
      headers['HTTP-Referer'] = process.env['OPENROUTER_HTTP_REFERER'] ?? 'http://localhost';
      headers['X-Title'] = process.env['OPENROUTER_APP_TITLE'] ?? 'Pixel Agents';
    }

    const res = await fetch(`${this.settings.baseUrl.replace(/\/$/, '')}/chat/completions`, {
      method: 'POST',
      headers,
      signal: cb.signal,
      body: JSON.stringify({
        model: this.settings.model,
        messages,
        stream: true,
        stream_options: { include_usage: true },
        temperature: this.settings.temperature,
        max_tokens: this.settings.maxTokens,
      }),
    });
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => '');
      throw new Error(`모델 호출 실패 ${res.status}: ${text.slice(0, 200)}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let content = '';
    let inputTokens = 0;
    let outputTokens = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        const t = line.trim();
        if (!t.startsWith('data:')) continue;
        const data = t.slice(5).trim();
        if (data === '[DONE]') continue;
        try {
          const obj = JSON.parse(data) as {
            choices?: { delta?: { content?: string } }[];
            usage?: { prompt_tokens?: number; completion_tokens?: number };
          };
          const delta = obj.choices?.[0]?.delta?.content;
          if (delta) {
            content += delta;
            cb.onText?.(delta);
          }
          if (obj.usage) {
            inputTokens = obj.usage.prompt_tokens ?? inputTokens;
            outputTokens = obj.usage.completion_tokens ?? outputTokens;
          }
        } catch {
          /* 부분 청크 무시 */
        }
      }
    }
    return { content, inputTokens, outputTokens };
  }
}
