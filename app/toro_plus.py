"""Superpoteri di SalesForB Agent: consiglio d'amministrazione, sentinella, CRM dei lead,
memoria del team, promemoria e report settimanale. Tutti i modelli passano dal login ChatGPT (llm.py)."""
import datetime as dt, json, os, re, threading, time, urllib.error, urllib.parse, urllib.request
import zoneinfo

import agents
import brain
import llm

TZ = zoneinfo.ZoneInfo("Europe/Rome")
from toro_paths import DATA_HOME
H = DATA_HOME
LOCK = threading.Lock()


def _j(nome, default):
    try:
        return json.load(open(os.path.join(H, nome)))
    except Exception:
        return default


def _salva(nome, dati):
    p = os.path.join(H, nome)
    with LOCK:
        json.dump(dati, open(p + ".tmp", "w"), ensure_ascii=False, indent=1, default=str)
        os.replace(p + ".tmp", p)


def env():
    return brain.env()


def ora():
    return dt.datetime.now(TZ)


# ====================================================================== LLM semplici
def claude(system, testo, modello=None, max_tokens=500):
    """(nome storico) Domanda semplice al modello ChatGPT."""
    return llm.chat(system, testo, max_tokens)


def chatgpt(system, testo, max_tokens=500):
    try:
        return llm.chat(system, testo, max_tokens)
    except Exception:
        return None, None


# ====================================================================== CONSIGLIO D'AMMINISTRAZIONE
CONSIGLIO = {"stato": "vuoto", "domanda": "", "messaggi": [], "verdetto": "", "dal": 0}
MEMBRI = [
    {"id": "cfo", "nome": "CFO", "colore": "#36d39a", "motore": "chatgpt",
     "ruolo": "Sei il CFO di SalesForB, agenzia italiana di agenti AI, automazioni e formazione AI per aziende. Guardi margini, cassa, prezzo dei progetti, ore del team, rischio. Sei prudente ma non ti opponi per principio: vuoi numeri."},
    {"id": "growth", "nome": "Growth", "colore": "#02C1FF", "motore": "chatgpt",
     "ruolo": "Sei il responsabile crescita di SalesForB. Vuoi più clienti B2B e contratti ricorrenti: cerchi l'opportunità, la velocità e l'effetto leva."},
    {"id": "diavolo", "nome": "Avvocato del diavolo", "colore": "#ff5d6c", "motore": "chatgpt",
     "ruolo": "Sei l'avvocato del diavolo nel consiglio di SalesForB: cerchi cosa può andare storto, le ipotesi deboli, i costi nascosti. Sei diretto."},
]

def _parla(membro, testo):
    sistema = membro["ruolo"] + " Rispondi in italiano, massimo 90 parole, niente elenchi lunghi, niente markdown. Inizia con la tua posizione: SÌ, NO o DIPENDE."
    return llm.chat(sistema, testo, strategico=True)


def consiglio(domanda, dati=None):
    """Tre agenti discutono in due giri, Toro decide. Restituisce il verdetto."""
    snap = brain._compatta(dati or {})[:4500]
    CONSIGLIO.update(stato="in corso", domanda=domanda, messaggi=[], verdetto="", dal=time.time())
    agents.inizia("ricerca", "Consiglio d'amministrazione: " + domanda[:60])
    base = f"Domanda del team SalesForB al consiglio: {domanda}\nDati attuali dei business (JSON): {snap}\n"

    def giro(n, prompt_fn):
        out, th = {}, []
        for mb in MEMBRI:
            def run(mb=mb):
                try:
                    out[mb["id"]] = _parla(mb, prompt_fn(mb))
                except Exception as e:
                    out[mb["id"]] = (f"(non disponibile: {str(e)[:60]})", "-")
            t = threading.Thread(target=run); t.start(); th.append(t)
        for t in th:
            t.join(120)
        for mb in MEMBRI:
            testo, modello = out.get(mb["id"], ("(nessuna risposta)", "-"))
            CONSIGLIO["messaggi"].append({"chi": mb["nome"], "id": mb["id"], "colore": mb["colore"], "giro": n, "testo": testo, "modello": modello})
        return out

    g1 = giro(1, lambda mb: base + "Primo giro: dai la tua posizione con i numeri che contano.")
    riass = "\n".join(f"{m['nome']}: {g1.get(m['id'], ('', ''))[0]}" for m in MEMBRI)
    giro(2, lambda mb: base + "Secondo giro. Ecco cosa hanno detto tutti:\n" + riass +
         f"\nTu sei {mb['nome']}: rispondi agli altri, puoi cambiare idea. Chiudi con la tua posizione finale.")
    tutto = "\n".join(f"[{m['chi']} · giro {m['giro']}] {m['testo']}" for m in CONSIGLIO["messaggi"])
    verdetto, _ = claude("Sei SALESFORB AGENT, il manager AI di SalesForB. Hai ascoltato il consiglio. Dai il verdetto finale in italiano, a voce, max 70 parole: "
                         "decisione chiara, perché, e la condizione o il numero da controllare. Niente markdown.",
                         base + "\nDiscussione:\n" + tutto, None, 350)
    CONSIGLIO.update(stato="concluso", verdetto=verdetto)
    agents.finisci("ricerca", "Consiglio concluso: " + verdetto[:70])
    ricorda(f"Consiglio su '{domanda[:80]}': {verdetto[:200]}", "decisioni", auto=True)
    return {"verdetto": verdetto, "posizioni": {m["chi"]: m["testo"][:200] for m in CONSIGLIO["messaggi"] if m["giro"] == 2}}


