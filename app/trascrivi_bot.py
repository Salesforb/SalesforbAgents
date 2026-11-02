#!/usr/bin/env python3
"""Condivide Whisper large-v3 dell'app SalesForB con i vocali Telegram."""
import argparse
import json
from pathlib import Path
import urllib.request

parser=argparse.ArgumentParser()
parser.add_argument('audio',type=Path)
args=parser.parse_args()
tipi={'.ogg':'audio/ogg','.oga':'audio/ogg','.opus':'audio/ogg','.mp3':'audio/mpeg',
      '.mp4':'audio/mp4','.m4a':'audio/mp4','.wav':'audio/wav','.webm':'audio/webm'}
req=urllib.request.Request('http://127.0.0.1:8788/api/trascrivi',data=args.audio.read_bytes(),
                           headers={'Content-Type':tipi.get(args.audio.suffix.lower(),'audio/ogg')},method='POST')
with urllib.request.urlopen(req,timeout=90) as response:
    out=json.load(response)
if out.get('errore'):raise SystemExit(out['errore'])
print(out.get('testo',''))
