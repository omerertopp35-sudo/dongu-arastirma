"""
dongu_backtest.py — Piyasa donguleri arastirmasi, backtest #1.

Bagimsiz arastirma reposu (dongu-arastirma). Veri: Yahoo (yfinance). Gizli anahtar yok.

Dort soru:
  A) Gumus 2011 <-> 2026: zirve gunune hizali patika karsilastirmasi
  B) Parabolik tepe olay calismasi: kuralla tanimli tepeler, coklu varlik,
     teyit gununden sonraki getiri vs ayni varligin rastgele gunleri
  C) Gumus + altin + Nasdaq AYNI CEYREKTE dustugunde diger varliklar ne yapti,
     sonraki 1 ve 4 ceyrekte ne toparlandi (kim onde)
  D) Gumus ayi donemleri: 2011 zirvesi -> 2015 dibi ve 2026 zirvesi -> bugun,
     ayni surede varliklarin getirisi

Tarihler: gunluk kapanis TARIHI (saat yok). tz'li gelen index UTC'ye cevrilip
tarihe indirgenir. Hepsi is gunu (B) takvimine ileri doldurularak hizalanir,
boylece 21 is gunu = 1 ay her varlikta ayni (BTC hafta sonlari dusulur).

Kullanim:
  python dongu_backtest.py           # yfinance ile gercek veri
  python dongu_backtest.py --demo    # sentetik veriyle kuru test (ag yok)
Cikti: sonuclar/backtest/  (csv + png + ozet.json + rapor.md); --demo -> sonuclar_demo/
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

KLASOR = Path(__file__).resolve().parent
ALT_KLASOR = "backtest"   # --demo ciktisi sonuclar_demo/ altina gider (git disi)

# ---------------------------------------------------------------------------
# Varsayimlar — hepsi burada, kodun icinde sihirli sabit yok
# ---------------------------------------------------------------------------
BASLANGIC = "1990-01-01"          # yfinance'in verdigi en eski tarihten itibaren
IS_GUNU_AY = 21                   # 1 ay = 21 is gunu
IS_GUNU_YIL = 252

# B) parabolik tepe kurali (testten ONCE yazildi, sonuca gore degistirilmez)
P_GETIRI_12A = 0.80               # 12 aylik getiri >= %80
P_SAPMA_MA200 = 0.40              # fiyat 200 gunluk ortalamanin >= %40 ustunde
P_MA_GUN = 200
TEYIT_DUSUS = -0.25               # tepeden -%25 = tepe TEYIT edildi (islem yapilabilir an)
OLAY_BEKLEME_GUN = 252            # ayni varlikta iki olay arasi en az 1 yil
UFUKLAR_AY = {"1A": 1, "3A": 3, "6A": 6, "12A": 12, "24A": 24}
RASTGELE_TEKRAR = 2000            # placebo: rastgele tarih seti sayisi
TOHUM = 42

# A) analog penceresi
ANALOG_ONCE_GUN = 260             # zirveden once ~1 yil
ANALOG_SONRA_GUN = 1300           # zirveden sonra ~5 yil
ANALOG_2011 = ("2011-01-01", "2011-12-31")
ANALOG_2026 = ("2025-06-01", "2026-06-30")

# C) ortak dusus ceyregi
ORTAK_UCLU = ("gumus", "altin", "nasdaq")
SERT_ESIK = -0.05                 # "sert" surum: ucu de <= -%5

# veri temizligi
SICRAMA_KAT = 5.0                 # bir gunde x5 ya da /5 = veri hatasi ya da yeniden bazlama

VARLIKLAR: dict[str, tuple[str, str]] = {
    "gumus":   ("Gümüş", "SI=F"),
    "altin":   ("Altın", "GC=F"),
    "bakir":   ("Bakır", "HG=F"),
    "platin":  ("Platin", "PL=F"),
    "petrol":  ("Petrol (WTI)", "CL=F"),
    "nasdaq":  ("Nasdaq", "^IXIC"),
    "sp500":   ("S&P 500", "^GSPC"),
    "bist_tl": ("BIST100 (TL)", "XU100.IS"),
    "usdtry":  ("USD/TRY", "USDTRY=X"),
    "tur":     ("Türkiye ETF (TUR, $)", "TUR"),
    "eem":     ("Gelişen Piy. (EEM)", "EEM"),
    "tlt":     ("ABD 20Y Tahvil (TLT)", "TLT"),
    "dxy":     ("Dolar Endeksi", "DX-Y.NYB"),
    "btc":     ("Bitcoin", "BTC-USD"),
}
AD = {k: v[0] for k, v in VARLIKLAR.items()}
AD["bist_usd"] = "BIST100 ($)"
CEKIRDEK = ("gumus", "altin", "nasdaq")       # bunlar yoksa kosu anlamsiz -> cikis 1
OLAY_EVRENI = ("gumus", "altin", "bakir", "platin", "petrol", "nasdaq", "sp500",
               "bist_usd", "tur", "eem", "btc")
SIRALAMA_DISI = ("usdtry",)                   # kur, "varlik" gibi siralanmaz
KRIPTO = ("btc",)                             # olay ozeti ayrica kripto HARIC verilir (BTC ortalamayi ezer)
PENCERE_TOLERANS_GUN = 7                      # D) seri son gunu pencere sonundan en fazla bu kadar eski olabilir

RENK = {"olay": "#C0392B", "baz": "#95A5A6", "y2011": "#7F8C8D", "y2026": "#2C3E50",
        "pozitif": "#27AE60", "negatif": "#C0392B", "vurgu": "#2980B9"}


# ---------------------------------------------------------------------------
# Veri
# ---------------------------------------------------------------------------
def _tarih_duzelt(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    s = pd.Series(np.asarray(s.values, dtype=float), index=idx.normalize()).sort_index()
    return s[~s.index.duplicated(keep="last")]


def indir() -> tuple[dict[str, pd.Series], dict[str, str]]:
    import yfinance as yf
    seriler, hatali = {}, {}
    for anahtar, (_, tk) in VARLIKLAR.items():
        try:
            df = yf.download(tk, start=BASLANGIC, auto_adjust=True, progress=False,
                             threads=False)
            if df is None or len(df) == 0:
                raise RuntimeError("bos yanit")
            k = df["Close"]
            if isinstance(k, pd.DataFrame):
                k = k.iloc[:, 0]
            k = k.dropna()
            if len(k) < 300:
                raise RuntimeError(f"cok kisa seri ({len(k)} gun)")
            seriler[anahtar] = _tarih_duzelt(k)
        except Exception as e:  # bir sembol patlarsa digerleri devam eder, hata ozette
            hatali[anahtar] = f"{tk}: {type(e).__name__}: {e}"
    return seriler, hatali


def sentetik() -> tuple[dict[str, pd.Series], dict[str, str]]:
    """Kuru test icin: GBM + iki gumus balonu + BIST'te yeniden bazlama sicramasi."""
    rng = np.random.default_rng(TOHUM)
    gunler = pd.bdate_range("2000-01-03", "2026-11-20")
    n = len(gunler)
    seriler = {}
    for i, k in enumerate(VARLIKLAR):
        vol = 0.012 + 0.004 * (i % 4)
        r = rng.normal(0.0002, vol, n)
        seriler[k] = pd.Series(100 * np.exp(np.cumsum(r)), index=gunler)
    g = seriler["gumus"].copy()

    def balon(s, bas, tepe, dip, carpan_yukari, carpan_asagi):
        b, t, d = (s.index.get_indexer([pd.Timestamp(x)], method="nearest")[0]
                   for x in (bas, tepe, dip))
        yol = np.ones(len(s))
        yol[b:t] = np.linspace(1, carpan_yukari, t - b)
        yol[t:d] = np.linspace(carpan_yukari, carpan_yukari * carpan_asagi, d - t)
        yol[d:] = carpan_yukari * carpan_asagi
        return s * yol

    g = balon(g, "2010-08-02", "2011-04-25", "2015-12-14", 2.8, 0.28)
    g = balon(g, "2024-11-01", "2026-01-29", "2026-11-20", 3.5, 0.40)
    seriler["gumus"] = g
    b = seriler["bist_tl"].copy()
    b.loc[b.index < pd.Timestamp("2020-07-27")] *= 100   # yeniden bazlama taklidi
    seriler["bist_tl"] = b
    seriler["btc"] = seriler["btc"].loc["2014-09-17":]
    return seriler, {}


