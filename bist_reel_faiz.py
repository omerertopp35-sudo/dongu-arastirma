"""
bist_reel_faiz.py — BIST dongu calismasi, adim 4: reel faiz rejimi.

Soru: TCMB reel politika faizi pozitifken (ya da pozitife dondukten sonra) BIST dolar bazinda ve
gelisen piyasalara (EEM) gore ne yapti?

ON-KAYIT (sonuclar gorulmeden yazildi; kurallar sonradan degistirilmez):
- Reel faiz r_t = (1 + i_t) / (1 + pi_t) - 1. i_t: ay sonu politika faizi (TP.BISPOLFAIZ.TUR, 2002->),
  pi_t: yillik TUFE (bist_dongu zinciri). Saglamlik: 2011-> TCMB agirlikli ortalama fonlama maliyeti
  (TP.APIFON4, aylik ortalama), oncesi politika faizi — 2011-2018 koridor doneminde haftalik repo efektif
  fonlama faizi degildi.
- Bilgi gecikmesi: TUFE(t) t+1'in ilk gunlerinde aciklanir -> r_t ancak t+1 ay sonunda kullanilir.
  Ileri getiriler t+1 ay sonundan olculur (BILGI_GECIKME_AY = 1).
- A) Rejim aylari: her ay icin rejim (r > 0 / r <= 0) -> sonraki ayin BIST $ log getirisi ve EEM'e gore
  fazlasi. Fark (pozitif - negatif) icin bos hipotez: rejim serisini getirilere gore dairesel kaydirma
  (>= KAYDIRMA_ASGARI ay), tum kaydirmalar. Rejimlerin uzun bloklar halinde gelmesini korur.
- B) 2x2: rejim x politika faizinin 6 aylik yonu (indirim: Δ6a < 0 / indirim degil).
- C) Olaylar: r <= 0 en az NEG_ASGARI_AY surdukten sonra r > 0 olan ilk ay; olaylar arasi en az
  OLAY_BEKLEME_AY. BIST $ ve BIST $/EEM yolu -12..+24 ay; +6/+12/+24; ayni sayida rastgele ay ile plasebo.
Ham veri public repoya yazilmaz. Gecmisin kaydidir, tahmin degildir. Cikti: sonuclar/bist_reel_faiz/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from bist_dongu import HAM, SERI, evds, sentetik, tufe_zinciri, yahoo_ay_sonu
from dongu_backtest import KLASOR, _json_guvenli, _plt, temizle

EFEKTIF = ("TP.APIFON4", "avg")
BILGI_GECIKME_AY = 1
NEG_ASGARI_AY = 6
OLAY_BEKLEME_AY = 12
YON_PENCERE_AY = 6
KAYDIRMA_ASGARI = 24
OLAY_ONCE, OLAY_SONRA = 12, 24
UFUKLAR = (6, 12, 24)
PLASEBO_CEKILIS = 2000
TOHUM = 11
HUCRELER = ("negatif · indirim değil", "negatif · indirim", "pozitif · indirim değil", "pozitif · indirim")
RENK = {"poz": "#2a78d6", "neg": "#e34948", "poz_acik": "#cde2fb", "neg_acik": "#f6d3d2", "notr": "#f0efec",
        "murekkep": "#1B2631", "ikincil": "#52514e", "silik": "#9a9994", "olay": "#bdbcb6",
        "fazla": "#eb6834", "simdi": "#eb6834"}


# ---------------------------------------------------------------------------
def veri(demo: bool) -> tuple[dict, list, dict]:
    notlar, hatali = [], {}
    if demo:
        ev, kuresel = sentetik()
        rng = np.random.default_rng(TOHUM)
        p = ev["politika"].loc["2011-01-31":]
        ev["efektif"] = p + rng.normal(2, 1.5, len(p))
    else:
        anahtar = os.environ.get("EVDS_API_KEY", "").strip()
        if not anahtar:
            raise RuntimeError("EVDS_API_KEY yok")
        ev = {}
        for k in ("bist_tl", "usdtry", "tufe_eski", "tufe_2003", "politika"):
            kod, toplama = SERI[k]
            try:
                ev[k] = evds(kod, toplama, anahtar)
            except Exception as e:
                hatali[k] = f"{kod}: {type(e).__name__}: {str(e).replace(anahtar, '***')[:200]}"
        try:
            ev["efektif"] = evds(*EFEKTIF, anahtar)
        except Exception as e:
            hatali["efektif"] = f"{EFEKTIF[0]}: {type(e).__name__}: {str(e).replace(anahtar, '***')[:200]}"
        eksik = [k for k in ("bist_tl", "usdtry", "tufe_eski", "tufe_2003", "politika") if k not in ev]
        if eksik:
            raise RuntimeError(f"cekirdek EVDS serileri eksik: {eksik} {hatali}")
        kuresel, h2 = yahoo_ay_sonu({"eem": "EEM"})
        hatali.update(h2)
    for k in ("bist_tl", "usdtry"):
        ev[k], nt = temizle(ev[k])
        notlar += [f"{k}: {x}" for x in nt]
    tufe, nt = tufe_zinciri(ev["tufe_eski"], ev["tufe_2003"])
    notlar.append(nt)
    df = pd.DataFrame({"bist_tl": ev["bist_tl"], "usdtry": ev["usdtry"], "tufe": tufe}).dropna()
    df["usd"] = df["bist_tl"] / df["usdtry"]
    df["enf"] = df["tufe"] / df["tufe"].shift(12) - 1
    df["politika"] = ev["politika"].reindex(df.index)
    df["reel"] = (1 + df["politika"] / 100) / (1 + df["enf"]) - 1
    if "efektif" in ev:
        eff = ev["efektif"].reindex(df.index)
        df["efektif_faiz"] = eff.where(eff.notna(), df["politika"])
        df["reel_efektif"] = (1 + df["efektif_faiz"] / 100) / (1 + df["enf"]) - 1
        notlar.append(f"efektif faiz: {EFEKTIF[0]} {ev['efektif'].index[0]:%Y-%m}->, oncesi politika faizi")
    if "eem" in kuresel:
        df["eem"] = kuresel["eem"].reindex(df.index)
    df = df.loc[df["politika"].first_valid_index():]
    if not demo:
        HAM.mkdir(exist_ok=True)
        df.to_csv(HAM / "bist_reel_faiz_aylik.csv", index_label="ay")
    return df, notlar, hatali


# ---------------------------------------------------------------------------
def ileri_getiriler(df: pd.DataFrame) -> pd.DataFrame:
    """Sinyal ayi t indeksinde: t+1 ay sonundan itibaren getiriler (log)."""
    L = BILGI_GECIKME_AY
    lu = np.log(df["usd"])
    out = pd.DataFrame(index=df.index)
    out["usd_1a"] = lu.shift(-(L + 1)) - lu.shift(-L)
    if "eem" in df:
        le = np.log(df["eem"])
        out["eem_1a"] = le.shift(-(L + 1)) - le.shift(-L)
        out["fazla_1a"] = out["usd_1a"] - out["eem_1a"]
    for h in UFUKLAR:
        out[f"usd_{h}a"] = lu.shift(-(L + h)) - lu.shift(-L)
        if "eem" in df:
            out[f"fazla_{h}a"] = out[f"usd_{h}a"] - (np.log(df["eem"]).shift(-(L + h)) - np.log(df["eem"]).shift(-L))
    return out


def dairesel_test(rejim: pd.Series, getiri: pd.Series) -> dict:
    d = pd.concat([rejim.rename("x"), getiri.rename("y")], axis=1).dropna()
    x, y = d["x"].to_numpy(bool), d["y"].to_numpy(float)
    n = len(d)
    if x.all() or (~x).all() or n < 2 * KAYDIRMA_ASGARI + 1:
        return {"n": n, "fark": np.nan, "p": np.nan, "kaydirma": 0}
    gercek = y[x].mean() - y[~x].mean()
    bos = []
    for k in range(KAYDIRMA_ASGARI, n - KAYDIRMA_ASGARI + 1):
        xs = np.roll(x, k)
        if xs.all() or (~xs).all():
            continue
        bos.append(y[xs].mean() - y[~xs].mean())
    bos = np.asarray(bos)
    return {"n": n, "fark": float(gercek), "p": float(np.mean(np.abs(bos) >= abs(gercek))),
            "yuzdelik": float(np.mean(bos <= gercek) * 100), "kaydirma": int(len(bos))}


def _yillik(m: float) -> float:
    return float(np.expm1(m * 12)) if np.isfinite(m) else np.nan


def rejim_ozeti(maske: pd.Series, ileri: pd.Series, ileri12: pd.Series) -> dict:
    y = ileri[maske.reindex(ileri.index).fillna(False).astype(bool)].dropna()
    y12 = ileri12[maske.reindex(ileri12.index).fillna(False).astype(bool)].dropna()
    return {"ay": int(len(y)), "yillik_ort": _yillik(y.mean()) if len(y) else np.nan,
            "aylik_medyan": float(np.expm1(y.median())) if len(y) else np.nan,
            "pozitif_ay_orani": float((y > 0).mean()) if len(y) else np.nan,
            "ileri12_medyan": float(np.expm1(y12.median())) if len(y12) else np.nan}


def hucre(df: pd.DataFrame, kolon: str) -> pd.Series:
    poz = df[kolon] > 0
    ind = df["politika"].diff(YON_PENCERE_AY) < 0
    h = pd.Series(np.where(poz, np.where(ind, HUCRELER[3], HUCRELER[2]), np.where(ind, HUCRELER[1], HUCRELER[0])),
                  index=df.index)
    return h.where(df[kolon].notna() & df["politika"].diff(YON_PENCERE_AY).notna())


def bloklar(rejim: pd.Series) -> list[dict]:
    r = rejim.dropna().astype(bool)
    out, bas = [], None
    for t, v in r.items():
        if bas is None or v != onceki:
            if bas is not None:
                out.append({"bas": bas, "bit": son, "pozitif": bool(onceki)})
            bas = t
        onceki, son = v, t
    if bas is not None:
        out.append({"bas": bas, "bit": son, "pozitif": bool(onceki)})
    return out


def olaylari_bul(r: pd.Series) -> list[pd.Timestamp]:
    olay, neg, son = [], 0, None
    for t, v in r.dropna().items():
        if v > 0:
            if neg >= NEG_ASGARI_AY and (son is None or (t.year - son.year) * 12 + t.month - son.month >= OLAY_BEKLEME_AY):
                olay.append(t)
                son = t
            neg = 0
        else:
            neg += 1
    return olay


def olay_yolu(seri: pd.Series, t: pd.Timestamp) -> pd.Series:
    s = seri.dropna()
    i0 = s.index.get_indexer([t])[0]
    if i0 < 0:
        return pd.Series(dtype=float)
    i = i0 + BILGI_GECIKME_AY
    if i >= len(s):
        return pd.Series(dtype=float)
    lo, hi = max(0, i - OLAY_ONCE), min(len(s), i + OLAY_SONRA + 1)
    return pd.Series(s.iloc[lo:hi].to_numpy() / s.iloc[i] - 1, index=np.arange(lo - i, hi - i))


def olay_tablosu(df: pd.DataFrame, ileri: pd.DataFrame, olaylar: list, kolon: str) -> pd.DataFrame:
    rel = df["usd"] / df["eem"] if "eem" in df else None
    satir = []
    for t in olaylar:
        yol = olay_yolu(df["usd"], t)
        s = {"olay_ayi": f"{t:%Y-%m}", "bilgi_ayi": f"{t + pd.DateOffset(months=BILGI_GECIKME_AY) + pd.offsets.MonthEnd(0):%Y-%m}",
             "reel_faiz": float(df.at[t, kolon]), "politika": float(df.at[t, "politika"]), "enflasyon": float(df.at[t, "enf"]),
             "bist_usd_12a_icinde_dip": float(yol.loc[0:12].min()) if len(yol) else np.nan}
        for h in UFUKLAR:
            v = ileri.at[t, f"usd_{h}a"]
            s[f"bist_usd_{h}a"] = float(np.expm1(v)) if pd.notna(v) else np.nan
            if f"fazla_{h}a" in ileri:
                v = ileri.at[t, f"fazla_{h}a"]
                s[f"eem_fazla_{h}a"] = float(np.expm1(v)) if pd.notna(v) else np.nan
        s["bist_usd_gunumuze"] = float(df["usd"].iloc[-1] / df["usd"].asof(t + pd.DateOffset(months=BILGI_GECIKME_AY) + pd.offsets.MonthEnd(0)) - 1)
        if rel is not None:
            t1 = t + pd.DateOffset(months=BILGI_GECIKME_AY) + pd.offsets.MonthEnd(0)
            s["eem_fazla_gunumuze"] = float(rel.iloc[-1] / rel.asof(t1) - 1) if pd.notna(rel.asof(t1)) else np.nan
        satir.append(s)
    return pd.DataFrame(satir)


def plasebo(ileri: pd.DataFrame, olaylar: list, kolon: str) -> dict:
    rng = np.random.default_rng(TOHUM)
    seri = ileri[kolon].dropna()
    gercek = seri.reindex(olaylar).dropna()
    if len(gercek) < 2:
        return {"n": int(len(gercek))}
    ort = np.array([rng.choice(seri.to_numpy(), len(gercek), replace=False).mean() for _ in range(PLASEBO_CEKILIS)])
    return {"n": int(len(gercek)), "olay_ort": float(np.expm1(gercek.mean())), "olay_medyan": float(np.expm1(gercek.median())),
            "tum_aylar_medyan": float(np.expm1(seri.median())), "plasebo_yuzdelik": float(np.mean(ort <= gercek.mean()) * 100)}


# ---------------------------------------------------------------------------
def _yuzde(v, ondalik=0) -> str:
    return "—" if v is None or not np.isfinite(v) else f"{v * 100:+.{ondalik}f}%".replace(".", ",")


def _golgele(ax, blok_listesi):
    for b in blok_listesi:
        ax.axvspan(b["bas"] - pd.offsets.MonthBegin(1), b["bit"], lw=0, zorder=0,
                   color=RENK["poz_acik"] if b["pozitif"] else RENK["neg_acik"], alpha=0.55)


def grafik_rejim(df: pd.DataFrame, olaylar: list, ozet: dict, yol) -> None:
    plt = _plt()
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.ticker import FuncFormatter, NullFormatter
    fig, ax = plt.subplots(3, 1, figsize=(11, 10), sharex=True, gridspec_kw={"height_ratios": [1.5, 2, 1.6], "hspace": 0.1})
    r = df["reel"] * 100
    ax[0].fill_between(r.index, 0, r, where=r > 0, color=RENK["poz"], alpha=0.35, lw=0, step="mid")
    ax[0].fill_between(r.index, 0, r, where=r <= 0, color=RENK["neg"], alpha=0.35, lw=0, step="mid")
    ax[0].plot(r.index, r, color=RENK["murekkep"], lw=1.4, label="politika faizi ile")
    if "reel_efektif" in df:
        re_ = (df["reel_efektif"] * 100).loc["2011-01-31":]
        ax[0].plot(re_.index, re_, color=RENK["silik"], lw=1.2, ls="--", label="efektif fonlama faizi ile (2011→)")
    ax[0].axhline(0, color=RENK["ikincil"], lw=0.8)
    ax[0].set_ylim(max(r.min() - 3, -45), min(r.max() + 3, 30))
    ax[0].set_ylabel("reel faiz, %")
    ax[0].legend(frameon=False, fontsize=8.5, loc="lower left", ncol=2)
    for t in olaylar:
        for a in ax:
            a.axvline(t, color=RENK["ikincil"], lw=0.9, ls=":")
        ax[0].annotate(f"{t:%Y-%m}", xy=(t, ax[0].get_ylim()[1]), xytext=(2, -11), textcoords="offset points",
                       fontsize=7.5, color=RENK["ikincil"])
    # rejim, bilindigi ana kaydirilmis (golgeler "yatirimcinin bildigi" rejim)
    bilinen = (df["reel"] > 0).where(df["reel"].notna()).shift(BILGI_GECIKME_AY)
    bl = bloklar(bilinen)
    _golgele(ax[1], bl)
    ax[1].plot(df.index, df["usd"], color=RENK["murekkep"], lw=1.6)
    ax[1].set_yscale("log")
    ax[1].yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:,.0f}".replace(",", ".") if v >= 1 else f"{v:.2g}"))
    ax[1].yaxis.set_minor_formatter(NullFormatter())
    ax[1].set_ylabel("BIST100 ($, log)")
    if "eem" in df:
        rel = (df["usd"] / df["eem"]).dropna()
        rel = rel / rel.iloc[0] * 100
        _golgele(ax[2], bl)
        ax[2].plot(rel.index, rel, color=RENK["murekkep"], lw=1.6)
        ax[2].axhline(100, color=RENK["ikincil"], lw=0.8)
        ax[2].set_yscale("log")
        ax[2].yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:,.0f}".replace(",", ".")))
        ax[2].yaxis.set_minor_formatter(NullFormatter())
        ax[2].set_ylabel(f"BIST $ / EEM\n({rel.index[0]:%Y-%m} = 100, log)")
    a = ozet["A_rejim"]["politika"]
    ax[0].set_title(f"Reel faiz pozitifken BIST $ yıllık ort. {_yuzde(a['pozitif']['usd']['yillik_ort'])}, "
                    f"negatifken {_yuzde(a['negatif']['usd']['yillik_ort'])} "
                    f"(fark p={a['test_usd']['p']:.2f}; EEM'e göre fark p={a['test_fazla']['p']:.2f})",
                    loc="left", fontweight="bold", fontsize=11)
    el = [Patch(color=RENK["poz_acik"], label="reel faiz pozitif (bilindiği aya kaydırılmış)"),
          Patch(color=RENK["neg_acik"], label="reel faiz negatif"),
          Line2D([], [], color=RENK["ikincil"], ls=":", lw=0.9, label=f"pozitife dönüş (≥{NEG_ASGARI_AY} ay negatiften sonra)")]
    ax[2].legend(handles=el, frameon=False, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3)
    ax[2].text(1.0, -0.36, "Reel faiz = (1+politika faizi)/(1+yıllık TÜFE)−1. Kaynak: TCMB EVDS, Yahoo (EEM).",
               transform=ax[2].transAxes, ha="right", fontsize=8, color="#777777")
    fig.savefig(yol, dpi=160, bbox_inches="tight")
    plt.close(fig)


def grafik_karsilastirma(ozet: dict, simdi: str, yol) -> None:
    plt = _plt()
    A, B = ozet["A_rejim"]["politika"], ozet["B_hucre"]["politika"]
    gruplar = [("Negatif\nreel faiz", A["negatif"]), ("Pozitif\nreel faiz", A["pozitif"])]
    gruplar += [(k.replace(" · ", "\n"), B[k]) for k in HUCRELER]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    x = np.arange(len(gruplar)) + np.array([0, 0, 0.6, 0.6, 0.6, 0.6])
    w = 0.36
    for j, (anahtar, renk, ad) in enumerate((("usd", RENK["murekkep"], "BIST $"), ("fazla", RENK["fazla"], "BIST $ − EEM (Türkiye farkı)"))):
        deg = [g[1][anahtar]["yillik_ort"] * 100 if g[1].get(anahtar) else np.nan for g in gruplar]
        cubuk = ax.bar(x + (j - 0.5) * (w + 0.02), deg, w, color=renk, label=ad, zorder=2)
        for c, v in zip(cubuk, deg):
            if np.isfinite(v):
                ax.annotate(f"{v:+.0f}%", xy=(c.get_x() + c.get_width() / 2, v), xytext=(0, 3 if v >= 0 else -11),
                            textcoords="offset points", ha="center", fontsize=8.5, color=RENK["murekkep"])
    ax.axhline(0, color=RENK["ikincil"], lw=0.8)
    ax.axvline(1.8, color=RENK["olay"], lw=1)
    etiketler = [f"{g[0]}\n({g[1]['usd']['ay']} ay)" for g in gruplar]
    ax.set_xticks(x, etiketler, fontsize=8.8)
    kalin = [1 if simdi.startswith("pozitif") else 0] + ([2 + HUCRELER.index(simdi)] if simdi in HUCRELER else [])
    for i in kalin:
        ax.get_xticklabels()[i].set_fontweight("bold")
    ax.set_ylabel("sonraki ay getirisi, yıllıklandırılmış ort. (%)")
    ax.grid(axis="y", color="#e6e5e1", lw=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.set_title("Reel faiz rejimine göre BIST: solda işaret, sağda işaret × faizin son 6 aylık yönü",
                 loc="left", fontweight="bold", fontsize=11)
    ax.text(1.0, -0.2, f"Kalın etiket: şu anki rejim ({simdi}). Sinyal ayından {BILGI_GECIKME_AY} ay sonra başlayan aylık getiriler. "
            f"Fark testi: dairesel kaydırma, p(BIST $)={A['test_usd']['p']:.2f}, p(EEM farkı)={A['test_fazla']['p']:.2f}.",
            transform=ax.transAxes, ha="right", fontsize=8, color="#777777")
    fig.savefig(yol, dpi=160, bbox_inches="tight")
    plt.close(fig)


def suren_olay(r: pd.Series, olaylar: list) -> str | None:
    if not olaylar:
        return None
    sonra = r.loc[olaylar[-1]:].dropna()
    return f"{olaylar[-1]:%Y-%m}" if len(sonra) and (sonra > 0).all() else None


def grafik_olaylar(df: pd.DataFrame, olaylar: list, yol) -> pd.DataFrame:
    plt = _plt()
    seriler = {"BIST $": df["usd"]}
    if "eem" in df:
        seriler["BIST $ / EEM (Türkiye farkı)"] = df["usd"] / df["eem"]
    fig, axlar = plt.subplots(1, len(seriler), figsize=(11, 5.2), sharey=False)
    axlar = np.atleast_1d(axlar)
    tablolar = {}
    for ax, (ad, s) in zip(axlar, seriler.items()):
        yollar = pd.DataFrame({f"{t:%Y-%m}": olay_yolu(s, t) for t in olaylar})
        tablolar[ad] = yollar
        son = suren_olay(df["reel"], olaylar)
        for k in yollar.columns:
            y = yollar[k].dropna()
            if k == son:
                continue
            ax.plot(y.index, y * 100, color=RENK["olay"], lw=1.1)
            if len(y):
                ax.annotate(k, xy=(y.index[-1], y.iloc[-1] * 100), xytext=(3, 0), textcoords="offset points",
                            fontsize=7, color=RENK["silik"], va="center")
        tamam = yollar.drop(columns=[son]) if son else yollar
        med = tamam.median(axis=1)
        ax.plot(med.index, med * 100, color=RENK["murekkep"], lw=2.4, label=f"medyan (n={tamam.shape[1]}, şimdiki hariç)")
        if son:
            y = yollar[son].dropna()
            ax.plot(y.index, y * 100, color=RENK["simdi"], lw=2.2, label=f"şimdiki ({son})")
            ax.annotate(f"{y.iloc[-1] * 100:+.0f}%", xy=(y.index[-1], y.iloc[-1] * 100), xytext=(4, 0),
                        textcoords="offset points", fontsize=8.5, color=RENK["murekkep"], fontweight="bold", va="center")
        ax.axvline(0, color=RENK["ikincil"], lw=0.9)
        ax.axhline(0, color=RENK["ikincil"], lw=0.8)
        ax.set_title(ad, loc="left", fontsize=10, fontweight="bold")
        ax.set_xlabel("ay (0 = pozitife dönüşün bilindiği ay sonu)")
        ax.grid(axis="y", color="#e6e5e1", lw=0.6)
        ax.legend(frameon=False, fontsize=8, loc="lower left")
    axlar[0].set_ylabel("başlangıca göre %")
    fig.suptitle("Reel faiz pozitife döndükten sonra: tek tek olaylar (gri), medyan (siyah), şimdiki (turuncu)",
                 x=0.01, ha="left", fontweight="bold", fontsize=11)
    fig.tight_layout()
    fig.savefig(yol, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return tablolar.get("BIST $ / EEM (Türkiye farkı)", tablolar["BIST $"])


# ---------------------------------------------------------------------------
def analiz(df: pd.DataFrame, kolon: str, ileri: pd.DataFrame) -> dict:
    poz = (df[kolon] > 0).where(df[kolon].notna())
    out = {"pozitif": {}, "negatif": {}}
    for ad, m in (("pozitif", poz == True), ("negatif", poz == False)):  # noqa: E712
        out[ad]["usd"] = rejim_ozeti(m, ileri["usd_1a"], ileri["usd_12a"])
        if "fazla_1a" in ileri:
            out[ad]["fazla"] = rejim_ozeti(m, ileri["fazla_1a"], ileri["fazla_12a"])
    out["test_usd"] = dairesel_test(poz, ileri["usd_1a"])
    out["test_fazla"] = dairesel_test(poz, ileri["fazla_1a"]) if "fazla_1a" in ileri else {}
    bl = bloklar(poz)
    out["blok_sayisi"] = {"pozitif": sum(b["pozitif"] for b in bl), "negatif": sum(not b["pozitif"] for b in bl)}
    return out


def hucre_analizi(df: pd.DataFrame, kolon: str, ileri: pd.DataFrame) -> dict:
    h = hucre(df, kolon)
    out = {}
    for k in HUCRELER:
        m = h == k
        out[k] = {"usd": rejim_ozeti(m, ileri["usd_1a"], ileri["usd_12a"])}
        # SONRADAN EKLENDI (sonuclar goruldukten sonra, yalniz temkin icin): hucre vs geri kalan, dairesel kaydirma
        mx = m.where(h.notna())
        out[k]["test_usd"] = dairesel_test(mx, ileri["usd_1a"])
        if "fazla_1a" in ileri:
            out[k]["fazla"] = rejim_ozeti(m, ileri["fazla_1a"], ileri["fazla_12a"])
            out[k]["test_fazla"] = dairesel_test(mx, ileri["fazla_1a"])
    return out


def kos(demo: bool = False) -> int:
    cikti = KLASOR / ("sonuclar_demo" if demo else "sonuclar") / "bist_reel_faiz"
    cikti.mkdir(parents=True, exist_ok=True)
    try:
        df, notlar, hatali = veri(demo)
    except Exception as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    ileri = ileri_getiriler(df)
    kolonlar = ["reel"] + (["reel_efektif"] if "reel_efektif" in df else [])
    ad = {"reel": "politika", "reel_efektif": "efektif"}
    A = {ad[k]: analiz(df, k, ileri) for k in kolonlar}
    B = {ad[k]: hucre_analizi(df, k, ileri) for k in kolonlar}
    olay = {ad[k]: olaylari_bul(df[k]) for k in kolonlar}
    olay_tab = {ad[k]: olay_tablosu(df, ileri, olay[ad[k]], k) for k in kolonlar}
    plas = {}
    for k in kolonlar:
        plas[ad[k]] = {f"{s}_{h}a": plasebo(ileri, olay[ad[k]], f"{s}_{h}a") for s in ("usd", "fazla") for h in UFUKLAR
                       if f"{s}_{h}a" in ileri}

    h_son = hucre(df, "reel").dropna()
    simdi = h_son.iloc[-1] if len(h_son) else "?"
    son = df["reel"].last_valid_index()
    ozet = {"uretim_zamani_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "demo": demo,
            "veri": {"ilk_ay": f"{df.index[0]:%Y-%m}", "son_ay": f"{son:%Y-%m}",
                     "eem_ilk": f"{df['eem'].first_valid_index():%Y-%m}" if "eem" in df else None},
            "notlar": notlar, "hatali": hatali,
            "kurallar": {"reel_faiz": "(1+i)/(1+yillik TUFE)-1", "bilgi_gecikmesi_ay": BILGI_GECIKME_AY,
                         "olay": f">= {NEG_ASGARI_AY} ay r<=0 sonra ilk r>0, olaylar arasi >= {OLAY_BEKLEME_AY} ay",
                         "yon": f"politika faizi {YON_PENCERE_AY} aylik degisim < 0 = indirim",
                         "test": f"dairesel kaydirma >= {KAYDIRMA_ASGARI} ay, tum kaydirmalar; plasebo {PLASEBO_CEKILIS} cekilis"},
            "simdi": {"ay": f"{son:%Y-%m}", "reel_faiz": float(df.at[son, "reel"]), "politika": float(df.at[son, "politika"]),
                      "enflasyon": float(df.at[son, "enf"]), "hucre": simdi,
                      "politika_6a_degisim": float(df["politika"].diff(YON_PENCERE_AY).at[son]),
                      "efektif_son": ({"ay": f"{df['efektif_faiz'].last_valid_index():%Y-%m}",
                                       "faiz": float(df["efektif_faiz"].dropna().iloc[-1]),
                                       "reel": float(df["reel_efektif"].dropna().iloc[-1])} if "reel_efektif" in df else None)},
            "A_rejim": A, "B_hucre": B,
            "C_olaylar": {k: v.to_dict(orient="records") for k, v in olay_tab.items()}, "C_plasebo": plas}
    (cikti / "ozet.json").write_text(json.dumps(_json_guvenli(ozet), ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in olay_tab.items():
        v.to_csv(cikti / f"olaylar_{k}.csv", index=False, encoding="utf-8-sig")

    grafik_rejim(df, olay["politika"], ozet, cikti / "reel_faiz_rejim.png")
    grafik_karsilastirma(ozet, simdi, cikti / "reel_faiz_karsilastirma.png")
    yollar = grafik_olaylar(df, olay["politika"], cikti / "reel_faiz_olaylar.png")
    (yollar * 100).round(1).to_csv(cikti / "olay_yollari_eem_farki.csv", encoding="utf-8-sig", index_label="ay")

    sat = [f"# BIST adım 4 — reel faiz rejimi ({ozet['uretim_zamani_utc']}{', DEMO' if demo else ''})", "",
           f"Veri {ozet['veri']['ilk_ay']}→{ozet['veri']['son_ay']} aylık (TCMB EVDS; EEM Yahoo). Ham veri yayımlanmaz.",
           f"Kurallar: {json.dumps(ozet['kurallar'], ensure_ascii=False)}", "",
           f"**Şu an ({ozet['simdi']['ay']}):** reel faiz {_yuzde(ozet['simdi']['reel_faiz'], 1)}, politika %{ozet['simdi']['politika']:.1f}, "
           f"yıllık TÜFE {_yuzde(ozet['simdi']['enflasyon'], 1)}, 6 aylık faiz değişimi {ozet['simdi']['politika_6a_degisim']:+.1f} puan → **{simdi}**", ""]
    for k in A:
        a = A[k]
        sat += [f"## A) Rejim ayları — {k}", "",
                "| rejim | ay | BIST $ yıllık ort. | aylık medyan | + ay oranı | ileri 12a medyan | EEM farkı yıllık ort. | EEM farkı ileri 12a medyan |",
                "|---|---|---|---|---|---|---|---|"]
        for r in ("negatif", "pozitif"):
            u, f = a[r]["usd"], a[r].get("fazla", {})
            sat.append(f"| {r} | {u['ay']} | {_yuzde(u['yillik_ort'])} | {_yuzde(u['aylik_medyan'], 1)} | {u['pozitif_ay_orani'] * 100:.0f}% | "
                       f"{_yuzde(u['ileri12_medyan'])} | {_yuzde(f.get('yillik_ort'))} | {_yuzde(f.get('ileri12_medyan'))} |")
        sat += ["", f"Fark testi (dairesel kaydırma, {a['test_usd'].get('kaydirma')} kaydırma): BIST $ p={a['test_usd']['p']:.2f}; "
                f"EEM farkı p={a['test_fazla'].get('p', float('nan')):.2f}. Bağımsız blok: {a['blok_sayisi']}.", "",
                f"## B) İşaret × faiz yönü — {k}", "",
                "| hücre | ay | BIST $ yıllık ort. | EEM farkı yıllık ort. | BIST $ ileri 12a medyan | p (BIST $, hücre vs geri kalan)* | p (EEM farkı)* |",
                "|---|---|---|---|---|---|---|"]
        for h in HUCRELER:
            u, f = B[k][h]["usd"], B[k][h].get("fazla", {})
            tu, tf = B[k][h].get("test_usd", {}), B[k][h].get("test_fazla", {})
            sat.append(f"| {h} | {u['ay']} | {_yuzde(u['yillik_ort'])} | {_yuzde(f.get('yillik_ort'))} | {_yuzde(u['ileri12_medyan'])} | "
                       f"{tu.get('p', float('nan')):.2f} | {tf.get('p', float('nan')):.2f} |")
        sat += ["", "*Hücre testleri sonuçlar görüldükten sonra eklendi (ön-kayıtta yoktu); yalnız temkin için, kanıt sayılmaz."]
        sat += ["", f"## C) Pozitife dönüş olayları — {k}", "",
                "| olay | bilindi | reel | politika | TÜFE | 12a içi dip | BIST $ +6 | +12 | +24 | EEM farkı +6 | +12 | +24 | BIST $ bugüne |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, o in olay_tab[k].iterrows():
            sat.append(f"| {o['olay_ayi']} | {o['bilgi_ayi']} | {_yuzde(o['reel_faiz'], 1)} | %{o['politika']:.1f} | {_yuzde(o['enflasyon'], 1)} | "
                       f"{_yuzde(o['bist_usd_12a_icinde_dip'])} | " + " | ".join(_yuzde(o.get(f"bist_usd_{h}a")) for h in UFUKLAR) + " | "
                       + " | ".join(_yuzde(o.get(f"eem_fazla_{h}a")) for h in UFUKLAR) + f" | {_yuzde(o['bist_usd_gunumuze'])} |")
        sat.append("")
        for kk, p in plas[k].items():
            if p.get("n", 0) >= 2:
                sat.append(f"- plasebo {kk}: n={p['n']}, olay ort. {_yuzde(p['olay_ort'])}, medyan {_yuzde(p['olay_medyan'])}, "
                           f"tüm aylar medyanı {_yuzde(p['tum_aylar_medyan'])}, plasebo yüzdeliği {p['plasebo_yuzdelik']:.0f}")
        sat.append("")
    sat += ["Geçmişin kaydıdır, tahmin değildir. Yatırım tavsiyesi değildir."]
    (cikti / "rapor.md").write_text("\n".join(sat) + "\n", encoding="utf-8")
    print(f"tamam: {cikti} | hatali: {hatali or 'yok'} | olaylar: { {k: [f'{t:%Y-%m}' for t in v] for k, v in olay.items()} }")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="sentetik veriyle kuru test (ag yok)")
    sys.exit(kos(demo=ap.parse_args().demo))
