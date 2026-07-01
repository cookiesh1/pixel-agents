#!/usr/bin/env python3
"""민원 답변초안 워크벤치 v4 — 에디토리얼 라이트 + 구조화 출력 + 모델·비용 투명성.
구조: Supervisor(조정자) + 병렬 전문가 + 작성↔검수 루프.
실행: OPENROUTER_API_KEY=... python3 app.py  → http://localhost:7878
"""
import os, json, re, threading, queue, ssl, html as htmllib, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlreq
import certifi, openpyxl
from pixel_bridge import PixelBridge

SSL_CTX = ssl.create_default_context(cafile=certifi.where())
HERE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.environ.get("MINWON_XLSX") or os.path.join(HERE, "민원_데모_40건.xlsx")
MODEL_STRONG = os.environ.get("OR_STRONG", "anthropic/claude-sonnet-4.6")
MODEL_FAST   = os.environ.get("OR_FAST", "openai/gpt-4o-mini")
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
PORT = 7878
SHORT = {"openai/gpt-4o-mini":"GPT-4o mini","anthropic/claude-sonnet-4.6":"Claude Sonnet 4.6"}

TONE = {"정중":"매우 정중하고 공손하게","표준":"표준 행정 공문체로","간결":"간결하게 핵심 위주로","단호":"명확하고 단호한 어조로"}
LENGTH = {"요약":"짧게 요약하여","표준":"적정 분량으로","상세":"상세하고 친절하게"}

def load_xlsx_rows(path):
    wb = openpyxl.load_workbook(path, data_only=True); ws = wb.active
    rows = []
    for i, r in enumerate(ws.iter_rows(values_only=True)):
        if not r or all(c is None for c in r): continue
        c = [htmllib.unescape(str(x)) if x is not None else "" for x in r]
        if i == 0 and (len(c) > 1 and "제목" in c[1]): continue
        rows.append({"no": c[0] if c else str(i),
                     "title": c[1] if len(c) > 1 else c[0],
                     "body": c[2] if len(c) > 2 else (c[1] if len(c) > 1 else "")})
    return rows
MINWON = load_xlsx_rows(XLSX)

def _post(body):
    body["usage"] = {"include": True}
    req = urlreq.Request("https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json",
            "HTTP-Referer": "https://dapa.local", "X-Title": "minwon-agent"})
    return urlreq.urlopen(req, timeout=120, context=SSL_CTX)

def llm(system, user, model=MODEL_FAST, want_json=False):
    b = {"model": model, "messages":[{"role":"system","content":system},{"role":"user","content":user}]}
    if want_json: b["response_format"] = {"type":"json_object"}
    with _post(b) as r: out = json.load(r)
    txt = out["choices"][0]["message"]["content"]
    cost = (out.get("usage") or {}).get("cost", 0) or 0
    if want_json:
        try: val = json.loads(txt)
        except Exception:
            m = re.search(r"\{.*\}", txt, re.S); val = json.loads(m.group(0)) if m else {"raw":txt}
        return val, {"model": SHORT.get(model, model), "cost": cost}
    return txt, {"model": SHORT.get(model, model), "cost": cost}

def llm_stream(system, user, model, on_token):
    b = {"model": model, "stream": True, "messages":[{"role":"system","content":system},{"role":"user","content":user}]}
    full, cost = [], 0
    with _post(b) as r:
        for raw in r:
            line = raw.decode("utf-8","ignore").strip()
            if not line.startswith("data:"): continue
            data = line[5:].strip()
            if data == "[DONE]": break
            try: obj = json.loads(data)
            except Exception: continue
            delta = obj["choices"][0]["delta"].get("content") if obj.get("choices") else None
            if obj.get("usage"): cost = obj["usage"].get("cost", cost) or cost
            if delta: full.append(delta); on_token(delta)
    return "".join(full), {"model": SHORT.get(model, model), "cost": cost}

# ── 에이전트 (구조화 JSON 출력) ──────────────────────────────
def agent_orchestrator(m):
    return llm("공공기관 민원 분류 조정자. JSON만.",
        f'JSON:{{"category":"유형(2~6자)","department":"소관 추정 부서","difficulty":"상|중|하"}}\n제목:{m["title"]}\n본문:{m["body"][:900]}',
        MODEL_FAST, want_json=True)
def agent_law(m):
    return llm("공무원 인사·행정 법령 전문가. 단정 금지·불확실하면 표시. JSON만.",
        f'JSON:{{"laws":["관련 법령·규정명 2~4개"],"summary":"한줄 요지"}}\n제목:{m["title"]}\n본문:{m["body"][:900]}',
        MODEL_FAST, want_json=True)
def agent_issues(m):
    return llm("민원 쟁점 분석가. JSON만.",
        f'JSON:{{"questions":["핵심 질문 1~3개"],"keywords":["키워드 4~8개"]}}\n제목:{m["title"]}\n본문:{m["body"][:900]}',
        MODEL_FAST, want_json=True)