def temizle(s: pd.Series) -> tuple[pd.Series, list[str]]:
    """<=0 atilir; tek gunluk sivri hata atilir; kalici sicrama (yeniden bazlama) ->
    onceki gecmis olceklenir. Yapilan her duzeltme not olarak doner (sessiz degil)."""
    notlar = []
    n0 = len(s)
    s = s[s > 0].copy()
    if len(s) < n0:
        notlar.append(f"{n0 - len(s)} adet <=0 fiyat atildi")
    r = s / s.shift(1)
    sivri = (((r > SICRAMA_KAT) & (r.shift(-1) < 1 / SICRAMA_KAT)) |
             ((r < 1 / SICRAMA_KAT) & (r.shift(-1) > SICRAMA_KAT)))
    if sivri.any():
        notlar.append(f"{int(sivri.sum())} tek gunluk sivri nokta atildi")
        s = s[~sivri.fillna(False)]
    r = s / s.shift(1)
    sicrama = r[(r > SICRAMA_KAT) | (r < 1 / SICRAMA_KAT)]
    for t, oran in sicrama.items():
        s.loc[s.index < t] = s.loc[s.index < t] * oran
        notlar.append(f"{t.date()} kalici sicrama x{oran:.4g}: onceki gecmis olceklendi")
    return s, notlar


