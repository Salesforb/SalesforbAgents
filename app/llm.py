"""Cervello SalesForB: modelli ChatGPT tramite il login OAuth (abbonamento ChatGPT, niente API key).

Il token lo gestisce il motore Hermes (login: `hermes auth add openai-codex`), che lo rinnova da solo
e con il suo lucchetto: qui lo leggiamo e lo teniamo in memoria fino a poco prima della scadenza.

Espone la stessa forma di risposta che il resto dell'app già usa
({"content": [blocchi text / tool_use], "stop_reason": ..., "model": ...}),
così brain.py resta identico nella logica degli strumenti.
"""
import base64, json, os, subprocess, threading, time, urllib.error, urllib.request, uuid

from toro_paths import DATA_HOME, BASE

CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
GATEWAY_PY = os.path.join(BASE, "gateway-runtime", "bin", "python")
_TOK = {"t": "", "exp": 0}
_TOK_LOCK = threading.Lock()
_SESSION = str(uuid.uuid4())


def env():
    out = {}
    try:
        for line in open(os.path.join(DATA_HOME, ".env")):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


def modello(strategico=False):
    e = env()
    if strategico:
        return e.get("SF_STRATEGY_MODEL") or e.get("SF_MODEL") or "gpt-6.1-sol"
    return e.get("SF_MODEL") or "gpt-6.1-sol"


# ------------------------------------------------------------------ token ChatGPT (OAuth)
def _jwt(token):
    try:
        p = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    except Exception:
        return {}


def _leggi_token(forza=False):
    codice = ("import json,sys\n"
              "from hermes_cli.auth_codex import resolve_codex_runtime_credentials as r\n"
              f"c=r(force_refresh={bool(forza)})\n"
              "print(json.dumps({'k':c.get('api_key',''),'u':c.get('base_url','')}))")
    out = subprocess.run([GATEWAY_PY, "-c", codice], capture_output=True, text=True, timeout=60,
                         env={**os.environ, "HERMES_HOME": DATA_HOME}, cwd=os.path.join(BASE, "hermes-agent"))
    if out.returncode != 0:
        raise RuntimeError("Login ChatGPT mancante o scaduto: apri il Terminale e lancia ~/.salesforb/login-chatgpt.sh "
                           f"({(out.stderr or '').strip().splitlines()[-1:] or ''})")
    d = json.loads(out.stdout.strip().splitlines()[-1])
    if not d.get("k"):
        raise RuntimeError("Login ChatGPT mancante: lancia ~/.salesforb/login-chatgpt.sh")
    return d["k"]


def token(forza=False):
    with _TOK_LOCK:
        if forza or not _TOK["t"] or time.time() > _TOK["exp"] - 300:
            t = _leggi_token(forza)
            _TOK.update(t=t, exp=float(_jwt(t).get("exp") or time.time() + 1800))
        return _TOK["t"]


def _headers(tok):
    h = {"Authorization": "Bearer " + tok, "Content-Type": "application/json", "Accept": "text/event-stream",
         "originator": "hermes-agent", "User-Agent": "HermesAgent/salesforb (SalesForB Agent)",
         "session_id": _SESSION}
    auth = _jwt(tok).get("https://api.openai.com/auth", {}) or {}
    if auth.get("chatgpt_account_id"):
        h["ChatGPT-Account-ID"] = auth["chatgpt_account_id"]
    res = auth.get("chatgpt_data_residency") or auth.get("chatgpt_compute_residency")
    if isinstance(res, str) and res.strip():
        h["x-openai-internal-codex-residency"] = res.strip()
    return h


def catalogo():
    """Modelli che l'account ChatGPT collegato può usare (catalogo Codex dell'account)."""
    codice = ("import json\n"
              "from hermes_cli.codex_models import get_codex_model_ids as g\n"
              f"print(json.dumps(g({token()!r})))")
    out = subprocess.run([GATEWAY_PY, "-c", codice], capture_output=True, text=True, timeout=60,
                         env={**os.environ, "HERMES_HOME": DATA_HOME}, cwd=os.path.join(BASE, "hermes-agent"))
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return []


def _salva_env(chiave, valore):
    p = os.path.join(DATA_HOME, ".env")
    righe = open(p).read().splitlines()
    for i, r in enumerate(righe):
        if r.startswith(chiave + "="):
            righe[i] = f"{chiave}={valore}"; break
    else:
        righe.append(f"{chiave}={valore}")
    open(p, "w").write("\n".join(righe) + "\n")


def scegli_modello(escludi=None):
    """Il piano ChatGPT non supporta il modello impostato: prendo il migliore disponibile e lo salvo."""
    lista = [m for m in catalogo() if m != escludi]
    if lista:
        _salva_env("SF_MODEL", lista[0])
        if env().get("SF_STRATEGY_MODEL") == escludi:
            _salva_env("SF_STRATEGY_MODEL", lista[0])
        return lista[0]
    return None


# ------------------------------------------------------------------ conversione formato
def _istruzioni(system):
    if isinstance(system, list):
        return "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))
    return str(system or "")


def _strumenti(tools):
    out = []
    for t in tools or []:
        if t.get("type", "").startswith("web_search"):
            out.append({"type": "web_search"})
        elif t.get("name"):
            out.append({"type": "function", "name": t["name"], "description": t.get("description", "")[:1000],
                        "parameters": t.get("input_schema") or {"type": "object", "properties": {}}, "strict": False})
    return out


