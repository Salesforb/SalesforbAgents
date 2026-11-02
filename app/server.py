#!/usr/bin/env python3
"""Server della dashboard di SalesForB Agent. Ascolta solo sul Mac, su 127.0.0.1:8788.
Serve la pagina e /api/stato con i dati reali di Shopify SalesForB e della casella info@salesforb.com.
I colleghi arrivano dal Worker Cloudflare (accesso privato): il Worker firma ogni richiesta con SF_PROXY_KEY
e passa l'email del collega; solo gli indirizzi in SF_ADMINS (e chi usa il Mac) possono eseguire azioni."""
import datetime as dt, hmac, json, os, sys, threading, time, traceback, urllib.request, urllib.error, uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

from toro_paths import DATA_HOME, SKILLS_HOME, ENV_FILE

HERE = os.path.dirname(os.path.abspath(__file__))
SK = SKILLS_HOME
sys.path[:0] = [os.path.join(SK, "shopify/scripts"), os.path.join(SK, "email/scripts")]
TZ = ZoneInfo("Europe/Rome")
BEST = ()
CACHE = {"t": 0, "data": None}
LOCK = threading.Lock()
REFRESH_LOCK = threading.Lock()
DATA_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="SalesForBDati")
CACHE_FILE = os.path.join(DATA_HOME, "cache", "dashboard-stato.json")
try:
    with open(CACHE_FILE) as saved:
        snapshot = json.load(saved)
    if isinstance(snapshot, dict) and "shopify" in snapshot:
        CACHE["data"] = snapshot
except (OSError, ValueError):
    pass
VOICE_LOCK = threading.Lock()
VOICE_SESSION = {"id": "", "ultimo": 0, "stato": "spento"}


def sessione_voce(body):
    ident = str(body.get("id") or "")[:100]
    with VOICE_LOCK:
        if ident and (body.get("prendi") is True or not VOICE_SESSION["id"] or (VOICE_SESSION["id"] == ident)):
            VOICE_SESSION.update(id=ident, ultimo=time.time(), stato=str(body.get("stato") or "attivo")[:60])
        if ident and VOICE_SESSION["id"] == ident and isinstance(body.get("microfono"), dict):
            VOICE_SESSION["microfono"] = {k:body["microfono"].get(k) for k in ("rms","picco","rec","contesto","trascrivo","errore")}
        return {"attivo": bool(ident and VOICE_SESSION["id"] == ident), "stato": VOICE_SESSION["stato"]}