def panel_kur(ham: dict[str, pd.Series]) -> tuple[dict[str, pd.Series], dict[str, list[str]]]:
    panel, notlar = {}, {}
    for k, s in ham.items():
        s2, nt = temizle(s)
        if nt:
            notlar[k] = nt
        panel[k] = s2.resample("B").last().ffill()
    if "bist_tl" in panel and "usdtry" in panel:
        kur = panel["usdtry"].reindex(panel["bist_tl"].index).ffill()
        panel["bist_usd"] = (panel["bist_tl"] / kur).dropna()
    return panel, notlar


# ---------------------------------------------------------------------------
# A) Gumus 2011 <-> 2026 analog
# ---------------------------------------------------------------------------
def zirve_bul(s: pd.Series, bas: str, son: str) -> tuple[pd.Timestamp, float]:
    w = s.loc[bas:son]
    return w.idxmax(), float(w.max())


def hizala(s: pd.Series, t0: pd.Timestamp) -> pd.Series:
    """Zirveye gore yuzde (0 = zirve), index = zirveden is gunu farki."""
    i0 = s.index.get_loc(t0)
    lo, hi = max(0, i0 - ANALOG_ONCE_GUN), min(len(s), i0 + ANALOG_SONRA_GUN + 1)
    return pd.Series(s.iloc[lo:hi].to_numpy() / s.iloc[i0] - 1,
                     index=np.arange(lo - i0, hi - i0))


def analog(gumus: pd.Series) -> dict:
    t11, p11 = zirve_bul(gumus, *ANALOG_2011)
    t26, p26 = zirve_bul(gumus, *ANALOG_2026)
    y11, y26 = hizala(gumus, t11), hizala(gumus, t26)
    k = int(y26.index.max())                       # bugun: zirveden kac is gunu sonra
    ortak_once = y11.index.intersection(y26.index)
    once = ortak_once[ortak_once <= 0]
    sonra = ortak_once[(ortak_once >= 0) & (ortak_once <= k)]

    def kor(a):
        x, y = np.log1p(y11.loc[a]), np.log1p(y26.loc[a])
        return float(np.corrcoef(x, y)[0, 1]) if len(a) > 5 else None

    rmse = float(np.sqrt(np.mean((y11.loc[sonra] - y26.loc[sonra]) ** 2))) if len(sonra) else None
    simdi = float(gumus.iloc[-1])
    proj = {}
    if k in y11.index:
        taban = 1 + y11.loc[k]
        for etiket, ay in UFUKLAR_AY.items():
            h = k + ay * IS_GUNU_AY
            if h in y11.index and etiket != "1A":
                deg = (1 + y11.loc[h]) / taban - 1
                proj[etiket] = {"degisim": float(deg), "fiyat": float(simdi * (1 + deg))}
        kalan = y11.loc[k:]
        dip_i = int(kalan.idxmin())
        proj["2011_kalan_dip"] = {
            "ek_dusus": float((1 + kalan.min()) / taban - 1),
            "is_gunu_sonra": dip_i - k,
            "fiyat": float(simdi * (1 + kalan.min()) / taban),
        }
    tablo = pd.DataFrame({"zirveden_is_gunu": y11.index, "y2011_yuzde": y11.to_numpy() * 100}).merge(
        pd.DataFrame({"zirveden_is_gunu": y26.index, "y2026_yuzde": y26.to_numpy() * 100}),
        on="zirveden_is_gunu", how="outer").sort_values("zirveden_is_gunu")
    return {
        "zirve_2011": {"tarih": str(t11.date()), "fiyat": p11},
        "zirve_2026": {"tarih": str(t26.date()), "fiyat": p26},
        "son_tarih": str(gumus.index[-1].date()), "son_fiyat": simdi,
        "zirveden_is_gunu": k,
        "dusus_2026_simdi": float(y26.loc[k]),
        "dusus_2011_ayni_gun": float(y11.loc[k]) if k in y11.index else None,
        "en_derin_2026": float(y26.loc[0:k].min()),
        "en_derin_2011_ayni_surede": float(y11.loc[0:k].min()) if k in y11.index else None,
        "korelasyon_zirve_oncesi": kor(once),
        "korelasyon_zirve_sonrasi": kor(sonra),
        "rmse_zirve_sonrasi_puan": rmse * 100 if rmse is not None else None,
        "projeksiyon_2011_tekrarlarsa": proj,
        "_tablo": tablo, "_y11": y11, "_y26": y26,
    }