# ====================================================================== TELEFONO
def _log_chiamata(x):
    lst = _j("chiamate.json", [])
    lst.append(x)
    _salva("chiamate.json", lst[-50:])


def chiama(messaggio, contesto="", motivo="avviso"):
    """Telefonate disattivate in SalesForB Agent (niente ElevenLabs): l'avviso resta in dashboard e su Telegram."""
    evento("warn", messaggio[:200], "SalesForB · avviso")
    return {"ok": False, "errore": "Le telefonate non sono attive in SalesForB Agent: avviso mostrato in dashboard e su Telegram (se collegato)."}

def telegram(testo):
    e = env()
    tok = e.get("TELEGRAM_BOT_TOKEN")
    chat = e.get("TORO_TELEGRAM_CHAT") or (e.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip())
    if not tok or not chat:
        return False
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                               data=urllib.parse.urlencode({"chat_id": chat, "text": testo[:3900]}).encode()), timeout=20).read()
        return True
    except Exception:
        return False


# ====================================================================== PROMEMORIA (anche con chiamata)
def promemoria(testo, quando, chiamata=False):
    """quando: 'HH:MM' oggi (o domani se già passato), 'YYYY-MM-DD HH:MM', oppure '+30' minuti."""
    n = ora()
    q = str(quando).strip()
    try:
        if q.startswith("+"):
            t = n + dt.timedelta(minutes=int(q[1:]))
        elif re.match(r"^\d{1,2}[:.]\d{2}$", q):
            h, m = map(int, re.split(r"[:.]", q))
            t = n.replace(hour=h, minute=m, second=0, microsecond=0)
            if t <= n:
                t += dt.timedelta(days=1)
        else:
            t = dt.datetime.fromisoformat(q.replace("T", " ")).replace(tzinfo=TZ)
    except Exception:
        return {"errore": "Orario non valido: usa HH:MM, 'YYYY-MM-DD HH:MM' o +minuti."}
    lst = _j("promemoria.json", [])
    lst.append({"testo": testo[:300], "quando": t.isoformat(), "chiamata": bool(chiamata), "fatto": False})
    _salva("promemoria.json", lst[-100:])
    return {"ok": True, "quando": t.strftime("%d/%m %H:%M"), "chiamata": bool(chiamata)}


def _giro_promemoria():
    lst = _j("promemoria.json", [])
    cambiato = False
    for p in lst:
        if not p.get("fatto") and dt.datetime.fromisoformat(p["quando"]) <= ora():
            p["fatto"] = True; cambiato = True
            telegram("⏰ Promemoria SalesForB: " + p["testo"])
            evento("info", "Promemoria: " + p["testo"], "SalesForB · promemoria")
    if cambiato:
        _salva("promemoria.json", lst)