def _input(messages):
    items = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            tipo = "input_text" if m["role"] == "user" else "output_text"
            items.append({"type": "message", "role": m["role"], "content": [{"type": tipo, "text": c}]})
            continue
        for b in c or []:
            ty = b.get("type")
            if ty == "_openai":
                items.append(b["item"])
            elif ty == "text" and b.get("text"):
                tipo = "input_text" if m["role"] == "user" else "output_text"
                items.append({"type": "message", "role": m["role"], "content": [{"type": tipo, "text": b["text"]}]})
            elif ty == "_image" and b.get("image_url"):
                items.append({"type": "message", "role": m["role"], "content": [{"type": "input_image", "image_url": b["image_url"], "detail": "auto"}]})
            elif ty == "_file" and b.get("file_data"):
                items.append({"type": "message", "role": m["role"], "content": [{"type": "input_file", "filename": b.get("filename") or "allegato", "file_data": b["file_data"]}]})
            elif ty == "tool_use":
                items.append({"type": "function_call", "call_id": b["id"], "name": b["name"],
                              "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)})
            elif ty == "tool_result":
                cont = b.get("content")
                if not isinstance(cont, str):
                    cont = json.dumps(cont, ensure_ascii=False)
                items.append({"type": "function_call_output", "call_id": b["tool_use_id"], "output": cont})
    return items


def _blocchi(output):
    blocks = []
    for it in output:
        ty = it.get("type")
        if ty == "message":
            txt = "".join(p.get("text", "") for p in it.get("content", []) if p.get("type") in ("output_text", "text"))
            if txt:
                blocks.append({"type": "text", "text": txt})
        elif ty == "function_call":
            try:
                args = json.loads(it.get("arguments") or "{}")
            except ValueError:
                args = {}
            blocks.append({"type": "tool_use", "id": it.get("call_id") or it.get("id"), "name": it.get("name"), "input": args})
        elif ty == "reasoning" and it.get("encrypted_content"):
            blocks.append({"type": "_openai", "item": {k: it[k] for k in ("type", "summary", "encrypted_content") if k in it}})
    return blocks


# ------------------------------------------------------------------ chiamata
def responses(messages, system, tools=None, on_text=None, strategico=False, annullato=None, max_tokens=None):
    """Una chiamata al modello ChatGPT (sempre in streaming: è l'unico modo che il backend accetta)."""
    model = modello(strategico)
    body = {"model": model, "instructions": _istruzioni(system), "input": _input(messages),
            "tools": _strumenti(tools), "tool_choice": "auto", "parallel_tool_calls": True,
            "store": False, "stream": True, "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": env().get("SF_EFFORT_STRATEGIA", "high") if strategico else env().get("SF_EFFORT", "low")},
            "prompt_cache_key": "salesforb-" + _SESSION[:8]}
    ultimo = None
    for tentativo in range(3):
        req = urllib.request.Request(CODEX_URL, data=json.dumps(body).encode(), method="POST", headers=_headers(token(tentativo == 1)))
        try:
            r = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            ultimo = f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
            if e.code == 401 and tentativo == 0:
                continue  # token appena scaduto: lo rinnovo e riprovo
            if e.code == 400 and "model" in ultimo and ("not supported" in ultimo or "model_not_found" in ultimo):
                nuovo = scegli_modello(escludi=body["model"])
                if nuovo and nuovo != body["model"]:
                    body["model"] = model = nuovo
                    continue
            if e.code == 400 and any(t.get("type") == "web_search" for t in body["tools"]):
                body["tools"] = [t for t in body["tools"] if t.get("type") != "web_search"]
                continue
            if e.code == 429:
                raise RuntimeError("Hai finito i crediti del piano ChatGPT per ora: riprova più tardi o passa a un piano superiore.")
            raise RuntimeError(ultimo)
        items, finale = [], None
        with r:
            for raw in r:
                if annullato and annullato():
                    raise RuntimeError("interrotto: nuova domanda")
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except ValueError:
                    continue
                ty = ev.get("type", "")
                if ty == "response.output_text.delta" and on_text:
                    try:
                        on_text(ev.get("delta", ""))
                    except (BrokenPipeError, ConnectionError):
                        raise
                    except Exception:
                        pass
                elif ty == "response.output_item.done":
                    items.append(ev.get("item") or {})
                elif ty in ("response.completed", "response.incomplete"):
                    finale = ev.get("response") or {}
                elif ty in ("response.failed", "error"):
                    err = (ev.get("response") or {}).get("error") or ev.get("error") or ev
                    raise RuntimeError("ChatGPT: " + str(err)[:300])
        output = items or (finale or {}).get("output") or []
        blocks = _blocchi(output)
        stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
        return {"content": blocks, "stop_reason": stop, "model": model}
    raise RuntimeError(ultimo or "ChatGPT non risponde")


def chat(system, testo, max_tokens=500, strategico=False):
    """Domanda semplice -> testo (consiglio, report, correzioni)."""
    r = responses([{"role": "user", "content": testo}], system, None, strategico=strategico)
    return " ".join(b["text"] for b in r["content"] if b["type"] == "text").strip(), r["model"]


def stato():
    try:
        t = token()
        auth = _jwt(t).get("https://api.openai.com/auth", {}) or {}
        return {"collegato": True, "piano": auth.get("chatgpt_plan_type", ""), "scade": int(_TOK["exp"])}
    except Exception as e:
        return {"collegato": False, "errore": str(e)[:200]}