# ---------------------------------------------------------------------------
# B) Parabolik tepe olay calismasi
# ---------------------------------------------------------------------------
def parabolik_olaylar(s: pd.Series) -> list[tuple[int, int, int | None]]:
    """(kosul_basladigi_i, tepe_i, teyit_i). Tepe = kosul basladiktan sonra -%25'lik
    dusus gelene kadarki en yuksek kapanis. Teyit gunu = tepeden -%25'e ilk degdigi gun
    (tepe ANCAK o gun bilinir; islem yapilabilir an budur)."""
    ma = s.rolling(P_MA_GUN, min_periods=P_MA_GUN).mean()
    g12 = s / s.shift(IS_GUNU_YIL) - 1
    kos = ((g12 >= P_GETIRI_12A) & (s / ma - 1 >= P_SAPMA_MA200)).fillna(False).to_numpy()
    v = s.to_numpy()
    n, i, son_teyit, cikti = len(v), 0, -10 ** 9, []
    while i < n:
        if kos[i] and (i - son_teyit) > OLAY_BEKLEME_GUN:
            tepe_i, tepe, teyit_i = i, v[i], None
            for j in range(i, n):
                if v[j] > tepe:
                    tepe, tepe_i = v[j], j
                elif v[j] <= tepe * (1 + TEYIT_DUSUS):
                    teyit_i = j
                    break
            cikti.append((i, tepe_i, teyit_i))
            if teyit_i is None:
                break
            son_teyit, i = teyit_i, teyit_i + 1
        else:
            i += 1
    return cikti


def _ileri(v: np.ndarray, i: int | None, h: int) -> float:
    if i is None or i + h >= len(v):
        return np.nan
    return float(v[i + h] / v[i] - 1)


def olay_calismasi(panel: dict[str, pd.Series]) -> dict:
    satirlar = []
    for k in OLAY_EVRENI:
        if k not in panel:
            continue
        s = panel[k]
        v = s.to_numpy()
        ma = s.rolling(P_MA_GUN, min_periods=P_MA_GUN).mean().to_numpy()
        g12 = (s / s.shift(IS_GUNU_YIL) - 1).to_numpy()
        for bas_i, tepe_i, teyit_i in parabolik_olaylar(s):
            tepe = v[tepe_i]
            pencere = v[tepe_i: tepe_i + 24 * IS_GUNU_AY + 1]
            dip_rel = int(np.argmin(pencere))
            satir = {
                "varlik": k, "ad": AD[k],
                "kosul_basi": str(s.index[bas_i].date()),
                "tepe_tarih": str(s.index[tepe_i].date()), "tepe": float(tepe),
                "tepede_12a_getiri": float(g12[tepe_i]),
                "tepede_ma200_sapma": float(tepe / ma[tepe_i] - 1),
                "teyit_tarih": str(s.index[teyit_i].date()) if teyit_i is not None else None,
                "teyit_gun_sayisi": (teyit_i - tepe_i) if teyit_i is not None else None,
                "dip_24a_icinde": float(pencere.min() / tepe - 1),
                "dibe_ay": round(dip_rel / IS_GUNU_AY, 1),
                "pencere_tam": len(pencere) == 24 * IS_GUNU_AY + 1,
            }
            if teyit_i is not None:
                sonrasi = v[teyit_i + 1: teyit_i + 24 * IS_GUNU_AY + 1]
                geri = bool((sonrasi >= tepe).any()) if len(sonrasi) else None
                if geri is False and teyit_i + 24 * IS_GUNU_AY >= len(v):
                    geri = None                      # pencere dolmadi, bilinmiyor
                satir["zirve_geri_24a"] = geri
            for et, ay in UFUKLAR_AY.items():
                satir[f"teyitten_{et}"] = _ileri(v, teyit_i, ay * IS_GUNU_AY)
                satir[f"tepeden_{et}"] = _ileri(v, tepe_i, ay * IS_GUNU_AY)
            satirlar.append(satir)
    olaylar = pd.DataFrame(satirlar)

    # baz: ayni varligin TUM gunlerinden ileri getiri ortalamasi
    baz = {}
    for k in OLAY_EVRENI:
        if k not in panel:
            continue
        v = panel[k].to_numpy()
        baz[k] = {}
        for et, ay in UFUKLAR_AY.items():
            h = ay * IS_GUNU_AY
            baz[k][et] = float(np.mean(v[h:] / v[:-h] - 1)) if len(v) > h else np.nan

    rng = np.random.default_rng(TOHUM)
    tumu = _olay_ozeti(olaylar, panel, baz, rng)
    kripto_disi = olaylar[~olaylar["varlik"].isin(KRIPTO)] if len(olaylar) else olaylar
    haric = _olay_ozeti(kripto_disi, panel, baz, rng)
    return {"olaylar": olaylar, "ozet": tumu, "ozet_kripto_haric": haric, "baz": baz}