def safe(fn):
    try:
        return fn(), None
    except SystemExit as e:
        return None, str(e)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def shopify_data():
    import shopify as S
    orders = [o for o in S.orders_since("salesforb", 30) if S.valid(o)]
    now = dt.datetime.now(TZ)
    today = now.date()

    def amt(o): return float(o["totalPriceSet"]["shopMoney"]["amount"])
    def day(o): return dt.datetime.fromisoformat(o["createdAt"].replace("Z", "+00:00")).astimezone(TZ).date()

    days = [today - dt.timedelta(days=i) for i in range(6, -1, -1)]
    per = defaultdict(float)
    cur, prev = [], []
    for o in orders:
        d = day(o)
        per[d] += amt(o)
        age = (today - d).days
        if age <= 6:
            cur.append(o)
        elif age <= 13:
            prev.append(o)
    fatt, fprev = sum(map(amt, cur)), sum(map(amt, prev))
    top = Counter()
    for o in orders:
        for e in o["lineItems"]["edges"]:
            n = e["node"]
            top[f"{n['title']} · {n['variantTitle'] or '-'}"] += n["quantity"]
    paesi = Counter((o.get("shippingAddress") or {}).get("countryCodeV2") or "?" for o in cur)
    # scorte
    rows, after = [], None
    while True:
        d = S.gql("salesforb", S.VAR_Q, {"after": after})["productVariants"]
        rows += [e["node"] for e in d["edges"]]
        if not d["pageInfo"]["hasNextPage"]:
            break
        after = d["pageInfo"]["endCursor"]
    active = [v for v in rows if v["product"]["status"] == "ACTIVE"]
    low = sorted((v for v in active if (v["inventoryQuantity"] or 0) <= 5), key=lambda v: v["inventoryQuantity"] or 0)
    def canale(o):
        s = (o.get("sourceName") or "").lower()
        return "TikTok" if "tiktok" in s else "Shop app" if s == "3890849" else "Sito"
    canali7 = Counter(canale(o) for o in cur)
    ultimi = []
    for o in sorted(orders, key=lambda o: o["createdAt"], reverse=True)[:6]:
        it = o["lineItems"]["edges"][0]["node"] if o["lineItems"]["edges"] else {"title": "-", "variantTitle": ""}
        ultimi.append({"nome": o["name"], "importo": amt(o), "quando": day(o).strftime("%d/%m"), "canale": canale(o),
                       "citta": (o.get("shippingAddress") or {}).get("city") or "-",
                       "articolo": f"{it['title']} {it.get('variantTitle') or ''}".strip()})
    return {
        "fatturato7": fatt, "fatturatoPrec": fprev, "ordini7": len(cur), "ordiniPrec": len(prev),
        "aov7": fatt / len(cur) if cur else 0,
        "giorni": [{"d": d.strftime("%d/%m"), "v": round(per.get(d, 0), 2)} for d in days],
        "paesi": paesi.most_common(4),
        "top30": top.most_common(5),
        "scorte": [{"nome": v["displayName"], "qta": v["inventoryQuantity"] or 0,
                    "best": any(b in v["displayName"].lower() for b in BEST)} for v in low[:8]],
        "varianti": len(active), "ultimiOrdini": ultimi, "canali7": dict(canali7),
    }


def email_data():
    import email_toro as E
    out = {}
    import agents
    for acc in E.configured():
        rid = "email"
        agents.inizia(rid, f"Controlla la casella {E.ACCOUNTS[acc][0]}")
        def one(acc=acc):
            m = E.connect(acc)
            unseen = E.search(m, ["UNSEEN"])
            rows = E.headers(m, unseen[-6:])
            m.logout()
            return {"nonLette": len(unseen),
                    "ultime": [{"da": r["from"].split("<")[0].strip().strip('"')[:40] or r["from"][:40],
                                "oggetto": r["subject"][:80], "quando": r["date"]} for r in rows[:4]]}
        v, err = safe(one)
        out[acc] = v if v else {"errore": err}
        if v:
            agents.finisci(rid, f"{v['nonLette']} non lette" + (f" · ultima da {v['ultime'][0]['da'][:25]}" if v["ultime"] else ""))
        else:
            agents.finisci(rid, "Casella non raggiungibile", False)
    return out


def extra_data():
    """Agenda, call Calendly e incassi (se collegati)."""
    import brain
    out = {}
    if brain._calendari():
        ev = brain.agenda(2)
        out["agenda"] = ev if isinstance(ev, list) else []
    if env().get("CALENDLY_TOKEN"):
        d = brain.calendly_leggi()
        out["calendly"] = [{"nome": x.get("name", "Call"), "quando": x.get("start_time", "")} for x in (d.get("collection") or [])[:5]] if not d.get("errore") else {"errore": d["errore"][:120]}
    inc = {}
    if env().get("STRIPE_KEY"):
        b = brain.pagamenti("stripe", "balance")
        if not b.get("errore"):
            inc["stripe"] = {"disponibile": sum(x["amount"] for x in b.get("available", []) if x["currency"] == "eur") / 100,
                             "inArrivo": sum(x["amount"] for x in b.get("pending", []) if x["currency"] == "eur") / 100}
    if env().get("PAYPAL_CLIENT_ID"):
        b = brain.pagamenti("paypal", "v1/reporting/balances", {"currency_code": "EUR"})
        if not b.get("errore"):
            try:
                inc["paypal"] = {"disponibile": float(b["balances"][0]["available_balance"]["value"])}
            except Exception:
                pass
    if inc:
        out["incassi"] = inc
    return out