def agent_tone(m):
    return llm("민원 감정·민감도 분석가. JSON만.",
        f'JSON:{{"sentiment":"감정톤(2~6자)","urgency":"긴급도(상|중|하)","guide":"어조 가이드 한줄"}}\n제목:{m["title"]}\n본문:{m["body"][:700]}',
        MODEL_FAST, want_json=True)

DRAFT_SYS = "공공기관 민원 답변 작성자. 행정 공문체(번호목록 위주, 과한 마크다운 금지). 근거 없는 단정 금지, 확신 못 하면 [담당자 확인] 표시."
def draft_user(m, law, issues, tone, fb, tone_opt, len_opt):
    laws = ", ".join(law.get("laws", [])) if isinstance(law, dict) else str(law)
    qs = " / ".join(issues.get("questions", [])) if isinstance(issues, dict) else str(issues)
    guide = tone.get("guide", "") if isinstance(tone, dict) else str(tone)
    return f"""민원 답변 초안 작성. 구성: 인사말 → 질문별 답변(근거 인용) → 안내 → 맺음말.
[작성 지침] {TONE.get(tone_opt,'표준 공문체')}, {LENGTH.get(len_opt,'적정 분량')}.
{('[검수 피드백] '+fb) if fb else ''}
[제목]{m['title']}
[본문]{m['body'][:1100]}
[법령근거]{laws}
[핵심쟁점]{qs}
[어조가이드]{guide}"""
def agent_critic(m, draft):
    return llm("공정한 민원답변 검수관. 확신 못 하는 부분을 [담당자 확인]으로 표시했으면 감점 말 것. 공손+핵심답변이면 60+. 치명오류만 60 미만. JSON만.",
        f'JSON:{{"verdict":"PASS|FAIL","score":0-100,"issues":["2개 이내"],"feedback":"FAIL이면 한 문장"}}\n[민원]{m["title"]}\n[초안]{draft}',
        MODEL_STRONG, want_json=True)

def run_pipeline(m, tone_opt, len_opt, emit_raw):
    px = PixelBridge(); px.start_run(m)
    def emit(stage, status, payload):  # SSE + 픽셀 사무실 동시 전송
        emit_raw(stage, status, payload)
        px.on(stage, status)
    total = [0.0]
    def done(stage, out, meta):
        total[0] += meta.get("cost", 0) or 0
        emit(stage, "done", {"data": out, "model": meta["model"], "cost": meta.get("cost", 0), "total": total[0]})
    emit("classify", "start", "")
    cls, mt = agent_orchestrator(m); done("classify", cls, mt)

    emit("search", "start", "")  # 병렬 묶음 = '검색' 매크로 단계
    res = {}
    def w(name, fn):
        emit(name, "start", "")
        try: o, meta = fn(m)
        except Exception as e: o, meta = {"error": str(e)}, {"model": "-", "cost": 0}
        res[name] = (o, meta); emit(name, "subdone", {"data": o, "model": meta["model"], "cost": meta.get("cost", 0)})
    ths = [threading.Thread(target=w, args=n) for n in [("law", agent_law), ("issues", agent_issues), ("tone", agent_tone)]]
    for t in ths: t.start()
    for t in ths: t.join()
    smeta = {"model": res["law"][1]["model"], "cost": sum(res[k][1].get("cost", 0) or 0 for k in res)}
    done("search", {k: res[k][0] for k in res}, smeta)

    draft, review, fb = None, None, ""
    for i in range(1, 3):
        emit("write", "start", f"{i}차")
        draft, mt = llm_stream(DRAFT_SYS, draft_user(m, res["law"][0], res["issues"][0], res["tone"][0], fb, tone_opt, len_opt),
                               MODEL_STRONG, lambda tok: emit("write", "token", tok))
        done("write", draft, mt)
        emit("review", "start", f"{i}차")
        review, mt = agent_critic(m, draft); done("review", review, mt)
        if review.get("verdict") == "PASS" or (review.get("score") or 0) >= 60:
            review["verdict"] = "PASS"; break
        fb = review.get("feedback", "")
    px.end_run()
    emit("final", "done", {"draft": draft, "review": review, "minwon": m, "total": round(total[0], 6)})