def _olay_ozeti(olaylar: pd.DataFrame, panel: dict[str, pd.Series], baz: dict,
                rng: np.random.Generator) -> pd.DataFrame:
    ozet = []
    teyitli = olaylar[olaylar["teyit_tarih"].notna()] if len(olaylar) else olaylar
    for et, ay in UFUKLAR_AY.items():
        kol = f"teyitten_{et}"
        d = teyitli[teyitli[kol].notna()] if len(teyitli) else teyitli
        if len(d) == 0:
            ozet.append({"ufuk": et, "n": 0})
            continue
        ort = float(d[kol].mean())
        baz_ort = float(np.mean([baz[a][et] for a in d["varlik"]]))
        # placebo: her olay icin ayni varliktan rastgele bir gun -> setin ortalamasi
        h = ay * IS_GUNU_AY
        havuz = {a: panel[a].to_numpy() for a in d["varlik"].unique()}
        rastgele = np.empty(RASTGELE_TEKRAR)
        for t in range(RASTGELE_TEKRAR):
            ret = []
            for a in d["varlik"]:
                v = havuz[a]
                j = rng.integers(IS_GUNU_YIL, len(v) - h)
                ret.append(v[j + h] / v[j] - 1)
            rastgele[t] = np.mean(ret)
        ozet.append({
            "ufuk": et, "n": int(len(d)),
            "ortalama": ort, "medyan": float(d[kol].median()),
            "pozitif_oran": float((d[kol] > 0).mean()),
            "baz_ortalama": baz_ort, "fark": ort - baz_ort,
            "rastgele_setlerin_yuzde_kaci_daha_dusuk": float((rastgele < ort).mean()),
        })
    return pd.DataFrame(ozet)


# ---------------------------------------------------------------------------
# C) Gumus + altin + Nasdaq ayni ceyrekte dustugunde
# ---------------------------------------------------------------------------
def ceyrek_getirileri(panel: dict[str, pd.Series]) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    fiyat = pd.DataFrame({k: s.resample("QE").last() for k, s in panel.items()})
    son_gun = max(s.index[-1] for s in panel.values())
    getiri = fiyat.pct_change(fill_method=None)
    return fiyat, getiri, son_gun


def ortak_dusus(panel: dict[str, pd.Series]) -> dict:
    fiyat, getiri, son_gun = ceyrek_getirileri(panel)
    son_ceyrek = getiri.index[-1]
    tamamlanmamis = son_gun < son_ceyrek                       # ceyrek henuz bitmedi
    ileri1 = getiri.shift(-1)
    ileri4 = fiyat.shift(-4) / fiyat - 1
    kosullar = {
        "genis": (getiri[list(ORTAK_UCLU)] < 0).all(axis=1),
        "sert": (getiri[list(ORTAK_UCLU)] <= SERT_ESIK).all(axis=1),
    }
    sonuc = {"son_ceyrek": str(son_ceyrek.date()), "son_ceyrek_tamamlanmadi": bool(tamamlanmamis),
             "kosullar": {}}
    tablolar = {}
    for ad, maske in kosullar.items():
        maske = maske & getiri[list(ORTAK_UCLU)].notna().all(axis=1)
        if tamamlanmamis:
            simdi_ortak = bool(maske.iloc[-1])
            maske.iloc[-1] = False                               # eksik ceyrek istatistige girmez
        else:
            simdi_ortak = None
        ceyrekler = getiri.index[maske]
        satirlar = []
        for k in getiri.columns:
            if k in ORTAK_UCLU:
                continue
            es = getiri.loc[maske, k].dropna()
            s1 = ileri1.loc[maske, k].dropna()
            s4 = ileri4.loc[maske, k].dropna()
            tum = getiri[k].dropna()
            tum4 = ileri4[k].dropna()
            if len(es) == 0:
                continue
            satirlar.append({
                "varlik": k, "ad": AD.get(k, k),
                "n": int(len(es)),
                "esnasinda_ort": float(es.mean()), "esnasinda_medyan": float(es.median()),
                "esnasinda_pozitif": float((es > 0).mean()),
                "normal_ceyrek_ort": float(tum.mean()),
                "sonraki_1c_ort": float(s1.mean()) if len(s1) else np.nan,
                "sonraki_4c_ort": float(s4.mean()) if len(s4) else np.nan,
                "sonraki_4c_pozitif": float((s4 > 0).mean()) if len(s4) else np.nan,
                "sonraki_4c_n": int(len(s4)),
                "normal_4c_ort": float(tum4.mean()),
            })
        tablo = pd.DataFrame(satirlar).sort_values("esnasinda_ort", ascending=False)
        liste = getiri.loc[ceyrekler].copy()
        liste.index = [f"{t.year}-Ç{(t.month - 1) // 3 + 1}" for t in liste.index]
        # toparlanma liderligi: her ortak dusus ceyreginden sonraki 4 ceyrekte siralama
        siralar = []
        for t in ceyrekler:
            r4 = ileri4.loc[t].drop(labels=[c for c in SIRALAMA_DISI if c in ileri4.columns]).dropna()
            if len(r4) < 5:
                continue
            sira = r4.rank(ascending=False)
            for k, rk in sira.items():
                siralar.append({"ceyrek": str(t.date()), "varlik": k, "sira": rk,
                                "ilk3": rk <= 3, "katilimci": len(r4), "getiri_4c": float(r4[k])})
        sira_df = pd.DataFrame(siralar)
        if len(sira_df):
            liderlik = (sira_df.groupby("varlik")
                        .agg(ort_sira=("sira", "mean"), ilk3_sayisi=("ilk3", "sum"),
                             gozlem=("sira", "size"), ort_getiri_4c=("getiri_4c", "mean"))
                        .reset_index().sort_values("ort_sira"))
            liderlik["ad"] = liderlik["varlik"].map(lambda x: AD.get(x, x))
        else:
            liderlik = pd.DataFrame()
        tablolar[ad] = {"ozet": tablo, "ceyrekler": liste, "liderlik": liderlik}
        sonuc["kosullar"][ad] = {
            "ceyrek_sayisi": int(maske.sum()),
            "ceyrekler": list(liste.index),
            "simdiki_ceyrek_su_ana_kadar_ortak_dusus": simdi_ortak,
        }
    return {"ozet": sonuc, "tablolar": tablolar, "getiri": getiri}