def build():
    import agents
    t0 = time.time()
    agents.inizia("shop", "Sincronizza ordini, clienti e prodotti SalesForB")
    lavori = {nome: DATA_POOL.submit(safe, funzione) for nome, funzione in (
        ("shop", shopify_data), ("mail", email_data), ("extra", extra_data))}
    shop, eshop = lavori["shop"].result()
    if shop:
        agents.finisci("shop", f"Sincronizzati {shop['ordini7']} ordini negli ultimi 7 giorni")
    else:
        agents.finisci("shop", "Shopify SalesForB da collegare" if eshop and "mancano le credenziali" in eshop else "Shopify non risponde", False)
    mail, email_err = lavori["mail"].result()
    ext, ext_err = lavori["extra"].result()
    import toro_plus, llm
    crm_s, _ = safe(lambda: toro_plus.crm("elenco"))
    gpt = llm.stato()
    avvisi = []
    if shop:
        if shop["fatturatoPrec"] and shop["fatturato7"] < shop["fatturatoPrec"] * 0.7:
            avvisi.append({"liv": "warn", "testo": f"Incassi Shopify 7 giorni giù del {round(100 - shop['fatturato7'] / shop['fatturatoPrec'] * 100)}% rispetto alla settimana prima.", "fonte": "SalesForB · Shopify"})
        for o in shop["ultimiOrdini"]:
            if o["importo"] >= 500:
                avvisi.append({"liv": "ok", "testo": f"Nuovo ordine importante {o['nome']}: € {o['importo']:.0f}.", "fonte": "SalesForB · Shopify"})
    elif eshop:
        avvisi.append({"liv": "warn", "testo": ("Shopify SalesForB da collegare: aggiungi le credenziali in ~/.salesforb/data/.env" if "mancano le credenziali" in eshop else "Shopify non risponde: " + eshop[:120]), "fonte": "Sistema"})
    for acc, v in (mail or {}).items():
        if v.get("errore"):
            avvisi.append({"liv": "warn", "testo": f"Casella {acc} non raggiungibile.", "fonte": "Email"})
    if not gpt.get("collegato"):
        avvisi.append({"liv": "crit", "testo": "ChatGPT non collegato: lancia ~/.salesforb/login-chatgpt.sh", "fonte": "Sistema"})
    cfg = env()
    return {"aggiornato": dt.datetime.now(TZ).strftime("%H:%M"), "secondi": round(time.time() - t0, 1), "azienda": "SalesForB",
            "shopify": shop, "shopifyErrore": eshop, "email": mail or {}, "emailErrore": email_err,
            "avvisi": (toro_plus.EVENTI[:3] + avvisi)[:7], **(ext or {}),
            "crm": crm_s, "sentinella": dict(toro_plus.STATO_SENT), "chatgpt": gpt,
            "collegamenti": {"shopify": bool(shop), "email": bool(mail), "voce": True, "chatgpt": bool(gpt.get("collegato")),
                             "calendario": bool((ext or {}).get("agenda") is not None or (ext or {}).get("calendly")),
                             "telegram": bool(cfg.get("TELEGRAM_BOT_TOKEN") and (cfg.get("TORO_TELEGRAM_CHAT") or cfg.get("TELEGRAM_ALLOWED_USERS") or cfg.get("TELEGRAM_HOME_CHANNEL"))),
                             "cloudflare": os.path.exists(os.path.join(DATA_HOME, "secrets", "cloudflare.json"))}}


