import smi_bot as b
def dump(label, bars, frm="2026-11-20 12", to="2026-11-20 23"):
    smi=b.calc_smi(bars)
    print("==",label)
    for i,x in enumerate(bars):
        d=b.fmt_time(x['t'])
        if frm<=d<=to: print(f"   {d} close {x['c']:.2f} SMI {smi[i]:.2f}")
for sym in ["NQ=F","^NDX"]:
    raw=b.only_closed(b.fetch_yahoo_raw(sym,"1h"),3600)
    dump(sym+" 1h", raw)
    dump(sym+" 4h NY17", b.resample_4h(raw), "2026-11-19 12")
    b.H4_ANCHOR_UTC=True; dump(sym+" 4h UTC", b.resample_4h(raw), "2026-11-19 12"); b.H4_ANCHOR_UTC=False
    b.H4_ANCHOR_NY_HOUR=18; dump(sym+" 4h NY18", b.resample_4h(raw), "2026-11-19 12"); b.H4_ANCHOR_NY_HOUR=17
