"""Backup privato di SalesForB Agent, con copie SQLite consistenti ed esclusione dei runtime."""
from pathlib import Path
import datetime
import os
import sqlite3
import tarfile
import tempfile

base=Path.home()/'.salesforb'
folder=Path.home()/'Documents/SalesForB-Backup'
folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
target=folder/('salesforb-locale-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.tar.gz')
skip=('data/installs','data/tools','data/runtime','data/cache/pm','hermes-agent/.git','hermes-agent/.venv','hermes-agent/node_modules')
def filtro(info):
    name=info.name
    if any(name==p or name.startswith(p+'/') for p in skip):return None
    if name.endswith(('.db','.db-wal','.db-shm','.sock','.pid','.lock')):return None
    if info.isdev() or info.isfifo():return None
    return info
os.umask(0o077)
with tempfile.TemporaryDirectory(prefix='salesforb-backup-') as work,tarfile.open(target,'w:gz') as archive:
    for name in ('app','data','hermes-agent','apri.sh'):
        archive.add(base/name,arcname=name,filter=filtro)
    for source in (base/'data').glob('*.db'):
        snapshot=Path(work)/source.name
        with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as db,sqlite3.connect(snapshot) as dest:
            db.backup(dest)
        snapshot.chmod(0o600)
        archive.add(snapshot,arcname='data/'+source.name)
print('Backup locale completo salvato:',target.name)