# ---------------------------------------------------------------------------
# D) Gumus ayi donemleri
# ---------------------------------------------------------------------------
def gumus_ayi(panel: dict[str, pd.Series], a: dict) -> dict:
    g = panel["gumus"]
    t11 = pd.Timestamp(a["zirve_2011"]["tarih"])
    t26 = pd.Timestamp(a["zirve_2026"]["tarih"])
    son = g.index[-1]
    dip11 = g.loc[t11:"2016-12-31"].idxmin()
    sure = son - t26
    pencereler = {
        "2011 zirvesi + aynı süre": (t11, t11 + sure),
        "2026 zirvesi → bugün": (t26, son),
        "2011 zirvesi → 2015 dibi": (t11, dip11),
    }
    satirlar = []
    for k, s in panel.items():
        if k == "usdtry":
            continue
        satir = {"varlik": k, "ad": AD.get(k, k)}
        for et, (b, e) in pencereler.items():
            if s.index[0] > b or s.index[-1] < e - pd.Timedelta(days=PENCERE_TOLERANS_GUN):
                satir[et] = np.nan
                continue
            satir[et] = float(s.asof(e) / s.asof(b) - 1)
        satirlar.append(satir)
    tablo = pd.DataFrame(satirlar)
    return {"pencereler": {k: [str(b.date()), str(e.date())] for k, (b, e) in pencereler.items()},
            "tablo": tablo}


# ---------------------------------------------------------------------------
# Grafikler
# ---------------------------------------------------------------------------
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.25})
    return plt


def grafik_analog(a: dict, yol: Path) -> None:
    plt = _plt()
    y11, y26, k = a["_y11"], a["_y26"], a["zirveden_is_gunu"]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(y11.index / IS_GUNU_AY, y11 * 100, color=RENK["y2011"], lw=1.6,
            label=f"2011 (zirve {a['zirve_2011']['tarih']}, ${a['zirve_2011']['fiyat']:.2f})")
    ax.plot(y26.index / IS_GUNU_AY, y26 * 100, color=RENK["y2026"], lw=2.4,
            label=f"2026 (zirve {a['zirve_2026']['tarih']}, ${a['zirve_2026']['fiyat']:.2f})")
    ax.axvline(0, color="#BBBBBB", lw=1)
    ax.axvline(k / IS_GUNU_AY, color=RENK["vurgu"], lw=1, ls="--")
    d26, d11 = a["dusus_2026_simdi"], a["dusus_2011_ayni_gun"]
    ax.text(0.99, 0.97, f"Bugün (zirveden {k / IS_GUNU_AY:.1f} ay): {d26 * 100:.0f}%\n"
            f"2011 aynı noktada: {(d11 if d11 is not None else float('nan')) * 100:.0f}%",
            transform=ax.transAxes, ha="right", va="top", fontsize=10, color=RENK["vurgu"])
    ax.set_xlabel("Zirveden ay (21 iş günü = 1 ay)")
    ax.set_ylabel("Zirveye göre %")
    if d11 is None:
        baslik = "Gümüş: 2026 zirvesi sonrası, 2011 ile hizalı"
    elif d26 < d11:
        baslik = "Gümüş: aynı sürede 2026 düşüşü 2011'den derin"
    else:
        baslik = "Gümüş: aynı sürede 2026 düşüşü 2011'den sığ"
    ax.set_title(baslik, loc="left", fontweight="bold")
    ax.legend(loc="lower right", frameon=False, bbox_to_anchor=(1.0, 0.0))
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


def grafik_olay(ozet: pd.DataFrame, yol: Path) -> None:
    plt = _plt()
    d = ozet[ozet["n"] > 0]
    if len(d) == 0:
        return
    x = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - 0.2, d["ortalama"] * 100, 0.4, color=RENK["olay"], label="Parabolik tepe teyidinden sonra")
    ax.bar(x + 0.2, d["baz_ortalama"] * 100, 0.4, color=RENK["baz"], label="Aynı varlık, sıradan gün")
    for xi, (_, r) in zip(x, d.iterrows()):
        ax.text(xi - 0.2, r["ortalama"] * 100, f"n={int(r['n'])}", ha="center",
                va="bottom" if r["ortalama"] >= 0 else "top", fontsize=8)
    ax.axhline(0, color="#888888", lw=0.8)
    ax.set_xticks(x, d["ufuk"])
    ax.set_ylabel("Ortalama getiri %")
    ax.set_title("Parabolik tepeler (kripto hariç): teyit gününden sonra ortalama getiri", loc="left", fontweight="bold")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


