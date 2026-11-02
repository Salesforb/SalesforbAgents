#!/usr/bin/env python3
"""Voce locale di SalesForB per i messaggi vocali del motore Hermes: testo -> WAV (via server locale)."""
import sys, urllib.parse, urllib.request

testo = open(sys.argv[1], encoding="utf-8").read()[:900]
url = "http://127.0.0.1:8788/api/voce?t=" + urllib.parse.quote(testo)
with urllib.request.urlopen(url, timeout=90) as r:
    open(sys.argv[2], "wb").write(r.read())
