#!/usr/bin/env python3
"""BRINK — WW3 meter. Builds data/brink.json. Free sources only, no API keys, stdlib only.
Live: Polymarket gamma API (public), Yahoo Finance chart API, US State Dept advisory RSS.
Curated (analyst-reviewed, every claim linked): data/curated.json.
Fail-safe: any live source that fails keeps its previous value (marked stale)."""
import json, os, re, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
D = os.path.join(os.path.dirname(__file__), '..', 'data')
OUT = os.path.join(D, 'brink.json')
UA = {'User-Agent': 'Mozilla/5.0 (ww3brink)'}
NOW = datetime.now(timezone.utc)
def get(u, t=25):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t) as r: return r.read()
cur = json.load(open(os.path.join(D, 'curated.json')))
try: prev = json.load(open(OUT))
except Exception: prev = {}
pf = {f['id']: f for f in prev.get('factors', [])}
clamp = lambda x: max(1.0, min(10.0, x))
status = {}

# --- prediction markets: risk-event probabilities (YES = bad outcome unless inverted) ---
import sys; sys.path.insert(0, os.path.dirname(__file__))
from brink_markets import MARKETS
import history
def markets():
    out = []
    for slug, label, inv in MARKETS:
        e = json.loads(get('https://gamma-api.polymarket.com/events?slug=' + slug))[0]
        m = [x for x in e['markets'] if not x.get('closed')][0]
        yes = float(json.loads(m['outcomePrices'])[0])
        p = 1 - yes if inv else yes
        out.append({'label': label, 'p': round(p * 100, 1), 'link': 'https://polymarket.com/event/' + slug})
    tot = sum(x['p'] for x in out)
    # 0% combined -> 1, 40%+ combined -> 10
    return clamp(1 + 9 * tot / 40), out, 'Combined odds of %d major escalation events: %.1f%%' % (len(out), tot)

# --- market fear: percentile of today vs 1y for VIX, gold, Brent, defense ETF ---
TICK = [('^VIX', 'VIX fear index'), ('GC=F', 'Gold'), ('BZ=F', 'Brent oil'), ('ITA', 'US defense stocks (ITA)')]
def fear():
    rows, pcts = [], []
    for t, label in TICK:
        j = json.loads(get('https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1y&interval=1d' % urllib.request.quote(t)))
        c = [x for x in j['chart']['result'][0]['indicators']['quote'][0]['close'] if x]
        pct = sum(1 for x in c if x <= c[-1]) / len(c) * 100
        pcts.append(pct)
        rows.append({'label': label, 'v': round(c[-1], 2), 'pct': round(pct), 'link': 'https://finance.yahoo.com/quote/' + urllib.request.quote(t)})
    s = clamp(1 + 9 * sum(pcts) / len(pcts) / 100)
    return s, rows, 'Average 1-year percentile of fear assets: %d%%' % (sum(pcts) / len(pcts))

# --- advisories: Level 4 + ordered/authorized departures (US State Dept) ---
def advisories():
    root = ET.fromstring(get('https://travel.state.gov/_res/rss/TAsTWs.xml'))
    rows, seen = [], set()
    for it in root.iter('item'):
        title, link = it.findtext('title') or '', it.findtext('link') or ''
        if link in seen: continue
        seen.add(link)
        desc = it.findtext('description') or ''
        m = re.search(r'Level (\d)', title); lvl = int(m.group(1)) if m else 0
        dep = bool(re.search(r'(ordered|authorized) (the )?departure', desc, re.I))
        if lvl >= 4 or dep: rows.append({'label': title.split(' - ')[0].strip(), 'level': lvl, 'departure': dep, 'link': link})
    n4, nd = sum(1 for r in rows if r['level'] >= 4), sum(1 for r in rows if r['departure'])
    # ~18 Level-4 countries is the chronic baseline; departures weigh more
    s = clamp(2 + max(0, n4 - 18) * 0.35 + nd * 0.8)
    rows.sort(key=lambda r: (-r['departure'], r['label']))
    return s, rows, '%d Level-4 "Do Not Travel" countries, %d with ordered/authorized embassy departures' % (n4, nd)

SPEC = [  # id, name, weight, kind
 ('greatpower', 'Great-power confrontation', 0.22, 'curated'),
 ('wars', 'Active wars intensity', 0.14, 'curated'),
 ('nuclear', 'Nuclear posture & arms control', 0.15, 'curated'),
 ('mobilization', 'Military mobilization', 0.09, 'curated'),
 ('chokepoints', 'Airspace & sea-lane closures', 0.08, 'curated'),
 ('advisories', 'Embassy evacuations & travel bans', 0.07, advisories),
 ('markets', 'Prediction markets', 0.10, markets),
 ('fear', 'Market fear (VIX, gold, oil, defense)', 0.08, fear),
 ('doomsday', 'Doomsday Clock', 0.07, 'curated'),
]
factors = []
for fid, name, w, kind in SPEC:
    f = {'id': fid, 'name': name, 'weight': w}
    if kind == 'curated':
        c = cur['factors'][fid]
        f.update(score=c['score'], why=c['why'], sources=c['sources'], kind='curated', asof=cur['reviewed'])
    else:
        try:
            s, rows, why = kind()
            f.update(score=round(s, 1), why=why, rows=rows, kind='live', asof=NOW.strftime('%Y-%m-%dT%H:%M:%SZ'))
            status[name] = 'ok'
        except Exception as e:
            status[name] = 'failed: %s' % e
            old = pf.get(fid)
            if old: f.update({k: old[k] for k in old if k not in f}); f['stale'] = True
            else: f.update(score=5, why='Live source unavailable', rows=[], kind='live', stale=True)
    factors.append(f)
score = round(sum(f['score'] * f['weight'] for f in factors) / sum(f['weight'] for f in factors), 1)
BANDS = [(2.5, 'CALM'), (4.5, 'TENSE'), (6.5, 'ELEVATED'), (8.5, 'DANGER'), (11, 'BRINK')]
band = next(b for lim, b in BANDS if score < lim)
hist = prev.get('history', [])
day = NOW.strftime('%Y-%m-%d')
hist = [h for h in hist if h[0] != day][-89:] + [[day, score]]
json.dump({'updated': NOW.strftime('%Y-%m-%dT%H:%M:%SZ'), 'score': score, 'band': band, 'factors': factors,
           'changed': cur['changed'], 'watch': cur['watch'], 'speculation': cur['speculation'],
           'reviewed': cur['reviewed'], 'status': status, 'history': hist,
           'prev_score': prev.get('score')}, open(OUT, 'w'), indent=1, ensure_ascii=False)
print(score, band, status)

# --- append today's live point to data/brink_history.json (fail-safe) ---
try:
    h = history.load()
    h['points'] = [p for p in h['points'] if p['date'] != day] + [{'date': day, 'score': score, 'mode': 'live',
        'factors': {f['id']: f['score'] for f in factors}}]
    history.save(h)
except Exception as e:
    print('history append failed:', e)
