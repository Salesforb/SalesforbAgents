"""Percorsi privati dell'installazione locale di SalesForB Agent (separata da Toro)."""
import os

BASE = os.path.expanduser(os.environ.get('SALESFORB_HOME', '~/.salesforb'))
DATA_HOME = os.path.expanduser(os.environ.get('SALESFORB_DATA_HOME', os.path.join(BASE, 'data')))
SKILLS_HOME = os.path.join(DATA_HOME, 'skills')
ENV_FILE = os.path.join(DATA_HOME, '.env')
MODELS = os.path.join(BASE, 'models')
os.environ.setdefault('HERMES_HOME', DATA_HOME)