def grafik_ortak(tablo: pd.DataFrame, n_ceyrek: int, yol: Path) -> None:
    plt = _plt()
    if len(tablo) == 0:
        return
    d = tablo.sort_values("esnasinda_ort")
    y = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(9, 0.42 * len(d) + 1.8))
    ax.barh(y + 0.2, d["esnasinda_ort"] * 100, 0.4,
            color=[RENK["pozitif"] if v > 0 else RENK["negatif"] for v in d["esnasinda_ort"]],
            label="O çeyrekte (ort.)")
    ax.barh(y - 0.2, d["sonraki_4c_ort"] * 100, 0.4, color=RENK["vurgu"], alpha=0.75,
            label="Sonraki 4 çeyrek (ort.)")
    ax.axvline(0, color="#888888", lw=0.8)
    ax.set_yticks(y, d["ad"])
    ax.set_xlabel("%")
    ax.set_title(f"Gümüş + altın + Nasdaq aynı çeyrekte düşünce (n={n_ceyrek})",
                 loc="left", fontweight="bold")
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


def grafik_ayi(tablo: pd.DataFrame, yol: Path) -> None:
    plt = _plt()
    k1, k2 = "2011 zirvesi + aynı süre", "2026 zirvesi → bugün"
    d = tablo.dropna(subset=[k2]).sort_values(k2)
    if len(d) == 0:
        return
    y = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(9, 0.42 * len(d) + 1.8))
    ax.barh(y + 0.2, d[k2] * 100, 0.4, color=RENK["y2026"], label=k2)
    ax.barh(y - 0.2, d[k1] * 100, 0.4, color=RENK["baz"], label=k1)
    ax.axvline(0, color="#888888", lw=0.8)
    ax.set_yticks(y, d["ad"])
    ax.set_xlabel("Toplam getiri %")
    ax.set_title("Gümüş zirve yaptıktan sonra: kim kazandırdı?", loc="left", fontweight="bold")
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Ana akis
# ---------------------------------------------------------------------------
def _yuzde(x) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.1f}%"