def _aggiorna_stato():
    """Il chiamante acquisisce REFRESH_LOCK prima di avviare l'aggiornamento."""
    try:
        data = build()
        with LOCK:
            CACHE.update(data=data, t=time.time())
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            fd = os.open(CACHE_FILE + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as saved:
                json.dump(data, saved, ensure_ascii=False)
            os.replace(CACHE_FILE + ".tmp", CACHE_FILE)
        except OSError:
            traceback.print_exc()
        return data
    except Exception:
        traceback.print_exc()
        with LOCK:
            return CACHE["data"] or {"errore": "Impossibile leggere i dati"}
    finally:
        REFRESH_LOCK.release()


def stato(force=False):
    with LOCK:
        data, timestamp = CACHE["data"], CACHE["t"]
    scaduto = force or not data or time.time() - timestamp > 300
    if data:
        if scaduto and REFRESH_LOCK.acquire(blocking=False):
            threading.Thread(target=_aggiorna_stato, daemon=True, name="SalesForBAggiornamento").start()
        return data
    if REFRESH_LOCK.acquire(blocking=False):
        return _aggiorna_stato()
    # Solo il primissimo avvio attende una lettura: i successivi usano la copia locale.
    with REFRESH_LOCK:
        with LOCK:
            return CACHE["data"] or {"errore": "Impossibile leggere i dati"}


# ---------- Conversazione con SalesForB Agent (ChatGPT) e voce locale (Kokoro / macOS) ----------
HIST = []


def env():
    out = {}
    try:
        for line in open(ENV_FILE):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


def post_json(url, payload, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def chiedi_a_toro(testo):
    import brain
    return brain.rispondi(testo, CACHE.get("data") or {})["risposta"]


def voce_stream(handler, testo):
    """Voce locale: Kokoro su Apple Silicon (o la voce italiana di macOS). Nessun servizio esterno."""
    import tts
    audio = tts.sintetizza(testo)
    if not audio:
        handler.send(204, b"", "text/plain"); return
    handler.send(200, audio, "audio/wav")


def utente(handler):
    """Chi sta parlando. Dal Mac: il titolare (amministratore). Dal Worker: l'email del collega, firmata."""
    cfg = env()
    via_rete = bool(handler.headers.get("Cf-Connecting-Ip") or handler.headers.get("X-SF-Proxy-Key"))
    if not via_rete:
        return {"email": cfg.get("SF_OWNER_EMAIL", "info@salesforb.com"), "admin": True, "locale": True}
    chiave = cfg.get("SF_PROXY_KEY", "")
    if not chiave or not hmac.compare_digest(handler.headers.get("X-SF-Proxy-Key", ""), chiave):
        return None
    email = (handler.headers.get("X-SF-User") or "").strip().lower()[:120]
    admins = {x.strip().lower() for x in cfg.get("SF_ADMINS", "").split(",") if x.strip()}
    return {"email": email or "collega", "admin": email in admins, "locale": False}


def trascrivi_audio(audio, mime="audio/webm"):
    """Whisper large-v3 trascrive in locale, l'agente riceve il testo risultante."""
    if not audio or len(audio) < 500:
        return {"testo": "", "errore": "audio troppo breve"}
    if len(audio) > 8 * 1024 * 1024:
        return {"testo": "", "errore": "audio troppo grande"}
    mime = mime.split(";", 1)[0].strip().lower()
    if mime not in {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav"}:
        return {"testo": "", "errore": "formato audio non supportato"}
    import inspect, voice_input
    parametri = inspect.signature(voice_input.trascrivi).parameters
    return voice_input.trascrivi(audio, env(), mime) if len(parametri) >= 3 else voice_input.trascrivi(audio, env())


# ---------- Accesso dei colleghi (codice via email da info@salesforb.com) ----------
CODICI = {}
CODICI_LOCK = threading.Lock()


def ammesso(email):
    cfg = env()
    voci = [x.strip().lower() for x in (cfg.get("SF_TEAM", "@salesforb.com") + "," + cfg.get("SF_ADMINS", "")).split(",") if x.strip()]
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 120:
        return False
    return any(email == v or (v.startswith("@") and email.endswith(v)) for v in voci)


def accesso_codice(email):
    import hashlib, secrets as sec
    email = (email or "").strip().lower()
    if not ammesso(email):
        return {"ok": False, "errore": "Questa email non è abilitata. Chiedi a un amministratore SalesForB."}
    with CODICI_LOCK:
        prima = CODICI.get(email)
        if prima and time.time() - prima["inviato"] < 60:
            return {"ok": True}
        codice = f"{sec.randbelow(1000000):06d}"
        CODICI[email] = {"h": hashlib.sha256(codice.encode()).hexdigest(), "scade": time.time() + 600, "tentativi": 0, "inviato": time.time()}
    import brain
    brain.invia_email({"account": "salesforb", "a": email, "oggetto": f"Codice di accesso SalesForB Agent: {codice}",
                       "testo": f"Ciao,\n\nil tuo codice per entrare in SalesForB Agent è: {codice}\nVale 10 minuti.\n\nSe non l'hai richiesto tu, ignora questa email.\n\nIl team SalesForB"})
    return {"ok": True}


def accesso_verifica(email, codice):
    import hashlib
    email = (email or "").strip().lower()
    with CODICI_LOCK:
        v = CODICI.get(email)
        if not v or time.time() > v["scade"] or v["tentativi"] >= 5:
            CODICI.pop(email, None)
            return {"ok": False, "errore": "Codice scaduto: richiedine uno nuovo."}
        v["tentativi"] += 1
        if hmac.compare_digest(v["h"], hashlib.sha256(str(codice).strip().encode()).hexdigest()):
            CODICI.pop(email, None)
            return {"ok": True}
    return {"ok": False, "errore": "Codice non corretto."}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location, code=302):
        self.send_response(code)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        p = self.path.split("?")[0]
        if utente(self) is None:
            self.send(403, b"accesso negato", "text/plain"); return
        if p in ("/", "/index.html"):
            self.send(200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8")
        elif p == "/aqua.css":
            f = os.path.join(HERE, "aqua.css")
            self.send(200, open(f, "rb").read(), "text/css; charset=utf-8") if os.path.isfile(f) else self.send(404, b"non trovato", "text/plain")
        elif p in ("/salesforb-logo.png", "/salesforb-logo-dark.png", "/salesforb-b.png", "/salesforb-icon.png", "/salesforb-core.png", "/favicon.png"):
            f = os.path.join(HERE, "brand", "salesforb-icon.png" if p == "/favicon.png" else p.strip("/"))
            self.send(200, open(f, "rb").read(), "image/png") if os.path.isfile(f) else self.send(404, b"non trovato", "text/plain")
        elif p.startswith("/brand/"):
            nome = os.path.basename(p)
            ammessi = {"shopify.svg", "gmail.svg", "telegram.svg", "whatsapp.svg", "github.svg", "chatgpt.svg", "whisper.svg", "cloudflare.svg", "voce.svg", "linkedin.svg", "instagram.svg"}
            f = os.path.join(HERE, "brand", nome)
            self.send(200, open(f, "rb").read(), "image/svg+xml") if nome in ammessi and os.path.isfile(f) else self.send(404, b"non trovato", "text/plain")
        elif p == "/api/sistema":
            import voice_input, wake_input
            import tts, llm
            out = {"esecuzione": "locale", "azienda": "SalesForB", "piattaforma": "macOS Apple Silicon", "pid": os.getpid(),
                   "trascrizione": "Whisper " + voice_input.NOME_MODELLO, "lingua": "it", "whisper_pronto": getattr(voice_input, "_MODEL", None) is not None,
                   "cervello": "ChatGPT (login OAuth) · " + llm.modello(), "voce": tts.MOTORE.get("nome"), "server_remoto": False,
                   "letture_parallele": 4, "cache_locale": bool(CACHE["data"]),
                   "risveglio_rapido": getattr(wake_input, "_MODEL", None) is not None}
            self.send(200, json.dumps(out).encode(), "application/json")
        elif p == "/api/voce-sessione":
            with VOICE_LOCK:
                out = {"attivo": bool(VOICE_SESSION["id"] and time.time() - VOICE_SESSION["ultimo"] < 15),
                       "stato": VOICE_SESSION["stato"], "aggiornato": VOICE_SESSION["ultimo"], "microfono": VOICE_SESSION.get("microfono", {})}
            self.send(200, json.dumps(out).encode(), "application/json")
        elif p == "/api/consiglio":
            import toro_plus
            self.send(200, json.dumps(toro_plus.CONSIGLIO, ensure_ascii=False).encode(), "application/json")
        elif p == "/api/versione":
            self.send(200, str(int(os.path.getmtime(os.path.join(HERE, "index.html")))).encode(), "text/plain")
        elif p == "/api/agenti":
            import agents
            col = (CACHE.get("data") or {}).get("collegamenti") or {"shopify": True, "email": True, "meta": False}
            self.send(200, json.dumps(agents.elenco(col), ensure_ascii=False).encode(), "application/json")
        elif p == "/api/stato":
            self.send(200, json.dumps(stato("refresh=1" in self.path), ensure_ascii=False).encode(), "application/json")
        elif p == "/api/voce":
            from urllib.parse import parse_qs, urlparse
            try:
                voce_stream(self, (parse_qs(urlparse(self.path).query).get("t") or [""])[0][:900])
            except Exception as e:
                try:
                    self.send(502, str(e).encode()[:200], "text/plain")
                except Exception:
                    pass
        elif p == "/api/io":
            u = utente(self) or {}
            self.send(200, json.dumps({"email": u.get("email"), "admin": u.get("admin", False)}).encode(), "application/json")
        elif p in ("/saluto.wav", "/saluto.mp3"):
            f = os.path.join(HERE, "saluto.wav")
            if not os.path.exists(f):
                import tts
                tts.prepara()
            self.send(200, open(f, "rb").read(), "audio/wav") if os.path.exists(f) else self.send(404, b"", "text/plain")
        else:
            self.send(404, b"non trovato", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        p = self.path.split("?")[0]
        chi = utente(self)
        if chi is None:
            self.send(403, b"accesso negato", "text/plain"); return
        if p in ("/api/trascrivi", "/api/ascolta", "/api/risveglio"):
            if n <= 0 or n > 8 * 1024 * 1024:
                self.close_connection = True
                self.send(413 if n > 0 else 400, json.dumps({"errore": "dimensione audio non valida"}).encode(), "application/json")
                return
            try:
                mime = self.headers.get("Content-Type", "audio/webm").split(";", 1)[0].strip().lower()
                audio = self.rfile.read(n)
                if p == "/api/risveglio":
                    import wake_input
                    out = wake_input.rileva(audio)
                else:
                    out = trascrivi_audio(audio, mime)
                self.send(200, json.dumps(out, ensure_ascii=False).encode(), "application/json")
            except urllib.error.HTTPError as e:
                self.send(502, json.dumps({"errore": f"Trascrizione HTTP {e.code}: {e.read().decode(errors='replace')[:180]}"}).encode(), "application/json")
            except Exception as e:
                self.send(502, json.dumps({"errore": f"{type(e).__name__}: {e}"}).encode(), "application/json")
            return
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        if p == "/api/voce-sessione":
            self.send(200, json.dumps(sessione_voce(body)).encode(), "application/json")
            return
        if p in ("/api/accesso/codice", "/api/accesso/verifica"):
            try:
                out = accesso_codice(body.get("email")) if p.endswith("codice") else accesso_verifica(body.get("email"), body.get("codice"))
            except Exception as e:
                out = {"ok": False, "errore": "Invio del codice non riuscito: " + str(e)[:120]}
            self.send(200, json.dumps(out, ensure_ascii=False).encode(), "application/json")
            return
        testo = str(body.get("testo", ""))[:2000]
        allegati = []
        for item in (body.get("allegati") or [])[:4]:
            if not isinstance(item, dict):
                continue
            nome = os.path.basename(str(item.get("name") or "allegato"))[:120]
            tipo = str(item.get("type") or "application/octet-stream")[:80]
            kind = str(item.get("kind") or "")
            if kind == "text":
                allegati.append({"name": nome, "type": tipo, "kind": "text", "text": str(item.get("text") or "")[:30000]})
            elif kind in ("image", "file"):
                data = str(item.get("data") or "")
                if data.startswith("data:") and len(data) <= 7_500_000:
                    allegati.append({"name": nome, "type": tipo, "kind": kind, "data": data})
        try:
            if p == "/api/chat":
                import brain
                t0 = time.time()
                out = brain.rispondi(testo, CACHE.get("data") or stato(), utente=chi["email"], admin=chi["admin"], allegati=allegati)
                out["secondi"] = round(time.time() - t0, 1)
                self.send(200, json.dumps(out, ensure_ascii=False).encode(), "application/json")
            elif p == "/api/chat-stream":
                import brain
                t0 = time.time()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()

                def riga(obj):
                    self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
                    self.wfile.flush()
                try:
                    out = brain.rispondi(testo, CACHE.get("data") or stato(), on_text=lambda s: riga({"t": s}), utente=chi["email"], admin=chi["admin"], allegati=allegati)
                    out["secondi"] = round(time.time() - t0, 1)
                    out["fine"] = True
                    riga(out)
                except Exception as e:
                    riga({"fine": True, "errore": str(e)[:200]})
                self.close_connection = True
            elif p == "/api/esegui" and not chi["admin"]:
                self.send(200, json.dumps({"ok": False, "messaggio": "Solo un amministratore SalesForB può confermare le azioni."}).encode(), "application/json")
            elif p == "/api/esegui":
                import brain
                out = brain.esegui(str(body.get("id", "")))
                if out.get("ok"):
                    CACHE["t"] = 0
                self.send(200, json.dumps(out, ensure_ascii=False).encode(), "application/json")
            elif p == "/api/annulla":
                import brain
                self.send(200, json.dumps(brain.annulla(str(body.get("id", "")))).encode(), "application/json")
            else:
                self.send(404, b"non trovato", "text/plain")
        except urllib.error.HTTPError as e:
            self.send(502, json.dumps({"errore": f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"}).encode(), "application/json")
        except Exception as e:
            self.send(502, json.dumps({"errore": f"{type(e).__name__}: {e}"}).encode(), "application/json")


if __name__ == "__main__":
    porta = int(os.environ.get("SF_PORT", "8788"))
    print(f"SalesForB Agent locale su http://127.0.0.1:{porta}", flush=True)
    sys.path.insert(0, HERE)

    def lavoro_di_fondo():
        time.sleep(5)
        while True:
            try:
                stato(force=True)
            except Exception:
                traceback.print_exc()
            time.sleep(120)
    def scalda_whisper():
        try:
            import voice_input, wake_input
            voice_input.prepara()
            wake_input.prepara()
            print("Whisper " + voice_input.NOME_MODELLO + " pronto (locale)", flush=True)
            import tts
            tts.prepara()
            print("Voce pronta: " + str(tts.MOTORE.get("nome")), flush=True)
        except Exception:
            traceback.print_exc()
    threading.Thread(target=scalda_whisper, daemon=True).start()
    threading.Thread(target=lavoro_di_fondo, daemon=True).start()
    try:
        import toro_plus
        if os.environ.get("SF_AUTOMATIONS", "1") == "1":
            toro_plus.avvia(lambda: CACHE.get("data"))
    except Exception:
        traceback.print_exc()
    ThreadingHTTPServer(("127.0.0.1", porta), H).serve_forever()
