"""
bist_dongu.py — BIST dongu calismasi, adim 1-3.

1) Veri seti (aylik): BIST100 (EVDS TP.MK.F.BILESIK, ay sonu), USD/TRY (TP.DK.USD.A, ay sonu),
   TUFE zinciri (TP.FG.F01 1978-79=100 -> TP.GENENDEKS.T1 2003=100), TCMB politika faizi
   (TP.BISPOLFAIZ.TUR, 2002->). Kuresel: Yahoo EEM, ^GSPC, DX-Y.NYB (ay sonu).
2) Uc mercek: BIST TL, BIST $ (TL / USDTRY), BIST reel (TL / TUFE). Kur soklari KURALLA:
   3 ayda reel kur degisimi (USDTRY / TUFE) >= KUR_SOKU_ESIK; ayni epizotta 12 ay bekleme.
   Faz haritasi: BIST $ zigzag (ZIGZAG_ESIK).
3) Ayristirma (2003->): aylik BIST $ log getirisi ~ EEM + DXY; kuresel pay ve Turkiye'ye ozgu kalinti;
   36 aylik kayan beta / R2.

Ham veri (BIST, EVDS) public repoya YAZILMAZ: yalniz turetilmis tablolar, ozetler ve grafikler.
Anahtar: EVDS_API_KEY ortam degiskeni (GitHub secret). Gecmisin kaydidir, tahmin degildir.
Cikti: sonuclar/bist/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from dongu_backtest import KLASOR, _json_guvenli, _plt, _tarih_duzelt, temizle
from dongu_fazlari import zigzag

EVDS_TABAN = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
SERI = {
    "bist_tl": ("TP.MK.F.BILESIK", "last"),
    "usdtry": ("TP.DK.USD.A", "last"),
    "tufe_eski": ("TP.FG.F01", None),        # 1978-79=100, 1982-01..2004-12
    "tufe_2003": ("TP.GENENDEKS.T1", None),  # 2003=100, 2003-01 ->
    "politika": ("TP.BISPOLFAIZ.TUR", None),
}
YAHOO = {"eem": "EEM", "sp500": "^GSPC", "dxy": "DX-Y.NYB"}
KUR_SOKU_ESIK = 0.15          # 3 ayda reel kur artisi >= %15
KUR_SOKU_PENCERE = 3
KUR_SOKU_BEKLEME = 12
OLAY_ONCE, OLAY_SONRA = 12, 36
ZIGZAG_ESIK = 0.30
KAYAN_AY = 36
AYRISTIRMA_BAS = "2003-05-31"
ETIKET_ESIK = 0.60
RENK = {"tl": "#7F8C8D", "usd": "#1B2631", "reel": "#B03A2E", "sok": "#E67E22", "kuresel": "#2980B9",
        "yerel": "#C0392B", "medyan": "#111111"}
CIKTI = KLASOR / "sonuclar" / "bist"
HAM = KLASOR / "ham_veri"     # git disi


# ---------------------------------------------------------------------------
def evds(kod: str, toplama: str | None, anahtar: str) -> pd.Series:
    import requests
    bitis = datetime.now(timezone.utc).strftime("%d-%m-%Y")
    url = f"{EVDS_TABAN}series={kod}&startDate=01-01-1980&endDate={bitis}&type=json"
    if toplama:
        url += f"&frequency=5&aggregationTypes={toplama}"
    r = requests.get(url, headers={"key": anahtar, "User-Agent": "dongu-arastirma/0.1"}, timeout=90)
    r.raise_for_status()
    kol = kod.replace(".", "_")
    tarih, deger = [], []
    for i in r.json().get("items", []):
        v = i.get(kol)
        if v in (None, "", "null"):
            continue
        y, a = str(i["Tarih"]).split("-")[:2]
        tarih.append(pd.Timestamp(int(y), int(a), 1) + pd.offsets.MonthEnd(0))
        deger.append(float(v))
    if not deger:
        raise RuntimeError(f"{kod}: bos yanit")
    s = pd.Series(deger, index=pd.DatetimeIndex(tarih)).sort_index()
    return s[~s.index.duplicated(keep="last")]


def yahoo_ay_sonu(tickerlar: dict[str, str]) -> tuple[dict[str, pd.Series], dict[str, str]]:
    import yfinance as yf
    cikti, hatali = {}, {}
    for k, tk in tickerlar.items():
        try:
            df = yf.download(tk, start="1985-01-01", auto_adjust=True, progress=False, threads=False)
            kap = df["Close"]
            if isinstance(kap, pd.DataFrame):
                kap = kap.iloc[:, 0]
            s = _tarih_duzelt(kap.dropna())
            cikti[k] = s[s > 0].resample("ME").last().dropna()
        except Exception as e:
            hatali[k] = f"{tk}: {type(e).__name__}: {e}"
    return cikti, hatali


def sentetik() -> tuple[dict[str, pd.Series], dict[str, pd.Series]]:
    rng = np.random.default_rng(3)
    aylar = pd.date_range("1982-01-31", "2026-11-30", freq="ME")
    n = len(aylar)
    enf = np.clip(0.03 + 0.02 * np.sin(np.arange(n) / 40), 0.002, None)
    tufe = pd.Series(np.cumprod(1 + enf), index=aylar)
    kur = pd.Series(np.cumprod(1 + enf + rng.normal(0, 0.03, n)), index=aylar)
    for t in ("1994-02-28", "2001-02-28", "2018-07-31", "2021-10-31"):
        i = aylar.get_loc(pd.Timestamp(t))
        kur.iloc[i:] *= 1.35
    kur.loc[:"2004-12-31"] *= 1e6
    bist = pd.Series(np.cumprod(1 + enf + rng.normal(0.004, 0.1, n)), index=aylar)
    evds_v = {"bist_tl": bist.loc["1986-02-28":], "usdtry": kur, "tufe_eski": (tufe * 50).loc[:"2004-12-31"],
              "tufe_2003": (tufe * 3).loc["2003-01-31":], "politika": pd.Series(enf * 1200, index=aylar).loc["2002-02-28":]}
    kuresel = {k: pd.Series(np.cumprod(1 + rng.normal(0.006, 0.05, n)), index=aylar) for k in YAHOO}
    kuresel["eem"] = kuresel["eem"].loc["2003-04-30":]
    return evds_v, kuresel


# ---------------------------------------------------------------------------
def tufe_zinciri(eski: pd.Series, yeni: pd.Series) -> tuple[pd.Series, str]:
    bag = yeni.index[0]
    if bag not in eski.index:
        raise RuntimeError("TUFE zinciri: baglanti ayi eski seride yok")
    oran = yeni[bag] / eski[bag]
    zincir = pd.concat([eski[eski.index < bag] * oran, yeni]).sort_index()
    return zincir, f"TUFE: {eski.index[0]:%Y-%m}..{bag:%Y-%m} eski seri x{oran:.6g} ile {bag:%Y-%m}'de 2003=100'e baglandi"


def kur_soklari(kur: pd.Series, tufe: pd.Series) -> pd.DataFrame:
    reel = (kur / kur.shift(KUR_SOKU_PENCERE)) / (tufe / tufe.shift(KUR_SOKU_PENCERE)) - 1
    reel = reel.dropna()
    olaylar, son = [], None
    for t, v in reel.items():
        if v >= KUR_SOKU_ESIK and (son is None or (t - son).days > KUR_SOKU_BEKLEME * 30.44):
            bas = kur.index[kur.index.get_loc(t) - KUR_SOKU_PENCERE]
            olaylar.append({"sok_ayi": t, "baslangic": bas, "reel_kur_3a": float(v),
                            "nominal_kur_3a": float(kur[t] / kur[bas] - 1)})
            son = t
        elif v >= KUR_SOKU_ESIK:
            son = t
    return pd.DataFrame(olaylar)


def olay_yollari(seri: pd.Series, olaylar: pd.DataFrame) -> pd.DataFrame:
    yollar = {}
    for _, o in olaylar.iterrows():
        i = seri.index.get_indexer([o["baslangic"]], method="nearest")[0]
        lo, hi = max(0, i - OLAY_ONCE), min(len(seri), i + OLAY_SONRA + 1)
        yollar[f"{o['baslangic']:%Y-%m}"] = pd.Series(seri.iloc[lo:hi].to_numpy() / seri.iloc[i] - 1,
                                                      index=np.arange(lo - i, hi - i))
    return pd.DataFrame(yollar)


def olay_ozeti(olaylar: pd.DataFrame, usd: pd.Series, reel: pd.Series, yollar_usd: pd.DataFrame) -> pd.DataFrame:
    satir = []
    for _, o in olaylar.iterrows():
        k = f"{o['baslangic']:%Y-%m}"
        y = yollar_usd[k].dropna()
        sonra = y[y.index >= 0]
        dip_ay = int(sonra.loc[:12].idxmin()) if len(sonra) else None
        geri = sonra[(sonra.index > (dip_ay or 0)) & (sonra >= 0)]   # dipten SONRA baslangic seviyesine donus
        bas = o["baslangic"]
        def deg(s, ay):
            t = bas + pd.DateOffset(months=ay) + pd.offsets.MonthEnd(0)
            return float(s.asof(t) / s.asof(bas) - 1) if t <= s.index[-1] and bas >= s.index[0] else np.nan
        satir.append({"baslangic": k, "sok_ayi": f"{o['sok_ayi']:%Y-%m}",
                      "nominal_kur_3a": o["nominal_kur_3a"], "reel_kur_3a": o["reel_kur_3a"],
                      "bist_usd_12a_icinde_dip": float(sonra.loc[:12].min()) if len(sonra) else np.nan,
                      "dibe_ay": dip_ay,
                      "bist_usd_12a": deg(usd, 12), "bist_usd_24a": deg(usd, 24), "bist_usd_36a": deg(usd, 36),
                      "bist_reel_12a": deg(reel, 12), "bist_reel_24a": deg(reel, 24),
                      "usd_seviyesine_donus_ay": int(geri.index[0]) if len(geri) else None})
    return pd.DataFrame(satir)


def faz_tablosu(usd: pd.Series, tl: pd.Series, reel: pd.Series, kuresel: dict) -> tuple[pd.DataFrame, list]:
    p = zigzag(usd, ZIGZAG_ESIK)
    satir = []
    for a, b in zip(p[:-1], p[1:]):
        s = {"baslangic": f"{a['tarih']:%Y-%m}", "bitis": f"{b['tarih']:%Y-%m}" + (" (teyitsiz)" if b["teyitsiz"] else ""),
             "faz": "yükseliş" if b["fiyat"] > a["fiyat"] else "düşüş",
             "bist_usd": b["fiyat"] / a["fiyat"] - 1,
             "bist_reel": float(reel.asof(b["tarih"]) / reel.asof(a["tarih"]) - 1),
             "sure_ay": int(round((b["tarih"] - a["tarih"]).days / 30.44))}
        for k, ser in kuresel.items():
            s[k] = float(ser.asof(b["tarih"]) / ser.asof(a["tarih"]) - 1) if ser.index[0] <= a["tarih"] else np.nan
        satir.append(s)
    return pd.DataFrame(satir), p


def ayristirma(usd: pd.Series, kuresel: dict) -> tuple[pd.DataFrame, dict]:
    df = pd.DataFrame({"bist": np.log(usd), "eem": np.log(kuresel["eem"]), "dxy": np.log(kuresel["dxy"])}).diff()
    df = df.loc[AYRISTIRMA_BAS:].dropna()
    X = np.column_stack([np.ones(len(df)), df["eem"], df["dxy"]])
    katsayi, *_ = np.linalg.lstsq(X, df["bist"].to_numpy(), rcond=None)
    tahmin = X[:, 1:] @ katsayi[1:]
    kalinti = df["bist"].to_numpy() - tahmin
    r2 = 1 - np.var(kalinti - katsayi[0]) / np.var(df["bist"])
    beta, r2_k = [], []
    for i in range(len(df)):
        if i + 1 < KAYAN_AY:
            beta.append(np.nan); r2_k.append(np.nan); continue
        w = df.iloc[i + 1 - KAYAN_AY: i + 1]
        Xw = np.column_stack([np.ones(len(w)), w["eem"]])
        kw, *_ = np.linalg.lstsq(Xw, w["bist"].to_numpy(), rcond=None)
        res = w["bist"].to_numpy() - Xw @ kw
        beta.append(kw[1]); r2_k.append(1 - np.var(res) / np.var(w["bist"]))
    cikti = pd.DataFrame({"bist_usd_kum": np.exp(df["bist"].cumsum()),
                          "kuresel_pay_kum": np.exp(pd.Series(tahmin, index=df.index).cumsum()),
                          "turkiye_ozgu_kum": np.exp(pd.Series(kalinti, index=df.index).cumsum()),
                          "kayan_beta_eem": beta, "kayan_r2": r2_k}, index=df.index)
    bilgi = {"donem": f"{df.index[0]:%Y-%m}..{df.index[-1]:%Y-%m}", "beta_eem": float(katsayi[1]),
             "beta_dxy": float(katsayi[2]), "r2": float(r2), "ay": int(len(df))}
    return cikti, bilgi


# ---------------------------------------------------------------------------
def _golge(ax, olaylar):
    for _, o in olaylar.iterrows():
        ax.axvspan(o["baslangic"], o["sok_ayi"], color=RENK["sok"], alpha=0.25, lw=0)


def grafik_uc_mercek(tl, usd, reel, olaylar, pivot, yol) -> dict:
    plt = _plt()
    fig, axlar = plt.subplots(3, 1, figsize=(11, 9.5), sharex=True, gridspec_kw={"hspace": 0.12})
    bas = usd.index[0]
    kat = {"tl": float(tl.iloc[-1] / tl.asof(bas)), "usd": float(usd.iloc[-1] / usd.asof(bas)),
           "reel": float(reel.iloc[-1] / reel.asof(bas))}
    for ax, s, ad, renk, k in ((axlar[0], tl, "BIST100 (TL, nominal)", RENK["tl"], "tl"),
                               (axlar[1], usd, "BIST100 ($)", RENK["usd"], "usd"),
                               (axlar[2], reel, "BIST100 (reel TL, TÜFE ile)", RENK["reel"], "reel")):
        ax.plot(s.index, s, color=renk, lw=1.4)
        ax.set_yscale("log")
        _golge(ax, olaylar)
        ax.text(0.01, 0.92, f"{ad} · {bas:%Y}'ten bu yana {kat[k]:,.1f} kat".replace(",", "."),
                transform=ax.transAxes, fontsize=10, fontweight="bold", color=renk)
    for a, b in zip(pivot[:-1], pivot[1:]):
        d = b["fiyat"] / a["fiyat"] - 1
        if abs(d) >= ETIKET_ESIK:
            axlar[1].annotate(f"{d * 100:+.0f}%", xy=(b["tarih"], b["fiyat"]), xytext=(0, 7 if d > 0 else -13),
                              textcoords="offset points", ha="center", fontsize=8,
                              color="#2E9E5B" if d > 0 else "#C0392B")
    axlar[0].set_title("BIST100 üç mercekle: TL'deki yükselişin çoğu enflasyon ve kur; döngüler dolar ve reel bazda görünür",
                       loc="left", fontweight="bold", fontsize=11)
    axlar[2].text(1.0, -0.2, f"Turuncu: kur şoku (3 ayda reel kur ≥ +%{KUR_SOKU_ESIK * 100:.0f}). "
                  f"Etiketler: BIST $ fazları (±%{ZIGZAG_ESIK * 100:.0f}). Kaynak: TCMB EVDS.",
                  transform=axlar[2].transAxes, ha="right", fontsize=8, color="#777777")
    fig.savefig(yol, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return kat


def grafik_kur_soklari(yollar: pd.DataFrame, yol) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(11, 5.8))
    for k in yollar.columns:
        y = yollar[k].dropna()
        ax.plot(y.index, y * 100, lw=1.1, alpha=0.75, label=k)
    med = yollar.median(axis=1, skipna=True)
    ax.plot(med.index, med * 100, color=RENK["medyan"], lw=2.8, label="medyan")
    ax.axvline(0, color="#999999", lw=1)
    ax.axhline(0, color="#999999", lw=0.8)
    d = med.loc[0:12]
    ax.set_title(f"Kur şokları (n={yollar.shape[1]}): BIST dolar bazında medyan {d.min() * 100:.0f}% düştü, "
                 f"dibi {int(d.idxmin())}. ayda gördü", loc="left", fontweight="bold", fontsize=11.5)
    ax.set_xlabel("Şokun başladığı aydan itibaren ay")
    ax.set_ylabel("BIST100 ($), başlangıca göre %")
    ax.legend(frameon=False, fontsize=8, ncol=4, loc="upper left")
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


def grafik_ayristirma(a: pd.DataFrame, bilgi: dict, yol) -> None:
    plt = _plt()
    fig, (ust, alt) = plt.subplots(2, 1, figsize=(11, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1.6]})
    ust.plot(a.index, a["bist_usd_kum"] * 100, color=RENK["usd"], lw=2.2, label="BIST100 ($)")
    ust.plot(a.index, a["kuresel_pay_kum"] * 100, color=RENK["kuresel"], lw=1.6,
             label=f"Küresel pay (EEM β={bilgi['beta_eem']:.2f}, dolar β={bilgi['beta_dxy']:.2f})")
    ust.plot(a.index, a["turkiye_ozgu_kum"] * 100, color=RENK["yerel"], lw=1.6, label="Türkiye'ye özgü kalıntı")
    ust.set_yscale("log")
    ust.axhline(100, color="#999999", lw=0.8)
    ust.set_ylabel(f"{a.index[0]:%Y-%m} = 100 (log)")
    ust.legend(frameon=False, fontsize=9, loc="upper left")
    ust.set_title(f"BIST $ aylık hareketinin %{bilgi['r2'] * 100:.0f}'i küresel; uzun vadeli farkı Türkiye'ye özgü kısım belirliyor",
                  loc="left", fontweight="bold", fontsize=11.5)
    alt.plot(a.index, a["kayan_beta_eem"], color=RENK["kuresel"], lw=1.6, label=f"{KAYAN_AY} aylık beta (EEM)")
    alt.plot(a.index, a["kayan_r2"], color=RENK["tl"], lw=1.4, label=f"{KAYAN_AY} aylık R²")
    alt.axhline(1, color="#BBBBBB", lw=0.8, ls="--")
    alt.legend(frameon=False, fontsize=8.5, loc="upper left", ncol=2)
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------------------
def _y(x) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.0f}%"


def _ay(x) -> str:
    return "—" if x is None or pd.isna(x) else str(int(x))


def kos(demo: bool = False) -> int:
    cikti = KLASOR / ("sonuclar_demo" if demo else "sonuclar") / "bist"
    cikti.mkdir(parents=True, exist_ok=True)
    notlar, hatali = [], {}
    if demo:
        ev, kuresel = sentetik()
    else:
        anahtar = os.environ.get("EVDS_API_KEY", "").strip()
        if not anahtar:
            print("HATA: EVDS_API_KEY yok", file=sys.stderr)
            return 1
        ev = {}
        for k, (kod, toplama) in SERI.items():
            try:
                ev[k] = evds(kod, toplama, anahtar)
            except Exception as e:
                hatali[k] = f"{kod}: {type(e).__name__}: {str(e).replace(anahtar, '***')[:200]}"
        if any(k not in ev for k in ("bist_tl", "usdtry", "tufe_eski", "tufe_2003")):
            print(f"HATA: cekirdek EVDS serileri eksik: {hatali}", file=sys.stderr)
            return 1
        kuresel, h2 = yahoo_ay_sonu(YAHOO)
        hatali.update(h2)
    for k in ("bist_tl", "usdtry"):
        ev[k], nt = temizle(ev[k])
        notlar += [f"{k}: {x}" for x in nt]
    tufe, nt = tufe_zinciri(ev["tufe_eski"], ev["tufe_2003"])
    notlar.append(nt)
    df = pd.DataFrame({"bist_tl": ev["bist_tl"], "usdtry": ev["usdtry"], "tufe": tufe}).dropna()
    tl, kur, tf = df["bist_tl"], df["usdtry"], df["tufe"]
    usd, reel = tl / kur, tl / tf
    if not demo:
        HAM.mkdir(exist_ok=True)
        df.assign(politika=ev.get("politika")).to_csv(HAM / "bist_aylik.csv", index_label="ay")

    olaylar = kur_soklari(ev["usdtry"], tufe)
    yollar_usd = olay_yollari(usd, olaylar)
    ozet_olay = olay_ozeti(olaylar, usd, reel, yollar_usd)
    fazlar, pivot = faz_tablosu(usd, tl, reel, kuresel)
    ayr, ayr_bilgi = ayristirma(usd, kuresel) if "eem" in kuresel and "dxy" in kuresel else (None, None)

    enf = tf / tf.shift(12) - 1
    reel_faiz = None
    if "politika" in ev:
        pol = ev["politika"].reindex(tf.index)
        reel_faiz = ((1 + pol / 100) / (1 + enf) - 1).dropna()

    kat = grafik_uc_mercek(tl, usd, reel, olaylar, pivot, cikti / "uc_mercek.png")
    grafik_kur_soklari(yollar_usd, cikti / "kur_soklari.png")
    if ayr is not None:
        grafik_ayristirma(ayr, ayr_bilgi, cikti / "ayristirma.png")
        ayr[["kayan_beta_eem", "kayan_r2"]].round(3).to_csv(cikti / "kayan_beta.csv", encoding="utf-8-sig", index_label="ay")

    ozet_olay.to_csv(cikti / "kur_soklari.csv", index=False, encoding="utf-8-sig")
    (yollar_usd * 100).round(1).to_csv(cikti / "kur_soku_yollari_usd.csv", encoding="utf-8-sig", index_label="ay")
    fazlar.to_csv(cikti / "fazlar_bist_usd.csv", index=False, encoding="utf-8-sig")
    if reel_faiz is not None:
        (reel_faiz * 100).round(1).to_csv(cikti / "reel_politika_faizi.csv", encoding="utf-8-sig", index_label="ay",
                                          header=["reel_faiz_yuzde"])

    son = df.index[-1]
    ozet = {"uretim_zamani_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "demo": demo,
            "veri": {"bist_ilk": f"{tl.index[0]:%Y-%m}", "son_ay": f"{son:%Y-%m}", "tufe_ilk": f"{tf.index[0]:%Y-%m}"},
            "notlar": notlar, "hatali": hatali,
            "kurallar": {"kur_soku": f"3 ayda reel kur (USDTRY/TUFE) >= +%{KUR_SOKU_ESIK * 100:.0f}, {KUR_SOKU_BEKLEME} ay bekleme",
                         "faz": f"BIST $ zigzag ±%{ZIGZAG_ESIK * 100:.0f}", "ayristirma": f"{AYRISTIRMA_BAS[:7]}->, OLS: BIST$ ~ EEM + DXY"},
            "katlar_bastan_beri": kat,
            "kur_soku_sayisi": int(len(olaylar)),
            "kur_soku_medyan": {"dip": float(yollar_usd.median(axis=1).loc[0:12].min()) if len(yollar_usd.columns) else None,
                                "12a": float(yollar_usd.median(axis=1).get(12, np.nan)),
                                "24a": float(yollar_usd.median(axis=1).get(24, np.nan)),
                                "36a": float(yollar_usd.median(axis=1).get(36, np.nan))},
            "ayristirma": ayr_bilgi,
            "son_reel_politika_faizi": float(reel_faiz.iloc[-1]) if reel_faiz is not None and len(reel_faiz) else None,
            "son_yillik_enflasyon": float(enf.iloc[-1])}
    (cikti / "ozet.json").write_text(json.dumps(_json_guvenli(ozet), ensure_ascii=False, indent=2), encoding="utf-8")

    sat = [f"# BIST döngü çalışması — adım 1-3 ({ozet['uretim_zamani_utc']}{', DEMO' if demo else ''})", "",
           f"Veri: BIST100 {ozet['veri']['bist_ilk']}→{ozet['veri']['son_ay']} (TCMB EVDS), aylık. Ham veri yayımlanmaz.", "",
           f"**Baştan beri:** TL {kat['tl']:,.0f} kat · $ {kat['usd']:.1f} kat · reel {kat['reel']:.1f} kat", "",
           f"## Kur şokları ({ozet['kurallar']['kur_soku']})", "",
           "| başlangıç | şok ayı | nominal kur 3 ay | reel kur 3 ay | BIST $ 12 ay içindeki dip | dibe (ay) | BIST $ +12 | +24 | +36 | BIST reel +12 | +24 | $ seviyeye dönüş (ay) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in ozet_olay.iterrows():
        sat.append(f"| {r['baslangic']} | {r['sok_ayi']} | {_y(r['nominal_kur_3a'])} | {_y(r['reel_kur_3a'])} | "
                   f"{_y(r['bist_usd_12a_icinde_dip'])} | {_ay(r['dibe_ay'])} | {_y(r['bist_usd_12a'])} | {_y(r['bist_usd_24a'])} | "
                   f"{_y(r['bist_usd_36a'])} | {_y(r['bist_reel_12a'])} | {_y(r['bist_reel_24a'])} | {_ay(r['usd_seviyesine_donus_ay'])} |")
    sat += ["", f"## BIST $ fazları ({ozet['kurallar']['faz']})", "",
            "| başlangıç | bitiş | faz | BIST $ | BIST reel | süre (ay) | " + " | ".join(YAHOO) + " |",
            "|---|---|---|---|---|---|" + "---|" * len(YAHOO)]
    for _, r in fazlar.iterrows():
        sat.append(f"| {r['baslangic']} | {r['bitis']} | {r['faz']} | {_y(r['bist_usd'])} | {_y(r['bist_reel'])} | {r['sure_ay']} | "
                   + " | ".join(_y(r.get(k)) for k in YAHOO) + " |")
    if ayr_bilgi:
        sat += ["", "## Küresel / yerel ayrıştırma",
                f"- Dönem {ayr_bilgi['donem']} ({ayr_bilgi['ay']} ay): β(EEM) {ayr_bilgi['beta_eem']:.2f}, "
                f"β(dolar endeksi) {ayr_bilgi['beta_dxy']:.2f}, R² {ayr_bilgi['r2']:.2f}"]
    sat += ["", "Geçmişin kaydıdır, tahmin değildir. Yatırım tavsiyesi değildir."]
    (cikti / "rapor.md").write_text("\n".join(sat) + "\n", encoding="utf-8")
    print(f"tamam: {cikti} | hatali: {hatali or 'yok'} | notlar: {notlar}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    sys.exit(kos(demo=ap.parse_args().demo))
