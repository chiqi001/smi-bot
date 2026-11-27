import smi_bot as b, time
b.TELEGRAM_TOKEN=""
for sym,name in [("CL=F","WTI"),("NQ=F","US100"),("ES=F","US500")]:
    raw=b.fetch_yahoo_raw(sym,"1h")
    b._delay=b.data_delay("yahoo",sym)
    bars=b.only_closed(raw,3600); smi=b.calc_smi(bars); ev,_=b.find_events(bars,smi)
    evd={}
    for i,k in ev: evd.setdefault(i,[]).append(k)
    print("==",name, "ostatni surowy punkt:", b.fmt_time(raw[-1]["t"]))
    for i,x in enumerate(bars):
        d=b.fmt_time(x['t'])
        if d>="2026-11-26 14": print(f"   {d} H {x['h']:.2f} L {x['l']:.2f} C {x['c']:.2f} SMI {smi[i]:7.2f} {evd.get(i,'')}")