# ── 서버 ─────────────────────────────────────────────────────
JOBS = {}; _lock = threading.Lock(); _ctr = [0]
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # chunked 스트리밍 + keep-alive (cloudflared SSE 버퍼링 방지)
    def log_message(self,*a): pass
    def _json(self,obj,code=200):
        body=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body))); self.end_headers()
        self.wfile.write(body)
    def _html(self,body):
        if isinstance(body,str): body=body.encode()
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",str(len(body))); self.end_headers()
        self.wfile.write(body)
    def _chunk(self,data:bytes):
        self.wfile.write(f"{len(data):X}\r\n".encode()+data+b"\r\n"); self.wfile.flush()
    def _read(self):
        n=int(self.headers.get("Content-Length",0)); return self.rfile.read(n)
    def do_POST(self):
        if self.path=="/api/start":
            d=json.loads(self._read() or b"{}")
            m={"no":d.get("no","-"),"title":d.get("title","").strip(),"body":d.get("body","").strip()}
            tone=d.get("tone","표준"); ln=d.get("length","표준")
            with _lock:
                _ctr[0]+=1; jid=str(_ctr[0])
                JOBS[jid]={"events":[],"done":False}
            def emit(a,s,o): JOBS[jid]["events"].append({"agent":a,"status":s,"output":o})
            def runner():
                emit("input","done",m)
                try: run_pipeline(m,tone,ln,emit)
                except Exception as e: emit("final","error",str(e))
                JOBS[jid]["done"]=True
            threading.Thread(target=runner,daemon=True).start()
            return self._json({"job":jid})
        if self.path=="/api/refine":
            d=json.loads(self._read() or b"{}")
            try: out,_=llm("공문 문장 교정기. 의미 유지·행정 공문체. 결과 문장만.",
                           f"[지시]{d.get('instruction','다듬어')}\n[원문]{d.get('text','')}", MODEL_STRONG)
            except Exception as e: out=d.get("text","")+f"(오류:{e})"
            return self._json({"text":out})
        if self.path=="/api/upload":
            raw=self._read(); fn=self.headers.get("X-Filename","up.xlsx")
            ext=".csv" if fn.lower().endswith(".csv") else ".xlsx"
            tmp=tempfile.NamedTemporaryFile(delete=False,suffix=ext); tmp.write(raw); tmp.close()
            try:
                if ext==".csv":
                    import csv,io; rows=[];
                    for i,r in enumerate(csv.reader(io.StringIO(raw.decode("utf-8","ignore")))):
                        if not r: continue
                        if i==0 and ("제목" in (r[1] if len(r)>1 else "")): continue
                        rows.append({"no":r[0] if r else str(i),"title":r[1] if len(r)>1 else r[0],"body":r[2] if len(r)>2 else ""})
                else: rows=load_xlsx_rows(tmp.name)
                return self._json({"rows":rows[:200]})
            except Exception as e: return self._json({"error":str(e)},400)
            finally: os.unlink(tmp.name)
        self._json({"error":"not found"},404)
    def do_GET(self):
        if self.path in ("/","/index.html"):
            return self._html(open(os.path.join(HERE,"dashboard.html"),"rb").read())
        if self.path in ("/combo","/combo.html"):
            office = os.environ.get("OFFICE_URL", "http://localhost:3100")
            html = f"""<!DOCTYPE html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>민원 워크벤치 + 픽셀 사무실</title>
<style>:root{{--bg:#f3eee4;--line:#e8e0d2;--ink:#2b241f;--sub:#8a8178}}*{{margin:0;box-sizing:border-box}}
body{{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;background:var(--bg);height:100dvh;display:flex;flex-direction:column}}
header{{padding:9px 16px;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--line)}}
header b{{font-size:14px;color:var(--ink)}} header span{{font-size:11.5px;color:var(--sub)}}
.split{{flex:1;display:flex;gap:0;min-height:0}}
.pane{{flex:1;display:flex;flex-direction:column;min-width:0;border-right:1px solid var(--line)}}
.pane:last-child{{border-right:none}}
.cap{{font-size:11px;font-weight:700;color:#b0542f;padding:6px 14px;background:#faf7f1;border-bottom:1px solid var(--line);letter-spacing:.04em}}
iframe{{flex:1;border:none;width:100%;background:#0d1018}}
@media(max-width:760px){{.split{{flex-direction:column}}.pane{{border-right:none;border-bottom:1px solid var(--line)}}}}
</style></head><body>
<header><b>🏛️ 민원 답변 워크벤치 + 픽셀 사무실</b><span>왼쪽에서 초안 생성 → 오른쪽 사무실에서 에이전트가 일합니다</span></header>
<div class=split>
  <div class=pane><div class=cap>📨 작업 대시보드</div><iframe src="/"></iframe></div>
  <div class=pane><div class=cap>🏢 픽셀 사무실 (실시간)</div><iframe src="{office}" allow="autoplay"></iframe></div>
</div></body></html>"""
            return self._html(html)
        if self.path=="/api/list":
            return self._json([{"no":x["no"],"title":x["title"],"body":x["body"]} for x in MINWON])
        if self.path.startswith("/api/poll"):
            mj=re.search(r"job=(\w+)",self.path); since=int((re.search(r"since=(\d+)",self.path) or ["",0])[1] or 0)
            job=JOBS.get(mj.group(1)) if mj else None
            if not job: return self._json({"events":[],"done":True,"next":since,"error":"expired"})
            evs=job["events"][since:]
            return self._json({"events":evs,"done":job["done"],"next":since+len(evs)})
        self._json({"error":"not found"},404)

if __name__ == "__main__":
    if not API_KEY: print("⚠️ OPENROUTER_API_KEY 필요")
    print(f"민원 {len(MINWON)}건 · 강:{MODEL_STRONG} 약:{MODEL_FAST} · http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1",PORT), H).serve_forever()
