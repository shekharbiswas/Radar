"""
⚡ Momentum Radar v2 — NSE Live
Streamlit Cloud edition:
  • Credentials from st.secrets
  • Original HTML table + tooltip (hover desktop / tap bottom-sheet mobile)
  • Auto-refresh via JS countdown + manual Streamlit button
  • Mobile-first responsive layout
"""

import streamlit as st
import pandas as pd
import datetime as dt
import math, time, json

# ══════════════════════════════════════════════════════
#  PAGE CONFIG  (must be first Streamlit call)
# ══════════════════════════════════════════════════════
st.set_page_config(
    page_title="⚡ Momentum Radar",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════
#  CREDENTIALS from st.secrets
# ══════════════════════════════════════════════════════
API_KEY      = st.secrets["API_KEY"]
CLIENT_ID    = st.secrets["CLIENT_ID"]
PASSWORD     = st.secrets["PASSWORD"]
TOTP_SECRET  = st.secrets["TOTP_SECRET"]

# ══════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════
REFRESH_SEC     = 10
BATCH_SIZE      = 50
WARMUP_TICKS    = 6
PRICE_BUCKET    = 0.5
GATE_VOL_RATIO  = 3.0
GATE_VOL_ABS    = 5000
GATE_ELEV_TICKS = 3
GATE_ROC        = 1.5
CANDLE_TICKS    = 6

# ══════════════════════════════════════════════════════
#  GLOBAL CSS
# ══════════════════════════════════════════════════════
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&display=swap');
  html, body, .stApp { background:#060608 !important; color:#d0d0d8 !important; font-family:'JetBrains Mono',monospace; }
  .stApp > header { background:#060608 !important; }
  div[data-testid="metric-container"] {
    background:linear-gradient(135deg,#0e0e14,#111118);
    border:1px solid #1e1e28; border-radius:10px; padding:12px 14px;
  }
  div[data-testid="metric-container"] label { color:#444 !important; font-size:10px !important; letter-spacing:1.5px; text-transform:uppercase; }
  div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color:#FFD700 !important; font-family:'JetBrains Mono',monospace !important; font-size:20px !important; }
  .stButton > button { background:#0e0e14 !important; color:#FFD700 !important; border:1px solid #2a2a3a !important; border-radius:8px !important; font-family:'JetBrains Mono',monospace !important; font-size:13px !important; }
  .stButton > button:hover { background:#1a1a2a !important; border-color:#FFD700 !important; }
  details { background:#0e0e14 !important; border:1px solid #1e1e28 !important; border-radius:8px !important; }
  hr { border-color:#1a1a24 !important; margin:8px 0 !important; }
  #MainMenu, footer, header { visibility:hidden; }
  .stDeployButton { display:none; }
  @media (max-width:768px) { section.main > div { padding:6px !important; } }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════
def fmt(v):
    if v >= 1e7: return f"{v/1e7:.1f}Cr"
    if v >= 1e5: return f"{v/1e5:.1f}L"
    if v >= 1e3: return f"{v/1e3:.0f}K"
    return str(int(v))

def mean_std(values):
    if len(values) < 2: return 0, 1
    m  = sum(values) / len(values)
    sd = math.sqrt(sum((x-m)**2 for x in values) / len(values))
    return m, max(sd, 1e-9)

def z_score(value, values):
    m, sd = mean_std(values)
    return (value - m) / sd

def bucket(price):
    return round(round(price / PRICE_BUCKET) * PRICE_BUCKET, 2)

def top_accum_zone(d, n=3):
    if not d: return []
    return sorted(d.items(), key=lambda x: x[1], reverse=True)[:n]

def vwap_calc(d):
    return d["vwap_num"] / d["vwap_den"] if d["vwap_den"] else 0

def strength_label(score):
    if score >= 20: return "🔥 EXTREME",  "#ff1744"
    if score >= 12: return "⚡ STRONG",   "#ff5252"
    if score >= 7:  return "📈 BUILDING", "#FFD700"
    if score >= 3:  return "🟢 EARLY",    "#69f0ae"
    if score >= 1:  return "🔵 WEAK",     "#4fc3f7"
    return               "— NONE",        "#555"

def score_bg(score):
    if score >= 20: return "linear-gradient(90deg,#1a0000,#120000)"
    if score >= 12: return "linear-gradient(90deg,#150a00,#0f0800)"
    if score >= 7:  return "linear-gradient(90deg,#0a1200,#080e00)"
    if score >= 3:  return "linear-gradient(90deg,#00101a,#000c14)"
    return "#09090f"

def momentum_roc(hist, cur):
    if len(hist) < 3: return 0.0
    avg = sum(hist[-3:]) / 3
    return cur / avg if avg >= 0.1 else 0.0

def two_candle_confirm(pl):
    n = CANDLE_TICKS
    if len(pl) < 2*n: return False, {}, {}
    prev = pl[-(2*n):-n]; curr = pl[-n:]
    po,pc,pl2 = prev[0],prev[-1],min(prev)
    co,cc2,cl = curr[0],curr[-1],min(curr)
    hl = cl>pl2; hc = cc2>pc
    ok = (pc>po) and (cc2>co) and hl and hc
    return ok, {"open":po,"close":pc,"low":pl2}, {"open":co,"close":cc2,"low":cl,"higher_low":hl,"higher_close":hc}

def candle_direction(pl, lookback=6):
    if len(pl) < 2: return 'doji',0,0,0.0
    o = pl[-min(lookback,len(pl))]; c = pl[-1]
    chg = (c-o)/o*100 if o else 0
    if c>o: return 'green',o,c,chg
    if c<o: return 'red',  o,c,chg
    return 'doji',o,c,chg

def all_up(pd_, n=3):
    r = pd_[-n:] if len(pd_)>=n else pd_
    return len(r)>=2 and all(p>0 for p in r)

def all_down(pd_, n=3):
    r = pd_[-n:] if len(pd_)>=n else pd_
    return len(r)>=2 and all(p<0 for p in r)

def compute_signal(score, pdelta, pl, zs, ratio, vgap, cc, sr, ah, ve):
    cd,co_,cc_,cp = candle_direction(pl, CANDLE_TICKS)
    tu = all_up(pdelta, 3)
    td = all_down(pdelta, 3)
    AS = score>=12 and cc and sr and ah
    if AS and tu and cd=='green': return "🟢 STRONG BUY",        "#00e676", cd,co_,cc_,cp
    if AS and cd=='green':        return "🔶 BUY? (mixed)",       "#ff9800", cd,co_,cc_,cp
    if AS and cd=='red':          return "🔴 DIST (red)",         "#ff1744", cd,co_,cc_,cp
    if score>=12 and cd=='green' and tu: return "🔷 WATCH ↑",    "#4fc3f7", cd,co_,cc_,cp
    if score>=12 and cd=='red':          return "🔴 DIST",        "#ff1744", cd,co_,cc_,cp
    if score>=7  and cd=='green' and tu: return "🔷 WATCH ↑",    "#4fc3f7", cd,co_,cc_,cp
    if td and zs>2:                      return "🔴 DIST",        "#ff5252", cd,co_,cc_,cp
    return                               "⬜ NEUTRAL",            "#444",    cd,co_,cc_,cp


# ══════════════════════════════════════════════════════
#  DATA STORE
# ══════════════════════════════════════════════════════
def new_store():
    return dict(
        cum=[], delta=[], price=[], price_delta=[], price_pct=[],
        open_price=None, day_open=None, day_high=None, day_low=None, prev_close=None,
        vwap_num=0.0, vwap_den=0.0, accum_zones={},
        surge_start=None, sustained=0, first_surge=None,
        total_hold_secs=0, prev_tick_surge=False,
        up_ticks=0, down_ticks=0, last_signal="—",
        z_spike_hist=[], score_hist=[], vwap_gap_hist=[],
        elevated_streak=0, gate_fail_reason="",
        trigger_time=None, trigger_price=None,
    )


# ══════════════════════════════════════════════════════
#  CACHED RESOURCES
# ══════════════════════════════════════════════════════
@st.cache_resource
def load_api():
    from SmartApi import SmartConnect
    from pyotp import TOTP
    obj  = SmartConnect(api_key=API_KEY)
    sess = obj.generateSession(CLIENT_ID, PASSWORD, TOTP(TOTP_SECRET).now())
    if not sess["status"]:
        st.error(f"Angel One login failed: {sess}")
        st.stop()
    return obj

@st.cache_data(ttl=86400)
def load_stocks():
    df = pd.read_csv("data/index.csv").dropna(subset=["token"])
    df["token"] = df["token"].astype(int).astype(str)
    return df

def init_state(symbols):
    if "store" not in st.session_state:
        st.session_state.store          = {s: new_store() for s in symbols}
        st.session_state.tick           = 0
        st.session_state.top3_freq      = {s: 0 for s in symbols}
        st.session_state.top3_last_rank = {s: 0 for s in symbols}
        st.session_state.hof_strength   = {s: {} for s in symbols}
        st.session_state.last_results   = []
        st.session_state.last_ts        = dt.datetime.now()


# ══════════════════════════════════════════════════════
#  FETCH
# ══════════════════════════════════════════════════════
def fetch_all(obj, batches, t2s):
    now = dt.datetime.now()
    S   = st.session_state.store
    for batch in batches:
        try:
            time.sleep(0.4)
            resp = obj.getMarketData(mode="FULL", exchangeTokens={"NSE": batch})
            if not (resp and resp.get("status")): continue
            for item in resp["data"].get("fetched", []):
                sym = t2s.get(str(item.get("symbolToken","")))
                if not sym: continue
                d   = S[sym]
                cum = item.get("tradeVolume", 0)
                ltp = item.get("ltp", 0)
                if ltp == 0: continue
                d["day_open"]   = item.get("open",  d["day_open"])
                d["day_high"]   = item.get("high",  d["day_high"])
                d["day_low"]    = item.get("low",   d["day_low"])
                d["prev_close"] = item.get("close", d["prev_close"])
                delta  = max(0, cum - d["cum"][-1]) if d["cum"] else 0
                pdelta = (ltp - d["price"][-1])     if d["price"] else 0.0
                ppct   = pdelta / d["price"][-1] * 100 if d["price"] else 0.0
                if d["open_price"] is None: d["open_price"] = ltp
                b = bucket(ltp)
                d["accum_zones"][b] = d["accum_zones"].get(b, 0) + delta
                d["vwap_num"] += ltp * delta
                d["vwap_den"] += delta
                if pdelta>0:   d["up_ticks"]+=1; d["down_ticks"]=0
                elif pdelta<0: d["down_ticks"]+=1; d["up_ticks"]=0
                for k, v in [("cum",cum),("delta",delta),("price",ltp),
                              ("price_delta",pdelta),("price_pct",ppct)]:
                    d[k].append(v); d[k] = d[k][-30:]
        except Exception as e:
            st.toast(f"Batch error: {e}", icon="⚠️")
    return now


# ══════════════════════════════════════════════════════
#  RANK / SCORE
# ══════════════════════════════════════════════════════
def _append_hist(d, z=0, score=0, vg=0):
    d["z_spike_hist"].append(z);  d["z_spike_hist"]  = d["z_spike_hist"][-10:]
    d["score_hist"].append(score);d["score_hist"]    = d["score_hist"][-10:]
    d["vwap_gap_hist"].append(vg);d["vwap_gap_hist"] = d["vwap_gap_hist"][-10:]

def rank_stocks(symbols):
    results = []
    now     = dt.datetime.now()
    S       = st.session_state.store

    for sym in symbols:
        d = S[sym]
        if len(d["delta"]) < WARMUP_TICKS+1 or not d["price"]: continue
        cv  = d["delta"][-1]; cp = d["price_pct"][-1]; ltp = d["price"][-1]
        bv  = d["delta"][:-3]    if len(d["delta"])    > 3 else d["delta"][:-1]
        bp  = d["price_pct"][:-3] if len(d["price_pct"]) > 3 else d["price_pct"][:-1]
        mv, _ = mean_std(bv)
        ratio  = cv / mv if mv > 0 else 0

        if ratio < GATE_VOL_RATIO:
            d["gate_fail_reason"] = f"G1 {ratio:.1f}×"; d["elevated_streak"] = 0
            _append_hist(d); continue
        if cv < GATE_VOL_ABS:
            d["gate_fail_reason"] = f"G2 {cv}"; d["elevated_streak"] = 0
            _append_hist(d); continue
        d["elevated_streak"] = d["elevated_streak"]+1 if ratio>=2.0 else 0
        if d["elevated_streak"] < GATE_ELEV_TICKS:
            d["gate_fail_reason"] = f"G3 streak {d['elevated_streak']}"; _append_hist(d); continue
        zs  = max(0, z_score(cv, bv))
        roc = momentum_roc(d["z_spike_hist"], zs)
        if len(d["z_spike_hist"]) >= 3 and roc < GATE_ROC:
            d["gate_fail_reason"] = f"G4 ROC {roc:.2f}"; _append_hist(d, z=zs); continue

        d["gate_fail_reason"] = ""
        if d["trigger_time"] is None:
            d["trigger_time"]  = now.strftime("%H:%M:%S")
            d["trigger_price"] = ltp

        w30     = [sum(d["delta"][i:i+3]) for i in range(len(d["delta"])-3)]
        a30     = sum(d["delta"][-3:])
        za      = max(0, z_score(a30, w30)) if len(w30) >= 3 else 0
        zp      = z_score(cp, bp) if len(bp) >= 3 else 0
        pm      = max(0.1, 1+zp*0.4)
        op      = d["open_price"] or ltp
        dc      = ((ltp-op)/op*100) if op else 0
        vv      = vwap_calc(d)
        vg      = ((ltp-vv)/vv*100) if vv > 0 else 0
        tz      = top_accum_zone(d["accum_zones"], 3)
        tzp     = tz[0][0] if tz else 0
        aa      = abs(ltp-tzp) <= PRICE_BUCKET*2
        ab      = 1.3 if aa else 1.0
        l3v     = d["delta"][-3:];       l3p = d["price_delta"][-3:]
        va      = (1.5 if len(l3v)==3 and l3v[0]<l3v[1]<l3v[2]
                   else 1.2 if len(l3v)>=2 and l3v[-2]<l3v[-1] else 1.0)
        pu      = all(x>0 for x in l3p[-2:]) if len(l3p)>=2 else False
        accel   = va * (1.2 if pu else 0.9)
        is_surge= zs>2 and cp>=0
        if is_surge:
            d["sustained"]+=1; d["total_hold_secs"]+=REFRESH_SEC
            if d["surge_start"] is None: d["surge_start"]=now
            if d["first_surge"] is None: d["first_surge"]=now
        else:
            if d["prev_tick_surge"] and d["sustained"]>=2:
                d["sustained"]+=1; d["total_hold_secs"]+=REFRESH_SEC
            else: d["sustained"]=0; d["surge_start"]=None
        d["prev_tick_surge"] = is_surge
        age = int((now-d["surge_start"]).total_seconds()) if d["surge_start"] else 0
        fr  = (0.5 if age==0 else 3.0 if age<=30 else 2.0 if age<=60
               else 1.3 if age<=120 else 1.0 if age<=300 else 0.7)
        fs  = zs*(1+za)*pm*accel*fr*ab
        cd_check,_,_,_ = candle_direction(d["price"], CANDLE_TICKS)
        if cd_check == 'red': fs = 0.0
        cc, pci, cci = two_candle_confirm(d["price"])
        sh   = d["score_hist"]
        sr   = (len(sh)>=2 and fs>sh[-1] and (len(sh)<3 or sh[-1]>=sh[-2]))
        rh   = max(d["price"][-10:]) if len(d["price"])>=10 else ltp
        ah   = ltp >= rh*0.999
        vgh  = d["vwap_gap_hist"]
        ve   = len(vgh)>=2 and vg>0 and vg>vgh[-1]
        _append_hist(d, z=zs, score=fs, vg=vg)
        sig,sc,cdir,co_,cc_,cpct = compute_signal(fs,d["price_delta"],d["price"],zs,ratio,vg,cc,sr,ah,ve)
        d["last_signal"] = sig
        tp_ = d["trigger_price"]
        tc_ = round((ltp-tp_)/tp_*100, 2) if tp_ else 0
        results.append(dict(
            sym=sym, score=fs, signal=sig, signal_color=sc,
            z_spike=zs, z_accum=za, ratio=ratio, cur_vol=cv, avg_vol=mv,
            cum_vol=d["cum"][-1] if d["cum"] else 0,
            roc=round(roc,2), elevated_streak=d["elevated_streak"],
            price=ltp, z_price=zp, price_pct=cp, day_chg=dc,
            vwap=vv, vwap_gap=vg, up_ticks=d["up_ticks"], down_ticks=d["down_ticks"],
            candle_dir=cdir, candle_open=co_, candle_close=cc_, candle_pct=round(cpct,3),
            candle_confirmed=cc,
            prev_c_open=pci.get("open",0),  prev_c_close=pci.get("close",0), prev_c_low=pci.get("low",0),
            curr_c_open=cci.get("open",0),  curr_c_close=cci.get("close",0), curr_c_low=cci.get("low",0),
            higher_low=cci.get("higher_low",False), higher_close=cci.get("higher_close",False),
            score_rising=sr, at_high=ah, vwap_expanding=ve,
            day_open=d["day_open"], day_high=d["day_high"], day_low=d["day_low"], prev_close=d["prev_close"],
            top_zones=tz, at_accum=aa, accum_bonus=ab,
            age=age, sustained=d["sustained"], total_hold=d["total_hold_secs"],
            first_seen=d["first_surge"].strftime("%H:%M:%S") if d["first_surge"] else "—",
            freshness=fr, accel=accel, price_multiplier=pm,
            trigger_time=d["trigger_time"], trigger_price=tp_, trigger_chg=tc_,
        ))
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ══════════════════════════════════════════════════════
#  INDICATOR CHECKS
# ══════════════════════════════════════════════════════
def indicator_checks(r):
    cd = r["candle_dir"]
    return [
        (f"G1 Vol ratio ≥ {GATE_VOL_RATIO}×", r["ratio"]>=GATE_VOL_RATIO,
         f"{r['ratio']:.1f}× session avg", "volume"),
        (f"G2 Abs vol ≥ {fmt(GATE_VOL_ABS)}/tick", r["cur_vol"]>=GATE_VOL_ABS,
         f"This tick: {fmt(r['cur_vol'])} shares", "volume"),
        (f"G3 Consecutive ≥ {GATE_ELEV_TICKS} elevated ticks", r["elevated_streak"]>=GATE_ELEV_TICKS,
         f"{r['elevated_streak']} ticks in a row", "volume"),
        (f"G4 Momentum ROC ≥ {GATE_ROC}×", r["roc"]>=GATE_ROC,
         f"ROC = {r['roc']:.2f}×", "volume"),
        ("S1a Current 60s candle GREEN", cd=='green',
         f"₹{r['candle_open']:.2f}→₹{r['candle_close']:.2f} ({r['candle_pct']:+.3f}%)", "price"),
        ("S1b Two green candles + higher low", r["candle_confirmed"],
         f"Prev ₹{r['prev_c_open']:.2f}→{r['prev_c_close']:.2f}  Curr ₹{r['curr_c_open']:.2f}→{r['curr_c_close']:.2f}  HL:{'✅' if r['higher_low'] else '❌'}", "price"),
        ("S2 Score rising 3 ticks", r["score_rising"],
         "↑ accelerating ✅" if r["score_rising"] else "→↓ flat/fading ❌", "price"),
        ("S3 Price at/near 10-tick high", r["at_high"],
         f"LTP ₹{r['price']:.2f} {'at breakout ✅' if r['at_high'] else 'below high ❌'}", "price"),
        ("S4 VWAP gap expanding", r["vwap_expanding"],
         f"Gap {r['vwap_gap']:+.3f}% vs VWAP ₹{r['vwap']:.2f}", "confluence"),
        ("High vol + GREEN candle", r["z_spike"]>2 and cd=='green',
         "✅ buyers absorbing" if r["z_spike"]>2 and cd=='green' else "❌ red candle = sellers", "confluence"),
        ("Price AT accumulation zone", r["at_accum"],
         f"Top zone ₹{r['top_zones'][0][0]:.1f}" if r["top_zones"] else "Building...", "confluence"),
        ("Volume accelerating", r["accel"]>1.1,
         f"Accel = {r['accel']:.2f}", "confluence"),
        ("Price above VWAP", r["vwap_gap"]>0,
         f"{r['vwap_gap']:+.3f}% vs VWAP", "confluence"),
    ]


# ══════════════════════════════════════════════════════
#  BUILD FULL HTML COMPONENT
# ══════════════════════════════════════════════════════
def build_html(results, ts, tick, hof, warming):

    # ── Table rows ──────────────────────────────────────
    rows_html = ""
    for rank, r in enumerate(results, 1):
        label, color = strength_label(r["score"])
        bg     = score_bg(r["score"])
        pc     = r["price_pct"]
        pc_col = "#69f0ae" if pc>0 else "#ff5252" if pc<0 else "#aaa"
        vg     = r["vwap_gap"]
        vg_col = "#69f0ae" if vg>0 else "#ff5252"
        exp    = '<span style="color:#69f0ae;font-size:9px"> EXP</span>' if r["vwap_expanding"] else ""
        roc_c  = "#00e676" if r["roc"]>=GATE_ROC else "#FFD700"
        gc     = "#00e676" if r["candle_confirmed"] else "#444"
        gbadge = "2C✅" if r["candle_confirmed"] else "1C"
        zones  = r["top_zones"]
        zs_    = " | ".join(f"₹{z[0]:.1f}({fmt(z[1])})" for z in zones[:2]) if zones else "—"
        zst    = "color:#FFD700;font-weight:bold" if r["at_accum"] else "color:#444"
        hs     = r["total_hold"]
        hstr   = f"{hs//60}m{hs%60}s" if hs>=60 else f"{hs}s" if hs>0 else "—"
        hc     = ("#ff1744" if hs>=300 else "#ff5252" if hs>=120 else "#FFD700" if hs>=60 else "#69f0ae" if hs>0 else "#333")
        astr   = f"{r['age']}s" if r["age"]>0 else "—"
        trig   = r["trigger_time"]
        tp_    = r["trigger_price"]
        tc_    = r["trigger_chg"]
        if trig:
            tcc = "#69f0ae" if tc_>0 else "#ff5252" if tc_<0 else "#aaa"
            tar = "▲" if tc_>0 else "▼" if tc_<0 else ""
            trig_td = (f'<span style="color:#888;font-size:10px">{trig}</span>'
                       f'<br><span style="color:#aaa;font-size:10px">₹{tp_:,.2f}</span> '
                       f'<span style="color:{tcc};font-size:10px">{tar}{abs(tc_):.2f}%</span>')
        else:
            trig_td = '<span style="color:#333">—</span>'

        checks = indicator_checks(r)
        passed = sum(1 for c in checks if c[1])
        tip_data = dict(
            sym=r["sym"], score=round(r["score"],2), signal=r["signal"], sig_color=r["signal_color"],
            price=r["price"], day_chg=round(r["day_chg"],3),
            z_spike=round(r["z_spike"],2), z_accum=round(r["z_accum"],2), z_price=round(r["z_price"],2),
            ratio=round(r["ratio"],1), cur_vol=fmt(r["cur_vol"]), avg_vol=fmt(int(r["avg_vol"])),
            cum_vol=fmt(r["cum_vol"]), roc=r["roc"], elevated_streak=r["elevated_streak"],
            vwap=round(r["vwap"],2), vwap_gap=round(r["vwap_gap"],3),
            up_ticks=r["up_ticks"], down_ticks=r["down_ticks"], price_pct=round(r["price_pct"],4),
            candle_dir=r["candle_dir"], candle_open=round(r["candle_open"],2),
            candle_close=round(r["candle_close"],2), candle_pct=r["candle_pct"],
            candle_confirmed=r["candle_confirmed"],
            prev_c_open=round(r["prev_c_open"],2), prev_c_close=round(r["prev_c_close"],2),
            prev_c_low=round(r["prev_c_low"],2),
            curr_c_open=round(r["curr_c_open"],2), curr_c_close=round(r["curr_c_close"],2),
            curr_c_low=round(r["curr_c_low"],2),
            higher_low=r["higher_low"], higher_close=r["higher_close"],
            score_rising=r["score_rising"], at_high=r["at_high"], vwap_expanding=r["vwap_expanding"],
            at_accum=r["at_accum"], top_zones=[[z[0], fmt(z[1])] for z in r["top_zones"]],
            sustained=r["sustained"], total_hold=r["total_hold"],
            first_seen=r["first_seen"], age=r["age"],
            accel=round(r["accel"],2), freshness=round(r["freshness"],1),
            price_multiplier=round(r["price_multiplier"],2),
            day_open=r["day_open"], day_high=r["day_high"],
            day_low=r["day_low"], prev_close=r["prev_close"],
            passed=passed, total_chk=len(checks),
            checks=[{"label":c[0],"pass":c[1],"detail":c[2],"cat":c[3]} for c in checks],
            trigger_time=trig or "—", trigger_price=tp_ or 0, trigger_chg=tc_,
        )
        tj = json.dumps(tip_data).replace('"', '&quot;')

        rows_html += f"""
        <tr data-tip='{tj}'
            style="background:{bg};border-bottom:1px solid #141420;cursor:pointer"
            onmouseenter="showTip(this)" onmouseleave="hideTip()">
          <td style="color:#333;padding:7px 6px;width:28px">{rank}</td>
          <td style="padding:7px 8px">
            <span style="color:{color};font-weight:700;font-size:14px">{r['sym']}</span>
            <span style="color:{gc};font-size:9px;margin-left:3px">{gbadge}</span>
          </td>
          <td style="padding:7px 8px">
            <span style="color:{r['signal_color']};font-weight:700;font-size:12px">{r['signal']}</span>
          </td>
          <td style="padding:7px 8px">
            <span style="color:{color};font-weight:700">{r['score']:.1f}</span>
            <span style="color:#333;font-size:9px"> {label}</span>
          </td>
          <td style="padding:7px 8px">
            <span style="color:#fff;font-weight:700">₹{r['price']:,.2f}</span>
            <br><span style="color:{pc_col};font-size:10px">{"▲" if pc>0 else "▼" if pc<0 else ""}{abs(pc):.3f}%</span>
          </td>
          <td style="padding:6px 8px;line-height:1.6">{trig_td}</td>
          <td style="padding:7px 8px">
            <span style="color:{vg_col}">{"▲" if vg>0 else "▼"}{abs(vg):.2f}%</span>{exp}
          </td>
          <td style="color:{color};font-weight:700;padding:7px 8px">{r['z_spike']:.1f}σ</td>
          <td style="padding:7px 8px">
            <span style="color:#FFD700">{r['ratio']:.1f}×</span>
            <br><span style="color:{roc_c};font-size:10px">ROC:{r['roc']:.1f}</span>
          </td>
          <td style="padding:7px 8px">
            <span style="{zst};font-size:11px">{zs_}</span>
          </td>
          <td style="padding:7px 8px;color:{hc};font-size:11px">{hstr}</td>
          <td style="color:#ff9800;padding:7px 8px">{astr}</td>
        </tr>"""

    # ── HOF cards ───────────────────────────────────────
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣"]
    hof_cards = ""
    if hof:
        for i, (sym, cnt) in enumerate(hof[:5]):
            is_live = st.session_state.top3_last_rank.get(sym, 0) > 0
            st_info = st.session_state.hof_strength.get(sym, {})
            sc_     = st_info.get("score", 0)
            cdir_   = st_info.get("candle_dir", "doji")
            cicon   = "🟩" if cdir_=="green" else "🟥" if cdir_=="red" else "🟨"
            _, scol = strength_label(sc_)
            bc      = "#00e676" if is_live else "#1e1e2e"
            hof_cards += (
                f'<div style="background:#0e0e18;border:1px solid {bc};border-radius:8px;'
                f'padding:8px 12px;min-width:100px;flex-shrink:0;text-align:center;'
                f'{"box-shadow:0 0 8px #00e67644;" if is_live else ""}">'
                f'<div style="color:#444;font-size:10px">{medals[i]}</div>'
                f'<div style="color:{"#00e676" if is_live else "#FFD700"};font-weight:700;font-size:13px">{sym} {cicon}</div>'
                f'<div style="color:{scol};font-size:10px">{sc_:.1f}</div>'
                f'<div style="color:#444;font-size:10px">{cnt}×</div>'
                f'</div>'
            )
    hof_strip = (
        f'<div style="display:flex;gap:8px;overflow-x:auto;padding-bottom:4px;margin-bottom:10px">{hof_cards}</div>'
        if hof_cards else
        '<div style="color:#333;font-size:11px;padding:6px 0 10px">🏆 Hall of Fame — building after warmup...</div>'
    )

    # ── Strong buy alert ────────────────────────────────
    sb_items = [r for r in results if "STRONG BUY" in r["signal"]]
    sb_html  = ""
    if sb_items:
        inner = "  ".join(
            f'<b style="color:#fff">{r["sym"]}</b> '
            f'<span style="color:#aaa">₹{r["price"]:,.2f}</span> '
            f'<span style="color:#69f0ae">{r["trigger_chg"]:+.2f}%</span>'
            for r in sb_items
        )
        sb_html = (
            f'<div style="background:#001a0a;border:1px solid #00e67644;border-radius:8px;'
            f'padding:10px 14px;margin-bottom:10px;font-size:12px">'
            f'🚨 <b style="color:#00e676">STRONG BUY:</b> {inner}</div>'
        )

    strong_buy_json = json.dumps([r["sym"] for r in results if "STRONG BUY" in r["signal"]])

    # ── Gate badges ────────────────────────────────────
    status_color = "#ff9800" if warming else "#00e676"
    status_text  = f"⏳ WARMING {tick}/{WARMUP_TICKS}" if warming else f"🟢 LIVE tick#{tick}"

    return f"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<style>
* {{ box-sizing:border-box;margin:0;padding:0 }}
body {{ background:#060608;font-family:'JetBrains Mono','Courier New',monospace;color:#d0d0d8;font-size:12px }}

/* Desktop tooltip */
#tip {{ display:none;position:fixed;z-index:9999;background:#0c0c14;
        border:1px solid #252535;border-radius:12px;padding:18px;
        width:450px;font-size:12px;line-height:1.7;pointer-events:none;
        box-shadow:0 12px 48px rgba(0,0,0,.95);max-height:90vh;overflow-y:auto }}

/* Mobile bottom sheet */
#overlay {{ display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:8000 }}
#sheet {{
  display:none;position:fixed;bottom:0;left:0;right:0;z-index:8001;
  background:#0c0c14;border-top:2px solid #252535;
  border-radius:16px 16px 0 0;padding:16px;
  max-height:88vh;overflow-y:auto;
  animation:up .25s ease-out
}}
@keyframes up {{ from{{transform:translateY(100%)}} to{{transform:translateY(0)}} }}
#sheet-hdr {{
  position:sticky;top:0;background:#0c0c14;
  display:flex;justify-content:space-between;align-items:center;
  padding-bottom:10px;margin-bottom:4px;border-bottom:1px solid #1a1a2a;z-index:2
}}

/* Table */
.tbl-wrap {{ width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;margin-bottom:4px }}
table {{ border-collapse:collapse;min-width:760px;width:100% }}
thead th {{
  background:#0b0b12;color:#FFD700;padding:8px 8px;text-align:left;
  border-bottom:2px solid #1e1e2e;font-size:10px;letter-spacing:.5px;
  position:sticky;top:0;z-index:10;white-space:nowrap
}}
tr:hover {{ filter:brightness(1.6) }}
td {{ white-space:nowrap }}

/* Shared detail content */
.tip-cards {{ display:flex;gap:8px;margin-bottom:10px }}
.tip-card  {{ background:#111120;border-radius:6px;padding:8px 10px;flex:1;text-align:center }}
.tc-lbl {{ color:#444;font-size:9px;letter-spacing:.5px }}
.tc-val {{ font-size:14px;font-weight:700 }}
.tc-sub {{ font-size:10px;color:#666;margin-top:1px }}
.chk-row {{ display:flex;align-items:flex-start;gap:8px;padding:5px 0;border-bottom:1px solid #141420 }}
.cat-hdr {{ font-size:9px;letter-spacing:1.2px;margin-top:10px;margin-bottom:4px }}
.t2grid  {{ display:flex;gap:6px;margin-bottom:10px }}
.t2cell  {{ background:#111120;border-radius:4px;padding:5px 7px;flex:1;text-align:center }}

/* Gate pills */
.gates {{ display:flex;gap:5px;flex-wrap:wrap;padding:6px 0 8px }}
.gate  {{ padding:3px 7px;border-radius:4px;font-size:10px;font-weight:700 }}

@media (max-width:600px) {{
  #tip {{ display:none !important }}
  .tc-val {{ font-size:13px }}
  thead th {{ font-size:9px;padding:6px 5px }}
}}
</style>
</head><body>

<div id="tip"></div>
<div id="overlay" onclick="closeSheet()"></div>
<div id="sheet">
  <div id="sheet-hdr">
    <span id="sheet-sym" style="color:#FFD700;font-size:15px;font-weight:700"></span>
    <button onclick="closeSheet()"
      style="background:#1a1a2a;color:#aaa;border:1px solid #333;
             border-radius:6px;padding:5px 14px;cursor:pointer;font-size:13px;
             -webkit-tap-highlight-color:transparent">✕ Close</button>
  </div>
  <div id="sheet-body"></div>
</div>

<!-- Status bar -->
<div style="display:flex;align-items:center;gap:10px;padding:6px 2px 6px;flex-wrap:wrap;border-bottom:1px solid #141420;margin-bottom:6px">
  <span style="color:{status_color};font-weight:700;font-size:12px">{status_text}</span>
  <span style="color:#444">{ts.strftime('%H:%M:%S')}</span>
  <span style="color:#333">|</span>
  <span style="color:#555">{len(results)} stocks passed</span>
  <span style="color:#333;margin-left:auto;font-size:10px;font-style:italic">tap row for details</span>
</div>

<!-- Gate legend -->
<div class="gates">
  <span class="gate" style="background:#1a1a24;color:#FFD700">HARD GATES:</span>
  <span class="gate" style="background:#001a0a;color:#69f0ae">G1 Vol≥{GATE_VOL_RATIO}×</span>
  <span class="gate" style="background:#001a0a;color:#69f0ae">G2 Abs≥{fmt(GATE_VOL_ABS)}</span>
  <span class="gate" style="background:#001a0a;color:#69f0ae">G3 Streak≥{GATE_ELEV_TICKS}</span>
  <span class="gate" style="background:#001a0a;color:#69f0ae">G4 ROC≥{GATE_ROC}×</span>
  <span class="gate" style="background:#1a1a24;color:#4fc3f7;margin-left:4px">STRONG BUY+:</span>
  <span class="gate" style="background:#00101a;color:#4fc3f7">S1 2C-HL</span>
  <span class="gate" style="background:#00101a;color:#4fc3f7">S2 Score↑</span>
  <span class="gate" style="background:#00101a;color:#4fc3f7">S3 @High</span>
  <span class="gate" style="background:#00101a;color:#4fc3f7">S4 VWAP↑</span>
</div>

<!-- HOF -->
{hof_strip}

<!-- Strong buy alert -->
{sb_html}

<!-- Main table -->
<div class="tbl-wrap">
<table>
  <thead><tr>
    <th>#</th><th>SYMBOL</th><th>SIGNAL</th><th>SCORE</th>
    <th>PRICE/Δ%</th><th title="Time + price when all 4 gates first passed">TRIGGERED</th>
    <th>vsVWAP</th><th>Z-VOL</th><th>RATIO/ROC</th>
    <th>ACCUM ZONE</th><th>HOLD</th><th>AGE</th>
  </tr></thead>
  <tbody>{rows_html}</tbody>
</table>
</div>

<!-- Legend -->
<div style="color:#333;font-size:10px;border-top:1px solid #141420;padding:6px 0;line-height:1.8;margin-top:4px">
  🟢 STRONG BUY = all gates + S1–S4 &nbsp;|&nbsp; 🔷 WATCH = gates pass, tier-2 partial &nbsp;|&nbsp; 🔴 DIST = high vol + red candle<br>
  TRIGGERED = time &amp; price when stock first passed all 4 hard gates · % move since
</div>

<!-- Countdown -->
<div style="color:#333;font-size:10px;text-align:right;padding:5px 0">
  Refreshing in <span id="ct">{REFRESH_SEC}</span>s
</div>

<script>
const isMobile = () => window.innerWidth <= 640 || ('ontouchstart' in window);
const CAT_COLOR = {{price:'#4fc3f7',volume:'#FFD700',confluence:'#cf6cc9'}};
const CAT_LABEL = {{price:'📈 PRICE / CANDLE',volume:'📊 VOLUME / GATES',confluence:'🔗 CONFLUENCE'}};

function buildDetail(d) {{
  const sp = Math.min(100,(d.score/25)*100).toFixed(0);
  const cats = {{price:[],volume:[],confluence:[]}};
  d.checks.forEach(c => cats[c.cat].push(c));
  const renderCat = key => {{
    const items = cats[key]; if(!items.length) return '';
    return `<div class="cat-hdr" style="color:${{CAT_COLOR[key]}}">${{CAT_LABEL[key]}}</div>`
      + items.map(c => `<div class="chk-row">
          <span style="font-size:13px">${{c.pass?'✅':'❌'}}</span>
          <div>
            <div style="color:${{c.pass?'#ddd':'#444'}};font-size:12px;font-weight:700">${{c.label}}</div>
            <div style="color:${{c.pass?'#777':'#333'}};font-size:11px">${{c.detail}}</div>
          </div></div>`).join('');
  }};

  const cc = d.candle_confirmed;
  const twoC = `<div style="background:#0a0a12;border:1px solid ${{cc?'#00e676':'#333'}}44;border-radius:6px;padding:8px;margin-bottom:10px">
    <div style="color:#444;font-size:10px;margin-bottom:6px">TWO-CANDLE (S1) ${{cc?'✅ CONFIRMED':'❌ NOT CONFIRMED'}}</div>
    <div style="display:flex;gap:8px">
      <div class="tip-card"><div class="tc-lbl">PREV</div>
        <div class="tc-val" style="color:${{d.prev_c_close>d.prev_c_open?'#00e676':'#ff5252'}};font-size:12px">${{d.prev_c_close>d.prev_c_open?'🟩':'🟥'}}</div>
        <div class="tc-sub">₹${{d.prev_c_open}}→₹${{d.prev_c_close}}</div></div>
      <div class="tip-card"><div class="tc-lbl">CURR</div>
        <div class="tc-val" style="color:${{d.curr_c_close>d.curr_c_open?'#00e676':'#ff5252'}};font-size:12px">${{d.curr_c_close>d.curr_c_open?'🟩':'🟥'}}</div>
        <div class="tc-sub">₹${{d.curr_c_open}}→₹${{d.curr_c_close}}</div></div>
      <div class="tip-card"><div class="tc-lbl">STRUCT</div>
        <div class="tc-val" style="font-size:11px;color:${{d.higher_low?'#00e676':'#ff5252'}}">${{d.higher_low?'↗HL✅':'↘LL❌'}}</div>
        <div class="tc-sub" style="color:${{d.higher_close?'#00e676':'#ff5252'}}">${{d.higher_close?'↗HC✅':'↘LC❌'}}</div>
      </div></div></div>`;

  const t2 = [['S1 2C-HL',d.candle_confirmed],['S2 Score↑',d.score_rising],['S3 High',d.at_high],['S4 VWAP↑',d.vwap_expanding]];
  const t2html = '<div class="t2grid">' + t2.map(([l,ok])=>
    `<div class="t2cell">
      <div style="color:${{ok?'#00e676':'#555'}};font-size:12px">${{ok?'✅':'❌'}}</div>
      <div style="color:#555;font-size:9px;margin-top:2px">${{l}}</div></div>`).join('') + '</div>';

  const volOk=d.z_spike>2&&d.ratio>={GATE_VOL_RATIO};
  const allS=d.score>=12&&d.candle_confirmed&&d.score_rising&&d.at_high;
  let verdict='';
  if(allS&&volOk&&d.candle_dir==='green')
    verdict=`<div style="background:#001a0a;border:1px solid #00e676;border-radius:6px;padding:8px 10px;color:#00e676;font-size:12px;margin-bottom:10px">✅ <b>STRONG BUY — ALL GATES CONFIRMED</b></div>`;
  else if(volOk&&d.candle_dir==='red')
    verdict=`<div style="background:#1a0000;border:1px solid #ff1744;border-radius:6px;padding:8px 10px;color:#ff5252;font-size:12px;margin-bottom:10px">⚠️ <b>HIGH VOL + RED CANDLE = SELLING PRESSURE</b></div>`;
  else if(!d.candle_confirmed)
    verdict=`<div style="background:#0d100a;border:1px solid #4fc3f7;border-radius:6px;padding:8px 10px;color:#4fc3f7;font-size:12px;margin-bottom:10px">🔷 <b>WATCH — Waiting for 2-candle confirmation (S1)</b></div>`;
  else if(!d.score_rising)
    verdict=`<div style="background:#0d100a;border:1px solid #ff9800;border-radius:6px;padding:8px 10px;color:#ff9800;font-size:12px;margin-bottom:10px">🔶 <b>WATCH — Score not rising (S2 fail)</b></div>`;
  else
    verdict=`<div style="background:#111;border:1px solid #222;border-radius:6px;padding:8px 10px;color:#444;font-size:12px;margin-bottom:10px">Some conditions unmet — see checks below.</div>`;

  const tca=d.trigger_chg>0?'#69f0ae':d.trigger_chg<0?'#ff5252':'#aaa';
  const tar=d.trigger_chg>0?'▲':d.trigger_chg<0?'▼':'';
  const trigB = d.trigger_time!=='—'
    ?`<div style="background:#0a0a12;border:1px solid #1e3a1e;border-radius:6px;padding:8px 12px;margin-bottom:10px;display:flex;gap:14px;align-items:center;flex-wrap:wrap">
        <div><div style="color:#444;font-size:9px">🎯 TRIGGERED</div><div style="color:#aaa;font-size:14px;font-weight:700">${{d.trigger_time}}</div></div>
        <div><div style="color:#444;font-size:9px">AT PRICE</div><div style="color:#fff;font-size:14px;font-weight:700">₹${{Number(d.trigger_price).toLocaleString('en-IN')}}</div></div>
        <div><div style="color:#444;font-size:9px">MOVE SINCE</div><div style="color:${{tca}};font-size:14px;font-weight:700">${{tar}}${{Math.abs(d.trigger_chg).toFixed(2)}}%</div></div>
      </div>`:'';

  const zones=d.top_zones.map((z,i)=>{{
    const col=(i===0&&d.at_accum)?'#FFD700':'#555';
    const star=(i===0&&d.at_accum)?'⭐':'#'+(i+1);
    return `<span style="color:${{col}};margin-right:10px">${{star}} ₹${{z[0]}} (${{z[1]}})</span>`;
  }}).join('');

  const pC=v=>v>0?'#69f0ae':v<0?'#ff5252':'#aaa';
  const zC=v=>v>=5?'#ff1744':v>=2?'#FFD700':'#69f0ae';

  return `
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">
      <h3 style="color:#FFD700;font-size:16px">${{d.sym}}</h3>
      <span style="color:${{d.sig_color}};font-size:13px;font-weight:700">${{d.signal}}</span>
    </div>
    ${{verdict}}${{trigB}}${{t2html}}${{twoC}}
    <div class="tip-cards">
      <div class="tip-card"><div class="tc-lbl">PRICE</div>
        <div class="tc-val" style="color:#fff">₹${{d.price.toLocaleString('en-IN')}}</div>
        <div class="tc-sub" style="color:${{pC(d.day_chg)}}">${{d.day_chg>0?'▲':'▼'}}${{Math.abs(d.day_chg).toFixed(3)}}%</div></div>
      <div class="tip-card"><div class="tc-lbl">Z-VOL/ROC</div>
        <div class="tc-val" style="color:${{zC(d.z_spike)}}">${{d.z_spike}}σ</div>
        <div class="tc-sub">ROC ${{d.roc}}× | ${{d.ratio}}× avg</div></div>
      <div class="tip-card"><div class="tc-lbl">CHECKS</div>
        <div class="tc-val" style="color:${{d.passed>=9?'#00e676':d.passed>=6?'#FFD700':'#ff5252'}}">${{d.passed}}/${{d.total_chk}}</div>
        <div class="tc-sub">passed</div></div>
    </div>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
      <span style="color:#444;font-size:10px">SCORE</span>
      <div style="flex:1;height:5px;background:#1a1a2a;border-radius:3px">
        <div style="width:${{sp}}%;height:5px;border-radius:3px;background:linear-gradient(90deg,#4fc3f7,#FFD700,#ff1744)"></div>
      </div>
      <span style="color:#FFD700;font-size:12px;font-weight:700">${{d.score}}</span>
    </div>
    ${{renderCat('volume')}}${{renderCat('price')}}${{renderCat('confluence')}}
    <div class="cat-hdr" style="color:#cf6cc9">🗺 ACCUMULATION ZONES</div>
    <div style="padding:4px 0 8px;font-size:12px">${{zones||'<span style="color:#333">Building...</span>'}}</div>
    <div class="cat-hdr" style="color:#555">⏱ TIMING</div>
    <div style="display:flex;flex-wrap:wrap;gap:12px;font-size:11px;color:#444;padding-bottom:8px">
      <span>First: <b style="color:#666">${{d.first_seen}}</b></span>
      <span>Age: <b style="color:#666">${{d.age}}s</b></span>
      <span>Hold: <b style="color:#666">${{d.total_hold}}s</b></span>
      <span>Streak: <b style="color:#666">${{d.elevated_streak}} ticks</b></span>
    </div>`;
}}

/* Desktop tooltip */
const tip = document.getElementById('tip');
function showTip(row) {{
  if(isMobile()) return;
  const d = JSON.parse(row.dataset.tip.replace(/&quot;/g,'"'));
  tip.innerHTML = buildDetail(d);
  const r = row.getBoundingClientRect();
  let left=r.right+12, top=r.top+window.scrollY-10;
  if(left+460>window.innerWidth) left=r.left-462;
  if(top+820>window.innerHeight+window.scrollY) top=Math.max(0,window.innerHeight+window.scrollY-830);
  Object.assign(tip.style,{{top:top+'px',left:left+'px',display:'block'}});
}}
function hideTip() {{ tip.style.display='none'; }}

/* Mobile bottom sheet */
function openSheet(row) {{
  const d = JSON.parse(row.dataset.tip.replace(/&quot;/g,'"'));
  document.getElementById('sheet-sym').textContent = d.sym;
  document.getElementById('sheet-body').innerHTML  = buildDetail(d);
  document.getElementById('overlay').style.display = 'block';
  document.getElementById('sheet').style.display   = 'block';
  document.body.style.overflow = 'hidden';
}}
function closeSheet() {{
  document.getElementById('overlay').style.display='none';
  document.getElementById('sheet').style.display='none';
  document.body.style.overflow='';
}}

/* Attach click/tap to every row */
document.querySelectorAll('tbody tr').forEach(tr => {{
  tr.addEventListener('click', () => {{
    if(isMobile()) openSheet(tr); else showTip(tr);
  }});
}});

/* Countdown → auto reload */
let secs={REFRESH_SEC};
const ct=document.getElementById('ct');
const iv=setInterval(()=>{{
  secs--;
  if(ct) ct.textContent=secs;
  if(secs<=0){{ clearInterval(iv); window.parent.location.reload(); }}
}},1000);

/* Strong buy popup */
const SB = {strong_buy_json};
(function(){{
  try {{
    const seen = JSON.parse(sessionStorage.getItem('seen_sb')||'[]');
    const nw   = SB.filter(s=>!seen.includes(s));
    if(nw.length){{
      sessionStorage.setItem('seen_sb',JSON.stringify([...new Set([...seen,...SB])]));
      const pop = document.createElement('div');
      pop.style.cssText='position:fixed;top:16px;right:16px;z-index:99999;background:#001a0a;border:2px solid #00e676;border-radius:10px;padding:14px 16px;min-width:200px;font-family:monospace;box-shadow:0 0 30px #00e67655;font-size:13px;color:#ddd';
      pop.innerHTML=`<div style="color:#00e676;font-weight:700;margin-bottom:8px">🚨 NEW STRONG BUY${{nw.length>1?'S':''}}</div>`
        +nw.map(s=>`<div style="color:#fff;font-size:15px;font-weight:700;margin-bottom:4px">${{s}}</div>`).join('')
        +`<div style="color:#333;font-size:10px;margin-top:6px">auto-dismisses 15s</div>`;
      document.body.appendChild(pop);
      setTimeout(()=>pop.remove(),15000);
    }}
    if(!SB.length) sessionStorage.removeItem('seen_sb');
  }}catch(e){{}}
}})();
</script>
</body></html>"""


# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════
def main():
    obj    = load_api()
    stocks = load_stocks()
    symbols         = stocks["Symbol"].tolist()
    token_to_symbol = dict(zip(stocks["token"], stocks["Symbol"]))
    batches         = [stocks["token"].tolist()[i:i+BATCH_SIZE]
                       for i in range(0, len(symbols), BATCH_SIZE)]
    init_state(symbols)

    # ── Header row ────────────────────────────────────
    c1, c2, c3 = st.columns([5, 3, 1])
    with c1:
        st.markdown(
            '<h2 style="font-family:JetBrains Mono,monospace;color:#FFD700;'
            'font-size:clamp(14px,3vw,20px);margin:0;letter-spacing:1px">'
            '⚡ Momentum Radar v2 — NSE</h2>',
            unsafe_allow_html=True,
        )
    tick    = st.session_state.tick
    warming = tick <= WARMUP_TICKS
    with c2:
        if warming:
            st.warning(f"⏳ Warming {tick}/{WARMUP_TICKS} ({tick*REFRESH_SEC}s/{WARMUP_TICKS*REFRESH_SEC}s)")
        else:
            st.success(f"🟢 Live — tick #{tick} · {st.session_state.last_ts.strftime('%H:%M:%S')}")
    with c3:
        refresh_btn = st.button("↻ Refresh", use_container_width=True)

    # ── Fetch & rank ──────────────────────────────────
    ts = fetch_all(obj, batches, token_to_symbol)
    st.session_state.tick   += 1
    st.session_state.last_ts = ts
    results = rank_stocks(symbols)
    st.session_state.last_results = results

    # ── HOF update ────────────────────────────────────
    if st.session_state.tick > WARMUP_TICKS:
        in_top3 = set()
        for i, r in enumerate(results[:3], 1):
            st.session_state.top3_freq[r["sym"]]      += 1
            st.session_state.top3_last_rank[r["sym"]]  = i
            in_top3.add(r["sym"])
        for sym in symbols:
            if sym not in in_top3:
                st.session_state.top3_last_rank[sym] = 0
    for r in results:
        st.session_state.hof_strength[r["sym"]] = {
            "score": round(r["score"],2), "signal": r["signal"],
            "sig_color": r["signal_color"], "z_spike": round(r["z_spike"],2),
            "ratio": round(r["ratio"],1), "roc": r["roc"],
            "candle_dir": r["candle_dir"], "price": r["price"],
            "up_ticks": r["up_ticks"],
        }
    hof = sorted([(s, st.session_state.top3_freq[s]) for s in symbols
                  if st.session_state.top3_freq[s] > 0],
                 key=lambda x: x[1], reverse=True)[:10]

    # ── Summary metric cards ──────────────────────────
    st.divider()
    if results:
        top5 = results[:min(5, len(results))]
        cols = st.columns(len(top5))
        for i, r in enumerate(top5):
            _, lc = strength_label(r["score"])
            with cols[i]:
                st.metric(
                    label=f"#{i+1} {r['sym']}",
                    value=f"₹{r['price']:,.2f}",
                    delta=f"{r['price_pct']:+.3f}%",
                )
                st.markdown(
                    f'<div style="color:{r["signal_color"]};font-size:11px;font-weight:700;margin-top:-8px">{r["signal"]}</div>'
                    f'<div style="color:{lc};font-size:10px;font-family:JetBrains Mono,monospace">Score: {r["score"]:.1f}</div>',
                    unsafe_allow_html=True,
                )

    st.divider()

    # ── 4 summary counters ────────────────────────────
    sb = [r for r in results if "STRONG BUY" in r["signal"]]
    wa = [r for r in results if "WATCH"      in r["signal"]]
    di = [r for r in results if "DIST"       in r["signal"]]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📊 Passed Gates", len(results))
    m2.metric("🟢 Strong Buys",  len(sb))
    m3.metric("🔷 Watch",        len(wa))
    m4.metric("🔴 Distribution", len(di))

    st.divider()

    # ── Full HTML component ───────────────────────────
    import streamlit.components.v1 as components
    if results:
        html_content = build_html(results, ts, tick, hof, warming)
        row_h  = 46
        extras = 380
        height = min(920, extras + len(results) * row_h)
        components.html(html_content, height=height, scrolling=True)
    else:
        st.markdown(
            '<div style="background:#0e0e18;border:1px solid #1e1e2e;border-radius:10px;'
            'padding:32px;text-align:center;color:#444;font-family:JetBrains Mono,monospace">'
            '⏳ No stocks have passed all 4 hard gates yet.<br>'
            '<span style="font-size:12px;color:#333">Baseline data building — check back in ~60s</span></div>',
            unsafe_allow_html=True,
        )

    # ── Manual refresh ────────────────────────────────
    if refresh_btn:
        st.rerun()

# SB

if __name__ == "__main__":
    main()
