"""Reparti di SalesForB Agent: chi sono, quali strumenti usano e su cosa stanno lavorando adesso."""
import threading, time

REPARTI = [
    {"id": "sales", "nome": "Sales & Lead", "icona": "↗", "colore": "#02C1FF",
     "ruolo": "Lead dell'agenzia SalesForB: risposte, follow-up, call, proposte commerciali e CRM.",
     "strumenti": ["leggi_email", "leggi_email_testo", "proponi_email", "email_azione", "calendly_leggi", "agenda", "crm"], "servizi": ["email"]},
    {"id": "email", "nome": "Email & Clienti", "icona": "@", "colore": "#0A8BFF",
     "ruolo": "Legge, smista, archivia e risponde alle email di info@salesforb.com.",
     "strumenti": ["leggi_email", "leggi_email_testo", "proponi_email", "email_azione", "shopify_leggi", "crm"], "servizi": ["email"]},
    {"id": "shop", "nome": "Shopify SalesForB", "icona": "S", "colore": "#36d39a",
     "ruolo": "Ordini, clienti, prodotti, servizi e pacchetti sullo Shopify di SalesForB.",
     "strumenti": ["cerca_prodotti", "shopify_leggi", "shopify_azione", "proponi_stato_prodotto", "proponi_prezzo"], "servizi": ["shopify"]},
    {"id": "marketing", "nome": "Marketing & Promo", "icona": "%", "colore": "#ffb547",
     "ruolo": "Promozioni, codici sconto, campagne e idee per acquisire clienti.",
     "strumenti": ["proponi_sconto", "shopify_leggi", "shopify_azione", "crm"], "servizi": ["shopify"]},
    {"id": "contenuti", "nome": "Contenuti & Proposte", "icona": "✎", "colore": "#7aa8ff",
     "ruolo": "Proposte commerciali, post LinkedIn e Instagram, copy, descrizioni dei servizi.",
     "strumenti": ["shopify_leggi", "shopify_azione", "richiama"], "servizi": []},
    {"id": "ricerca", "nome": "Ricerca & Analisi", "icona": "?", "colore": "#5fd4ff",
     "ruolo": "Ricerche sul web, concorrenti, mercato AI e analisi approfondite.",
     "strumenti": ["analisi_approfondita", "consiglio", "richiama"], "servizi": []},
]
STATO = {r["id"]: {"stato": "pronto", "compito": "In attesa di istruzioni", "log": [], "dal": time.time(), "fatti": 0} for r in REPARTI}
LOCK = threading.Lock()
TOOL_REPARTO = {"consiglio": "ricerca", "crm": "sales", "ricorda": "ricerca", "richiama": "ricerca", "promemoria": "email",
                "report_settimanale": "marketing", "agenda": "sales", "calendly_leggi": "sales", "shopify_leggi": "shop", "shopify_azione": "shop",
                "cerca_prodotti": "shop", "proponi_stato_prodotto": "shop", "proponi_prezzo": "shop", "proponi_sconto": "marketing",
                "analisi_approfondita": "ricerca"}


def reparto_per_tool(tool, args=None):
    if tool in ("leggi_email", "leggi_email_testo", "proponi_email", "email_azione"):
        return "email"
    return TOOL_REPARTO.get(tool, "sales")


def _ora():
    return time.strftime("%H:%M:%S")


def inizia(rid, compito):
    with LOCK:
        s = STATO[rid]
        s.update(stato="lavora", compito=compito, dal=time.time())
        s["log"] = (s["log"] + [f"{_ora()} › {compito}"])[-14:]


def finisci(rid, esito, ok=True):
    with LOCK:
        s = STATO[rid]
        s["log"] = (s["log"] + [f"{_ora()} {'✓' if ok else '✕'} {esito}"])[-14:]
        s["fatti"] += 1
        s.update(stato="pronto" if ok else "errore", compito=esito, dal=time.time())


def nota(rid, testo):
    with LOCK:
        s = STATO[rid]
        s["log"] = (s["log"] + [f"{_ora()} · {testo}"])[-14:]


def elenco(collegamenti):
    out = []
    with LOCK:
        for r in REPARTI:
            s = dict(STATO[r["id"]])
            scollegato = any(not collegamenti.get(sv, True) for sv in r["servizi"])
            if scollegato and s["stato"] != "lavora":
                s["stato"], s["compito"] = "scollegato", "Da collegare: " + ", ".join(sv for sv in r["servizi"] if not collegamenti.get(sv, True))
            # dopo qualche secondo un lavoro finito torna "pronto"
            if s["stato"] == "pronto" and time.time() - s["dal"] > 90 and s["fatti"]:
                s["compito"] = "Pronto · " + str(s["fatti"]) + " lavori completati"
            out.append({**{k: r[k] for k in ("id", "nome", "icona", "colore", "ruolo", "strumenti")}, **s,
                        "secondi": int(time.time() - s["dal"])})
    return out
