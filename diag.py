import smi_bot as b, sys
b.TELEGRAM_TOKEN=""
def show(label, bars):
    for iv in ["1h","4h"]:
        bb = bars if iv=="1h" else b.resample_4h(bars)
        smi=b.calc_smi(bb); ev,pos=b.find_events(bb,smi)
        print(f"== {label} {iv}: {len(bb)} świec, ost. close {bb[-1]['c']}, SMI {smi[-1]:.2f}, pozycja {pos}")
        for i,k in ev:
            d=b.fmt_time(bb[i]['t'])
            if d>="2026-11-17": print(f"   {d} {k:12} close {bb[i]['c']:.2f} SMI {smi[i]:.2f}")
        # przekroczenia -75/75 niezależnie od pozycji
        x=[(b.fmt_time(bb[i]['t']),round(smi[i],1)) for i in range(1,len(bb)) if smi[i] is not None and smi[i-1] is not None and b.fmt_time(bb[i]['t'])>="2026-11-17" and ((smi[i]<-75<=smi[i-1]) or (smi[i]>75>=smi[i-1]))]
        print("   przebicia ±75:", x)
for sym in ["XAUUSD=X","GC=F","ZW=F","ZC=F","CC=F"]:
    try:
        raw=b.fetch_yahoo_raw(sym,"1h"); show(sym, b.only_closed(raw,3600))
    except Exception as e: print(sym,"BŁĄD",e)
try:
    bars=[x for x in b.fetch_binance("PAXGUSDT","1h") if not b.is_weekend_ny(x["t"])]
    show("PAXGUSDT", bars)
except Exception as e: print("PAXG BŁĄD", e)