# ====================================================================== SENTINELLA
EVENTI = []          # avvisi recenti per la dashboard
STATO_SENT = {"ultimo": None, "controlli": 0, "allarmi": 0}
URGENTI_PEC = re.compile(r"agenzia\s+delle\s+entrate|riscossione|equitalia|tribunal|ingiunzion|pignorament|sollecito|diffida|sanzion|accertament|cartella|scadenz|inps|inail|camera di commercio|avviso di pagamento", re.I)
SCADENZE = re.compile(r"scadenz|f24|iva\b|tasse|rata|bollo|pagament|udienza|deadline|versament|dichiarazion|bilancio", re.I)


def evento(liv, testo, fonte):
    EVENTI.insert(0, {"liv": liv, "testo": testo, "fonte": fonte, "quando": ora().strftime("%H:%M")})
    del EVENTI[20:]


def _una_volta(chiave, ore=12):
    st = _j("sentinella.json", {})
    t = st.get(chiave)
    if t and time.time() - t < ore * 3600:
        return False
    st[chiave] = time.time()
    st = {k: v for k, v in st.items() if time.time() - v < 7 * 86400}
    _salva("sentinella.json", st)
    return True


def notte():
    h = ora().hour + ora().minute / 60
    return h >= 22.5 or h < 8


def allarme(chiave, testo, fonte, critico=False, contesto="", ore=12):
    """Avvisa una sola volta ogni N ore. Critico = chiamata (di notte solo Telegram, chiamata alle 8:30)."""
    if not _una_volta(chiave, ore):
        return
    STATO_SENT["allarmi"] += 1
    evento("crit" if critico else "warn", testo, fonte)
    telegram(("🚨 " if critico else "⚠️ ") + testo + f"\n— {fonte}")



def _giro_sentinella(dati):
    STATO_SENT["controlli"] += 1
    STATO_SENT["ultimo"] = ora().strftime("%H:%M")
    agents.nota("shop", "Sentinella: controllo sito e caselle")
    sito = env().get("SF_SITO", "")
    if sito:
        try:
            r = urllib.request.urlopen(urllib.request.Request(sito, headers={"User-Agent": "Mozilla/5.0 SalesForB-Sentinella"}), timeout=20)
            ok = r.status == 200
        except Exception:
            ok = False
        st = _j("sentinella.json", {})
        if not ok:
            st["_sito_ko"] = st.get("_sito_ko", 0) + 1; _salva("sentinella.json", st)
            if st["_sito_ko"] >= 2:
                allarme("sito_giu", "Il sito di SalesForB non risponde da almeno 20 minuti.", "SalesForB · sito", True, ore=3)
        elif st.get("_sito_ko"):
            st["_sito_ko"] = 0; _salva("sentinella.json", st)
    for acc, v in ((dati or {}).get("email") or {}).items():
        if isinstance(v, dict) and v.get("errore"):
            allarme("casella_" + acc, f"La casella {acc} non è raggiungibile: controlla la password per le app.", "SalesForB · email", False, ore=12)

def _giro_scadenze():
    """Alle 9: scadenze di oggi (chiamata) e di domani (Telegram), dai calendari."""
    if not brain._calendari():
        return
    ev = brain.agenda(2)
    if not isinstance(ev, list):
        return
    oggi, domani = ora().strftime("%d/%m"), (ora() + dt.timedelta(days=1)).strftime("%d/%m")
    s_oggi = [e for e in ev if e.get("giorno") == oggi and SCADENZE.search(e.get("titolo", ""))]
    s_dom = [e for e in ev if e.get("giorno") == domani and SCADENZE.search(e.get("titolo", ""))]
    if s_oggi:
        allarme("scad_" + oggi, "Oggi hai scadenze: " + "; ".join(f"{e['titolo']} ({e['ora']})" for e in s_oggi), "Agenda · scadenze", True, ore=20)
    if s_dom:
        allarme("scad_dom_" + domani, "Domani hai scadenze: " + "; ".join(e["titolo"] for e in s_dom), "Agenda · scadenze", False, ore=20)


# ====================================================================== CONTO ECONOMICO
COSTI_DEFAULT = {"iva_pct": 22, "commissione_pct": 2.9, "commissione_fissa": 0.25, "spedizione_per_ordine": 6.0, "costo_prodotto_pct_se_manca": 30}


def costi():
    c = dict(COSTI_DEFAULT)
    c.update(_j("costi.json", {}))
    return c


