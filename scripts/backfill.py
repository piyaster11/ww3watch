#!/usr/bin/env python3
"""One-off honest 30-day backfill -> data/brink_history.json (mode='reconstructed').
Live-type signals from real daily history (Yahoo closes, Polymarket CLOB price history).
Travel advisories: the State Dept feed is not dated per level change -> today's value carried (flagged).
Curated signals: data/curated_timeline.json change points, carried forward between documented dates."""
import json, os, sys, urllib.request
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(__file__))
import history
D = history.D
get = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30).read()
clamp = lambda x: max(1.0, min(10.0, x))
today = datetime.now(timezone.utc).date()
days = [(today - timedelta(days=i)) for i in range(30, 0, -1)]   # 30 days before today
cur = json.load(open(os.path.join(D, 'brink.json')))
W = {f['id']: f['weight'] for f in cur['factors']}
tl = json.load(open(os.path.join(D, 'curated_timeline.json')))
def carry(series, d):  # series: list of (date, value) ascending
    v = None
    for sd, sv in series:
        if sd <= d: v = sv
    return v if v is not None else series[0][1]
# fear: percentile of each day's close vs the prior 1y window
fear = {}
TICK = ['^VIX', 'GC=F', 'BZ=F', 'ITA']
closes = {}
for t in TICK:
    j = json.loads(get('https://query1.finance.yahoo.com/v8/finance/chart/%s?range=2y&interval=1d' % urllib.request.quote(t)))['chart']['result'][0]
    closes[t] = [(datetime.fromtimestamp(ts, timezone.utc).date(), c) for ts, c in zip(j['timestamp'], j['indicators']['quote'][0]['close']) if c]
def pct(t, d):
    s = [c for dd, c in closes[t] if dd <= d]; last = s[-1]; w = s[-252:]
    return sum(1 for x in w if x <= last) / len(w) * 100
# markets: Polymarket CLOB daily price history
from brink_markets import MARKETS
mk = []
for slug, label, inv in MARKETS:
    m = [x for x in json.loads(get('https://gamma-api.polymarket.com/events?slug=' + slug))[0]['markets'] if not x.get('closed')][0]
    tok = json.loads(m['clobTokenIds'])[0]
    hist = json.loads(get('https://clob.polymarket.com/prices-history?market=%s&startTs=%d&fidelity=1440' % (tok, int((datetime.now().timestamp()) - 40 * 86400))))['history']
    s = [(datetime.fromtimestamp(x['t'], timezone.utc).date(), (1 - x['p']) if inv else x['p']) for x in hist]
    mk.append(s)
adv = next(f['score'] for f in cur['factors'] if f['id'] == 'advisories')
h = history.load()
h['events'] = tl['events']
for d in days:
    ds = d.isoformat(); sc = {}
    for fid in ('greatpower', 'wars', 'nuclear', 'mobilization', 'chokepoints', 'doomsday'):
        sc[fid] = carry([(x[0], x[1]) for x in tl[fid]], ds)
    sc['advisories'] = adv
    sc['markets'] = round(clamp(1 + 9 * sum(carry(s, d) * 100 for s in mk) / 40), 1)
    sc['fear'] = round(clamp(1 + 9 * sum(pct(t, d) for t in TICK) / len(TICK) / 100), 1)
    tot = round(sum(sc[k] * W[k] for k in W) / sum(W.values()), 1)
    if any(p['date'] == ds and p['mode'] == 'live' for p in h['points']): continue
    h['points'].append({'date': ds, 'score': tot, 'mode': 'reconstructed', 'factors': sc,
                        'notes': 'advisories carried from ' + today.isoformat() + ' (feed undated)'})
history.save(h); print([(p['date'], p['score']) for p in h['points']])
