"""
cot_grafik.py — COT konumlanma cizgi grafigi + altinda urunun fiyati.

Bagimsiz arastirma reposu (dongu-arastirma). Gizli anahtar yok.
COT verisi CFTC'nin Socrata ucundan (futures + options birlesik):
  emtia     -> Disaggregated (kh3c-gbw2), Managed Money (fonlar) uzun / kisa
  endeksler -> TFF (yw9f-hn96), Leveraged Funds (kaldiracli fonlar) uzun / kisa
Sozlesme DEGISMEZ contract_market_code ile sorgulanir (ad degisikliklerinden etkilenmez).
Fiyat: Yahoo (yfinance), yalniz bu klasorde; COT'un as-of gunu (Sali) kapanisina hizalanir.

Ust panel : fonlarin UZUN, KISA ve NET pozisyonu (kontrat)
Alt panel : ayni urunun fiyati, farkli renkte; fonlarin net pozisyonu belirgin
            artirdigi / azalttigi haftalar fiyat uzerinde isaretli
Not       : Bu grafik konumlanmanin betimlemesidir, yon sinyali degildir.

Kullanim:
  python cot_grafik.py          # gercek veri
  python cot_grafik.py --demo   # sentetik veriyle kuru test (ag yok)
Cikti: sonuclar/cot/  (cot_<piyasa>_3y.png, cot_<piyasa>_tam.png, cot_<piyasa>.csv, ozet.json); --demo -> sonuclar_demo/
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

KLASOR = Path(__file__).resolve().parent
ALT_KLASOR = "cot"   # --demo ciktisi sonuclar_demo/ altina gider (git disi)

SOCRATA = "https://publicreporting.cftc.gov/resource/{ds}.json"
BASLIK = {"User-Agent": "dongu-arastirma/0.1"}
SAYFA = 50000
BELIRGIN_YUZDELIK = 90        # |haftalik net degisim| son 3 yilin bu yuzdeliginin ustundeyse "belirgin"
KISA_PENCERE_YIL = 3

PIYASALAR = {
    "altin":  dict(ad="Altın",      ds="kh3c-gbw2", kod="088691", tur="emtia",    fiyat="GC=F",  renk="#B8860B"),
    "gumus":  dict(ad="Gümüş",      ds="kh3c-gbw2", kod="084691", tur="emtia",    fiyat="SI=F",  renk="#607D8B"),
    "nas100": dict(ad="Nasdaq 100", ds="yw9f-hn96", kod="209742", tur="finansal", fiyat="^NDX",  renk="#6A3D9A"),
    "spx":    dict(ad="S&P 500",    ds="yw9f-hn96", kod="13874A", tur="finansal", fiyat="^GSPC", renk="#1F6FB4"),
    "dow30":  dict(ad="Dow Jones",  ds="yw9f-hn96", kod="124603", tur="finansal", fiyat="^DJI",  renk="#2E7D32"),
}
GRUP_ADI = {"emtia": "Fonlar (Managed Money)", "finansal": "Kaldıraçlı fonlar (Leveraged Funds)"}
RENK = {"uzun": "#2E9E5B", "kisa": "#D0453A", "net": "#1A1A1A", "artis": "#2E9E5B", "azalis": "#D0453A"}


def _f(satir: dict, *adaylar):
    for a in adaylar:
        if a in satir and satir[a] not in (None, ""):
            try:
                return float(satir[a])
            except ValueError:
                pass
    return None


def cot_cek(p: dict) -> pd.DataFrame:
    import requests
    hepsi, offset = [], 0
    while True:
        prm = {"$where": f"cftc_contract_market_code='{p['kod']}'", "$limit": SAYFA,
               "$offset": offset, "$order": "report_date_as_yyyy_mm_dd"}
        r = requests.get(SOCRATA.format(ds=p["ds"]), params=prm, headers=BASLIK, timeout=60)
        r.raise_for_status()
        parca = r.json()
        hepsi.extend(parca)
        if len(parca) < SAYFA:
            break
        offset += SAYFA
        time.sleep(1.0)
    satirlar = []
    for s in hepsi:
        t = (s.get("report_date_as_yyyy_mm_dd") or "")[:10]
        if p["tur"] == "emtia":
            u = _f(s, "m_money_positions_long_all", "mmoney_positions_long_all")
            k = _f(s, "m_money_positions_short_all", "mmoney_positions_short_all")
        else:
            u = _f(s, "lev_money_positions_long", "lev_money_positions_long_all")
            k = _f(s, "lev_money_positions_short", "lev_money_positions_short_all")
        oi = _f(s, "open_interest_all", "open_interest")
        if t and u is not None and k is not None:
            satirlar.append({"tarih": pd.Timestamp(t), "uzun": u, "kisa": k, "oi": oi})
    if not satirlar:
        raise RuntimeError("bos yanit (kod ya da kolon adi degismis olabilir)")
    df = pd.DataFrame(satirlar).drop_duplicates("tarih", keep="last").set_index("tarih").sort_index()
    return df


def fiyat_cek(tk: str) -> pd.Series:
    import yfinance as yf
    df = yf.download(tk, start="2006-01-01", auto_adjust=True, progress=False, threads=False)
    if df is None or len(df) == 0:
        raise RuntimeError(f"{tk}: bos fiyat")
    k = df["Close"]
    if isinstance(k, pd.DataFrame):
        k = k.iloc[:, 0]
    idx = pd.DatetimeIndex(k.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    s = pd.Series(np.asarray(k.values, dtype=float), index=idx.normalize()).dropna().sort_index()
    return s[s > 0]


def sentetik(anahtar: str) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(abs(hash(anahtar)) % 2 ** 32)
    haftalar = pd.date_range("2006-06-13", "2026-11-17", freq="W-TUE")
    taban = 150_000 + rng.normal(0, 20_000, len(haftalar)).cumsum() * 0.1
    uzun = np.clip(taban + rng.normal(0, 8_000, len(haftalar)).cumsum() * 0.3, 10_000, None)
    kisa = np.clip(60_000 + rng.normal(0, 6_000, len(haftalar)).cumsum() * 0.3, 5_000, None)
    cot = pd.DataFrame({"uzun": uzun, "kisa": kisa, "oi": uzun + kisa + 200_000}, index=haftalar)
    gunler = pd.bdate_range("2006-01-02", "2026-11-20")
    fiyat = pd.Series(1000 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, len(gunler)))), index=gunler)
    return cot, fiyat


def birlestir(cot: pd.DataFrame, fiyat: pd.Series) -> pd.DataFrame:
    d = cot.copy()
    d["net"] = d["uzun"] - d["kisa"]
    d["net_degisim"] = d["net"].diff()
    d["uzun_degisim"] = d["uzun"].diff()
    d["kisa_degisim"] = d["kisa"].diff()
    d["fiyat"] = [fiyat.asof(t) if t >= fiyat.index[0] else np.nan for t in d.index]
    # belirgin hafta: |net degisim| son 3 yilin (kayan) BELIRGIN_YUZDELIK'inin ustunde
    pencere = 52 * KISA_PENCERE_YIL
    esik = d["net_degisim"].abs().rolling(pencere, min_periods=52).quantile(BELIRGIN_YUZDELIK / 100)
    d["belirgin"] = np.where(d["net_degisim"].abs() > esik, np.sign(d["net_degisim"]), 0)
    return d


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.25})
    return plt


def _bin(x, _pos=None):
    return "0" if x == 0 else f"{x / 1000:,.0f}K".replace(",", ".")


def grafik(d: pd.DataFrame, p: dict, yol: Path, baslangic: pd.Timestamp | None) -> None:
    plt = _plt()
    from matplotlib.ticker import FuncFormatter
    if baslangic is not None:
        d = d.loc[baslangic:]
    fig, (ust, alt) = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 2], "hspace": 0.08})
    ust.plot(d.index, d["uzun"], color=RENK["uzun"], lw=1.4, label="Uzun (long)")
    ust.plot(d.index, d["kisa"], color=RENK["kisa"], lw=1.4, label="Kısa (short)")
    ust.plot(d.index, d["net"], color=RENK["net"], lw=2.2, label="Net (uzun − kısa)")
    ust.axhline(0, color="#999999", lw=0.8)
    ust.yaxis.set_major_formatter(FuncFormatter(_bin))
    ust.set_ylabel("Kontrat")
    son = d.iloc[-1]
    ust.set_title(f"{p['ad']} · {GRUP_ADI[p['tur']]} pozisyonu ve fiyat", loc="left",
                  fontweight="bold", pad=20)
    ust.text(0, 1.012, f"Son rapor {d.index[-1].date()} · net {son['net']:,.0f} "
             f"(haftalık {son['net_degisim']:+,.0f}) · uzun {son['uzun']:,.0f} · kısa {son['kisa']:,.0f}"
             .replace(",", "."), transform=ust.transAxes, fontsize=9, color="#555555", va="bottom")
    ust.legend(loc="best", frameon=True, framealpha=0.85, edgecolor="none", ncol=3, fontsize=9)

    alt.plot(d.index, d["fiyat"], color=p["renk"], lw=1.8, label="Fiyat (COT günü kapanışı)")
    art = d[d["belirgin"] > 0]
    aza = d[d["belirgin"] < 0]
    alt.scatter(art.index, art["fiyat"], marker="^", s=26, color=RENK["artis"], zorder=3,
                label="Fonlar net pozisyonu belirgin ARTIRDI")
    alt.scatter(aza.index, aza["fiyat"], marker="v", s=26, color=RENK["azalis"], zorder=3,
                label="Fonlar net pozisyonu belirgin AZALTTI")
    alt.set_ylabel("Fiyat")
    alt.legend(loc="best", frameon=True, framealpha=0.85, edgecolor="none", fontsize=8.5)
    alt.text(1.0, -0.22, f"Belirgin = haftalık net değişim, son {KISA_PENCERE_YIL} yılın %{BELIRGIN_YUZDELIK} "
             "üstünde. Betimlemedir, yön sinyali değildir. Kaynak: CFTC, Yahoo.",
             transform=alt.transAxes, ha="right", fontsize=7.5, color="#777777")
    fig.savefig(yol, dpi=160, bbox_inches="tight")
    plt.close(fig)


def kos(demo: bool = False) -> int:
    cikti = KLASOR / ("sonuclar_demo" if demo else "sonuclar") / ALT_KLASOR
    cikti.mkdir(parents=True, exist_ok=True)
    ozet, hatali = {}, {}
    for anahtar, p in PIYASALAR.items():
        try:
            if demo:
                cot, fiyat = sentetik(anahtar)
            else:
                cot, fiyat = cot_cek(p), fiyat_cek(p["fiyat"])
            d = birlestir(cot, fiyat)
            d.to_csv(cikti / f"cot_{anahtar}.csv", encoding="utf-8-sig", index_label="tarih")
            kisa_bas = d.index[-1] - pd.DateOffset(years=KISA_PENCERE_YIL)
            grafik(d, p, cikti / f"cot_{anahtar}_3y.png", kisa_bas)
            grafik(d, p, cikti / f"cot_{anahtar}_tam.png", None)
            son = d.iloc[-1]
            pencere = d.loc[kisa_bas:]
            ozet[anahtar] = {
                "ad": p["ad"], "grup": GRUP_ADI[p["tur"]], "son_rapor": str(d.index[-1].date()),
                "uzun": float(son["uzun"]), "kisa": float(son["kisa"]), "net": float(son["net"]),
                "net_degisim": float(son["net_degisim"]),
                "uzun_degisim": float(son["uzun_degisim"]), "kisa_degisim": float(son["kisa_degisim"]),
                "fiyat": None if np.isnan(son["fiyat"]) else float(son["fiyat"]),
                "net_3y_yuzdelik": float((pencere["net"] <= son["net"]).mean() * 100),
                "ilk_rapor": str(d.index[0].date()), "hafta": int(len(d)),
            }
        except Exception as e:   # bir piyasa patlarsa digerleri devam, hata ozette
            hatali[anahtar] = f"{type(e).__name__}: {e}"
    (cikti / "ozet.json").write_text(json.dumps({
        "uretim_zamani_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "demo": demo, "piyasalar": ozet, "hatali": hatali}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"tamam: {cikti} | hatali: {hatali or 'yok'}")
    return 1 if hatali and not ozet else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    sys.exit(kos(demo=ap.parse_args().demo))