def imposta_costi(**k):
    c = _j("costi.json", {})
    for chiave, v in k.items():
        if chiave in COSTI_DEFAULT and v is not None:
            c[chiave] = float(v)
    _salva("costi.json", c)
    return {"ok": True, "costi": costi()}


Q_CONTO = """query($q:String!,$after:String){ orders(first:100, after:$after, query:$q){ edges{ node{ createdAt cancelledAt
  totalPriceSet{shopMoney{amount}} totalRefundedSet{shopMoney{amount}} totalShippingPriceSet{shopMoney{amount}}
  lineItems(first:30){ edges{ node{ quantity variant{ inventoryItem{ unitCost{ amount } } } originalUnitPriceSet{shopMoney{amount}} } } } } }
  pageInfo{ hasNextPage endCursor } } }"""


def conto_economico(giorni=7):
    giorni = max(1, min(int(giorni), 31))
    c = costi()
    inizio = (ora() - dt.timedelta(days=giorni)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows, after = [], None
    while True:
        d = brain.shopify_gql(Q_CONTO, {"q": f"created_at:>={inizio.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}", "after": after})["orders"]
        rows += [e["node"] for e in d["edges"]]
        if not d["pageInfo"]["hasNextPage"] or len(rows) > 600:
            break
        after = d["pageInfo"]["endCursor"]
    per = {}
    for i in range(giorni + 1):
        g = (inizio + dt.timedelta(days=i)).date()
        if g <= ora().date():
            per[g] = {"ordini": 0, "lordo": 0.0, "rimborsi": 0.0, "costo_prodotti": 0.0, "costi_stimati": False, "ads": 0.0}
    for o in rows:
        if o.get("cancelledAt"):
            continue
        g = dt.datetime.fromisoformat(o["createdAt"].replace("Z", "+00:00")).astimezone(TZ).date()
        if g not in per:
            continue
        x = per[g]
        x["ordini"] += 1
        x["lordo"] += float(o["totalPriceSet"]["shopMoney"]["amount"])
        x["rimborsi"] += float(o["totalRefundedSet"]["shopMoney"]["amount"])
        for e in o["lineItems"]["edges"]:
            n = e["node"]
            uc = ((n.get("variant") or {}).get("inventoryItem") or {}).get("unitCost")
            if uc and float(uc["amount"]) > 0:
                x["costo_prodotti"] += float(uc["amount"]) * n["quantity"]
            else:
                x["costi_stimati"] = True
                x["costo_prodotti"] += float(n["originalUnitPriceSet"]["shopMoney"]["amount"]) * n["quantity"] / (1 + c["iva_pct"] / 100) * c["costo_prodotto_pct_se_manca"] / 100
    if env().get("META_TOKEN"):
        d = brain.meta("GET", "{account}/insights", {"fields": "spend", "time_increment": 1,
                                                       "time_range": {"since": str(inizio.date()), "until": str(ora().date())}})
        for r in d.get("data") or []:
            g = dt.date.fromisoformat(r["date_start"])
            if g in per:
                per[g]["ads"] = float(r.get("spend") or 0)
    giorni_out = []
    for g in sorted(per):
        x = per[g]
        incassato = x["lordo"] - x["rimborsi"]
        netto_iva = incassato / (1 + c["iva_pct"] / 100)
        commissioni = incassato * c["commissione_pct"] / 100 + x["ordini"] * c["commissione_fissa"]
        spedizioni = x["ordini"] * c["spedizione_per_ordine"]
        utile = netto_iva - x["costo_prodotti"] - x["ads"] - commissioni - spedizioni
        giorni_out.append({"giorno": g.strftime("%d/%m"), "ordini": x["ordini"], "ricavi": round(incassato, 2), "ricavi_netti_iva": round(netto_iva, 2),
                           "costo_prodotti": round(x["costo_prodotti"], 2), "ads": round(x["ads"], 2), "commissioni": round(commissioni, 2),
                           "spedizioni": round(spedizioni, 2), "utile": round(utile, 2), "costi_stimati": x["costi_stimati"]})
    tot = {k: round(sum(d[k] for d in giorni_out), 2) for k in ("ordini", "ricavi", "ricavi_netti_iva", "costo_prodotti", "ads", "commissioni", "spedizioni", "utile")}
    tot["margine_pct"] = round(tot["utile"] / tot["ricavi_netti_iva"] * 100, 1) if tot["ricavi_netti_iva"] else 0
    ieri = next((d for d in giorni_out if d["giorno"] == (ora() - dt.timedelta(days=1)).strftime("%d/%m")), None)
    return {"periodo_giorni": giorni, "totale": tot, "ieri": ieri, "giorni": giorni_out, "meta_inclusa": bool(env().get("META_TOKEN")),
            "nota": "Stima: IVA, commissioni e spedizioni da impostazioni; costo prodotti da Shopify (o stimato se manca).",
            "impostazioni": c}


# ====================================================================== PREVISIONE SCORTE / RIORDINO
Q_VEND = """query($q:String!,$after:String){ orders(first:100, after:$after, query:$q){ edges{ node{ cancelledAt
  lineItems(first:30){ edges{ node{ quantity variant{ id } } } } } } pageInfo{ hasNextPage endCursor } } }"""
Q_VAR = """query($after:String){ productVariants(first:200, after:$after, query:"product_status:active"){ edges{ node{
  id displayName inventoryQuantity } } pageInfo{ hasNextPage endCursor } } }"""


def previsione_scorte(giorni_copertura=30):
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    vend, after = {}, None
    while True:
        d = brain.shopify_gql(Q_VEND, {"q": f"created_at:>={since}", "after": after})["orders"]
        for e in d["edges"]:
            if e["node"].get("cancelledAt"):
                continue
            for li in e["node"]["lineItems"]["edges"]:
                v = (li["node"].get("variant") or {}).get("id")
                if v:
                    vend[v] = vend.get(v, 0) + li["node"]["quantity"]
        if not d["pageInfo"]["hasNextPage"]:
            break
        after = d["pageInfo"]["endCursor"]
    out, after = [], None
    while True:
        d = brain.shopify_gql(Q_VAR, {"after": after})["productVariants"]
        for e in d["edges"]:
            n = e["node"]
            venduti = vend.get(n["id"], 0)
            if not venduti:
                continue
            al_giorno = venduti / 30
            qta = n["inventoryQuantity"] or 0
            giorni = round(qta / al_giorno, 1) if al_giorno else None
            da_ordinare = max(0, round(al_giorno * giorni_copertura - qta))
            out.append({"variante": n["displayName"], "venduti_30gg": venduti, "scorte": qta, "giorni_rimasti": giorni, "da_ordinare": da_ordinare})
        if not d["pageInfo"]["hasNextPage"]:
            break
        after = d["pageInfo"]["endCursor"]
    out.sort(key=lambda x: (x["giorni_rimasti"] if x["giorni_rimasti"] is not None else 999))
    return {"copertura_giorni": giorni_copertura, "varianti": out[:25],
            "nota": "Ritmo calcolato sugli ultimi 30 giorni. 'da_ordinare' copre i prossimi giorni_copertura."}


# ====================================================================== CRM SALESFORB (lead dell'agenzia)
STATI_LEAD = ["nuovo", "contattato", "call", "proposta", "vinto", "perso"]


def crm(azione="elenco", nome=None, email=None, azienda=None, stato=None, note=None, valore=None, followup_giorni=None):
    db = _j("crm.json", [])
    if azione == "elenco":
        attivi = [l for l in db if l.get("stato") not in ("vinto", "perso")]
        return {"lead": db[-40:], "attivi": len(attivi), "per_stato": {s: sum(1 for l in db if l.get("stato") == s) for s in STATI_LEAD},
                "valore_pipeline": sum(float(l.get("valore") or 0) for l in attivi)}
    chiave = (email or nome or "").lower().strip()
    if not chiave:
        return {"errore": "Serve almeno nome o email del lead."}
    lead = next((l for l in db if chiave in ((l.get("email") or "").lower(), (l.get("nome") or "").lower())), None)
    if not lead:
        lead = {"nome": nome or email, "email": email, "azienda": azienda, "stato": "nuovo", "creato": ora().strftime("%Y-%m-%d"), "storia": []}
        db.append(lead)
    for k, v in (("nome", nome), ("email", email), ("azienda", azienda), ("valore", valore)):
        if v:
            lead[k] = v
    if stato:
        if stato not in STATI_LEAD:
            return {"errore": "Stato non valido: " + ", ".join(STATI_LEAD)}
        lead["stato"] = stato
    if note:
        lead.setdefault("storia", []).append(f"{ora().strftime('%d/%m')} {note[:200]}")
    if followup_giorni is not None:
        lead["followup"] = (ora() + dt.timedelta(days=int(followup_giorni))).strftime("%Y-%m-%d")
    lead["aggiornato"] = ora().strftime("%Y-%m-%d")
    _salva("crm.json", db)
    return {"ok": True, "lead": lead}


def _giro_followup():
    oggi = ora().strftime("%Y-%m-%d")
    da_fare = [l for l in _j("crm.json", []) if l.get("followup") and l["followup"] <= oggi and l.get("stato") not in ("vinto", "perso")]
    if da_fare and _una_volta("followup_" + oggi, 20):
        nomi = ", ".join(f"{l.get('nome')} ({l.get('stato')})" for l in da_fare[:6])
        telegram(f"📇 Follow-up SalesForB di oggi: {nomi}. Di' 'scrivi i follow-up' e preparo le email.")
        evento("info", "Follow-up di oggi: " + nomi, "SalesForB · CRM")


# ====================================================================== MEMORIA LUNGA
def ricorda(testo, categoria="generale", auto=False):
    mem = _j("memoria.json", [])
    mem.append({"quando": ora().strftime("%Y-%m-%d"), "categoria": categoria, "testo": testo[:400], "auto": auto})
    _salva("memoria.json", mem[-400:])
    return {"ok": True}


def richiama(cerca=None, categoria=None):
    mem = _j("memoria.json", [])
    if categoria:
        mem = [m for m in mem if m.get("categoria") == categoria]
    if cerca:
        parole = [p for p in re.findall(r"\w{3,}", cerca.lower())]
        mem = sorted(mem, key=lambda m: -sum(p in m["testo"].lower() for p in parole))
        mem = [m for m in mem if any(p in m["testo"].lower() for p in parole)]
    return {"ricordi": mem[:25] if cerca else mem[-25:]}


def memoria_per_prompt():
    mem = [m for m in _j("memoria.json", []) if not m.get("auto")][-30:]
    return "\n".join(f"- ({m['quando']}, {m['categoria']}) {m['testo']}" for m in mem)


# ====================================================================== REPORT SETTIMANALE
def report_settimanale(invia=True):
    d = (_GET[0]() if _GET[0] else None) or {}
    sh = d.get("shopify") or {}
    righe = [f"📊 Report settimanale SalesForB · {ora().strftime('%d/%m')}"]
    if sh:
        righe.append(f"Shopify: {sh.get('ordini7', 0)} ordini, incassi € {sh.get('fatturato7', 0):.0f} negli ultimi 7 giorni")
    em = (d.get("email") or {}).get("salesforb") or {}
    if em and not em.get("errore"):
        righe.append(f"Email: {em.get('nonLette', 0)} non lette su info@salesforb.com")
    c = crm("elenco")
    righe.append(f"CRM: {c['attivi']} lead attivi, pipeline € {c['valore_pipeline']:.0f} · " + ", ".join(f"{k} {v}" for k, v in c["per_stato"].items() if v))
    testo = "\n".join(righe)
    try:
        mosse, _ = claude("Sei SALESFORB AGENT. Dai 3 mosse concrete per la settimana al team SalesForB, in italiano, numerate, max 60 parole totali.", testo, None, 300)
        testo += "\n\nLe 3 mosse:\n" + mosse
    except Exception:
        pass
    if invia:
        telegram(testo)
    return {"report": testo}

# ====================================================================== CICLO DI FONDO
_GET = [None]


def avvia(get_dati):
    _GET[0] = get_dati
    def ciclo():
        n = 0
        while True:
            try:
                _giro_promemoria()
                if n % 10 == 0:
                    _giro_sentinella(get_dati())
                h = ora()
                if h.hour == 9 and h.minute < 2:
                    _giro_scadenze(); _giro_followup()
                if h.weekday() == 0 and h.hour == 8 and 45 <= h.minute < 47 and _una_volta("report_" + h.strftime("%Y%m%d"), 20):
                    report_settimanale(True)
            except Exception as e:
                evento("warn", "Sentinella: " + str(e)[:100], "SalesForB")
            n += 1
            time.sleep(60)
    threading.Thread(target=ciclo, daemon=True).start()