def _json_guvenli(o):
    if isinstance(o, dict):
        return {k: _json_guvenli(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [_json_guvenli(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def kos(demo: bool = False) -> int:
    cikti = KLASOR / ("sonuclar_demo" if demo else "sonuclar") / ALT_KLASOR
    cikti.mkdir(parents=True, exist_ok=True)
    ham, hatali = sentetik() if demo else indir()
    eksik = [k for k in CEKIRDEK if k not in ham]
    if eksik:
        print(f"HATA: cekirdek seriler yok: {eksik} | {hatali}", file=sys.stderr)
        return 1
    panel, notlar = panel_kur(ham)
    kapsam = {k: [str(s.index[0].date()), str(s.index[-1].date())] for k, s in panel.items()}

    a = analog(panel["gumus"])
    a["_tablo"].to_csv(cikti / "a_gumus_analog.csv", index=False, encoding="utf-8-sig")
    grafik_analog(a, cikti / "a_gumus_analog.png")

    b = olay_calismasi(panel)
    b["olaylar"].to_csv(cikti / "b_parabolik_olaylar.csv", index=False, encoding="utf-8-sig")
    b["ozet"].to_csv(cikti / "b_parabolik_ozet.csv", index=False, encoding="utf-8-sig")
    b["ozet_kripto_haric"].to_csv(cikti / "b_parabolik_ozet_kripto_haric.csv", index=False,
                                  encoding="utf-8-sig")
    grafik_olay(b["ozet_kripto_haric"], cikti / "b_parabolik_ozet.png")

    c = ortak_dusus(panel)
    for ad, t in c["tablolar"].items():
        t["ozet"].to_csv(cikti / f"c_ortak_dusus_{ad}.csv", index=False, encoding="utf-8-sig")
        t["ceyrekler"].to_csv(cikti / f"c_ortak_dusus_{ad}_ceyrekler.csv", encoding="utf-8-sig")
        t["liderlik"].to_csv(cikti / f"c_toparlanma_liderligi_{ad}.csv", index=False, encoding="utf-8-sig")
    grafik_ortak(c["tablolar"]["genis"]["ozet"], c["ozet"]["kosullar"]["genis"]["ceyrek_sayisi"],
                 cikti / "c_ortak_dusus_genis.png")

    d = gumus_ayi(panel, a)
    d["tablo"].to_csv(cikti / "d_gumus_ayi_donemleri.csv", index=False, encoding="utf-8-sig")
    grafik_ayi(d["tablo"], cikti / "d_gumus_ayi_donemleri.png")

    ozet = {
        "uretim_zamani_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "demo": demo,
        "veri_kapsami": kapsam,
        "hatali": hatali,
        "veri_duzeltmeleri": notlar,
        "kurallar": {
            "parabolik": f"12A getiri >= {P_GETIRI_12A:.0%} ve MA{P_MA_GUN} sapma >= {P_SAPMA_MA200:.0%}; "
                         f"teyit = tepeden {TEYIT_DUSUS:.0%}; olaylar arasi >= {OLAY_BEKLEME_GUN} is gunu",
            "ortak_dusus": f"{'+'.join(ORTAK_UCLU)} ayni takvim ceyreginde < 0 (genis) / <= {SERT_ESIK:.0%} (sert)",
        },
        "A_analog": a,
        "B_parabolik": {"ozet": b["ozet"].to_dict(orient="records"),
                        "ozet_kripto_haric": b["ozet_kripto_haric"].to_dict(orient="records"),
                        "olay_sayisi": int(len(b["olaylar"]))},
        "C_ortak_dusus": c["ozet"],
        "D_gumus_ayi": {"pencereler": d["pencereler"]},
    }
    (cikti / "ozet.json").write_text(json.dumps(_json_guvenli(ozet), ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    (cikti / "rapor.md").write_text(rapor_metni(ozet, b, c, d), encoding="utf-8")
    print(f"tamam: {cikti}  | hatali: {hatali or 'yok'}")
    return 0


def rapor_metni(oz: dict, b: dict, c: dict, d: dict) -> str:
    a = oz["A_analog"]
    satir = [f"# Döngü backtest #1 — {oz['uretim_zamani_utc']}{' (DEMO, sentetik)' if oz['demo'] else ''}", ""]
    satir += ["## A) Gümüş 2011 ↔ 2026",
              f"- Zirve 2011: {a['zirve_2011']['tarih']} ${a['zirve_2011']['fiyat']:.2f} · "
              f"Zirve 2026: {a['zirve_2026']['tarih']} ${a['zirve_2026']['fiyat']:.2f}",
              f"- Bugün ({a['son_tarih']}, zirveden {a['zirveden_is_gunu']} iş günü): "
              f"{_yuzde(a['dusus_2026_simdi'])} · 2011 aynı gün: {_yuzde(a['dusus_2011_ayni_gun'])}",
              f"- Korelasyon (log): zirve öncesi {a['korelasyon_zirve_oncesi']:.2f}, "
              f"zirve sonrası {a['korelasyon_zirve_sonrasi']:.2f}", ""]
    satir += ["## B) Parabolik tepe olayları", f"- Olay sayısı: {len(b['olaylar'])}", ""]
    for baslik, tablo in (("Tüm olaylar", b["ozet"]), ("Kripto hariç", b["ozet_kripto_haric"])):
        satir += [f"**{baslik}**", "",
                  "| ufuk | n | ort. | medyan | pozitif | baz | fark | rastgele < ort. |",
                  "|---|---|---|---|---|---|---|---|"]
        for _, r in tablo.iterrows():
            if r.get("n", 0):
                satir.append(f"| {r['ufuk']} | {int(r['n'])} | {_yuzde(r['ortalama'])} | {_yuzde(r['medyan'])} | "
                             f"{r['pozitif_oran'] * 100:.0f}% | {_yuzde(r['baz_ortalama'])} | {_yuzde(r['fark'])} | "
                             f"{r['rastgele_setlerin_yuzde_kaci_daha_dusuk'] * 100:.0f}% |")
        satir.append("")
    for ad, t in c["tablolar"].items():
        k = oz["C_ortak_dusus"]["kosullar"][ad]
        satir += [f"## C) Ortak düşüş çeyrekleri ({ad}, n={k['ceyrek_sayisi']})",
                  "| varlık | o çeyrek ort. | pozitif | sonraki 4Ç ort. | 4Ç pozitif | normal 4Ç |",
                  "|---|---|---|---|---|---|"]
        for _, r in t["ozet"].iterrows():
            p4 = r["sonraki_4c_pozitif"]
            p4_metin = "—" if np.isnan(p4) else f"{p4 * 100:.0f}%"
            satir.append(f"| {r['ad']} | {_yuzde(r['esnasinda_ort'])} | {r['esnasinda_pozitif'] * 100:.0f}% | "
                         f"{_yuzde(r['sonraki_4c_ort'])} | {p4_metin} | {_yuzde(r['normal_4c_ort'])} |")
        satir.append("")
    satir += ["## D) Gümüş zirvesinden sonra varlıklar", "| varlık | " + " | ".join(d["pencereler"]) + " |",
              "|---|" + "---|" * len(d["pencereler"])]
    for _, r in d["tablo"].iterrows():
        satir.append(f"| {r['ad']} | " + " | ".join(_yuzde(r[p]) for p in d["pencereler"]) + " |")
    satir += ["", "Geçmişin kaydıdır, tahmin değildir. Yatırım tavsiyesi değildir."]
    return "\n".join(satir) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="sentetik veriyle kuru test")
    sys.exit(kos(demo=ap.parse_args().demo))
