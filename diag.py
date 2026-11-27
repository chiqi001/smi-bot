import smi_bot as b, json, urllib.parse
from collections import Counter
for sym in ["CL=F","NQ=F"]:
    q=urllib.parse.urlencode({"interval":"60m","range":"10d"})
    d=b.http_get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?{q}")
    r=d["chart"]["result"][0]; ts=r["timestamp"]; qt=r["indicators"]["quote"][0]
    print("==",sym,"punktów",len(ts),"siatka", Counter(t%3600 for t in ts).most_common(4))
    for i,t in enumerate(ts):
        s=b.fmt_time(t)
        if s>="2026-11-25 20": print("  ",s, t%3600, qt["close"][i], b.is_weekend_ny(t))
