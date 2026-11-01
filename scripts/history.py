"""Shared history helpers for MIDNIGHT HOUR."""
import json, os
D = os.path.join(os.path.dirname(__file__), '..', 'data')
H = os.path.join(D, 'brink_history.json')
def load():
    try: return json.load(open(H))
    except Exception: return {'points': [], 'events': []}
def save(h):
    h['points'] = sorted({p['date']: p for p in h['points']}.values(), key=lambda p: p['date'])[-400:]
    json.dump(h, open(H, 'w'), indent=0, ensure_ascii=False)
