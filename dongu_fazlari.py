"""
dongu_fazlari.py — Backtest #2: "Zirveden sonraki dongu nasil gelisti?"

1) Gumusun 2000'den beri buyuk faz haritasi: zigzag (ZIGZAG_ESIK kadar ters hareket
   gelince tepe/dip teyit edilir), her fazin suresi, buyuklugu ve ayni fazda diger
   varliklarin getirisi.
2) 2011 zirvesinden sonraki tam dongu: dibe kadar gecen sure, dipten sonraki ilk yukselis,
   2011 zirvesinin ne zaman geri alindigi.
3) Bugune iki hizalama, 2011 patikasi uzerinden:
   ZAMAN    -> zirveden ayni is gunu sayisi kadar sonrasi
   DERINLIK -> 2011 patikasinin bugunku dususu ILK gordugu gun
   Her biri icin 2011'de o noktadan sonra ne oldu (3/6/12/24 ay, kalan dip, zirveyi geri alma).

Veri yuklemesi ve temizlik dongu_backtest.py ile ortak. Gecmisin kaydidir, tahmin degildir.

Kullanim:
  python dongu_fazlari.py           # gercek veri
  python dongu_fazlari.py --demo    # sentetik kuru test
Cikti: sonuclar/fazlar/  (fazlar.csv, hizalama.csv, ozet.json, rapor.md, fazlar.png, hizalama.png)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from dongu_backtest import (AD, ANALOG_2011, ANALOG_2026, IS_GUNU_AY, KLASOR, _json_guvenli, _plt,
                            indir, panel_kur, sentetik, zirve_bul)

ALT_KLASOR = "fazlar"
ZIGZAG_ESIK = 0.25            # tepe/dip teyidi: son uctan %25 ters hareket (haftalik kapanis)
FAZ_VARLIKLARI = ("altin", "bakir", "petrol", "nasdaq", "sp500", "bist_usd", "tur", "tlt", "dxy", "btc")
HIZALAMA_UFUK_AY = (3, 6, 12, 24)
ETIKET_ESIK = 0.40            # grafikte yalniz |degisim| >= %40 fazlarin yuzdesi yazilir
RENK = {"gumus": "#455A64", "yukselis": "#2E9E5B", "dusus": "#D0453A", "vurgu": "#2980B9",
        "zaman": "#7F8C8D", "derinlik": "#2C3E50"}


def zigzag(s: pd.Series, esik: float) -> list[dict]:
    """Haftalik seride tepe/dip noktalari. Son nokta TEYITSIZ (henuz esik kadar ters hareket yok)."""
    v, idx = s.to_numpy(), s.index
    pivot, yon, uc = [], 0, 0
    imin = imax = 0
    for i in range(1, len(v)):
        if yon == 0:
            if v[i] < v[imin]:
                imin = i
            if v[i] > v[imax]:
                imax = i
            if v[i] >= v[imin] * (1 + esik):
                pivot.append({"i": imin, "tip": "dip"}); yon, uc = 1, i
            elif v[i] <= v[imax] * (1 - esik):
                pivot.append({"i": imax, "tip": "tepe"}); yon, uc = -1, i
            continue
        if yon == 1:
            if v[i] > v[uc]:
                uc = i
            elif v[i] <= v[uc] * (1 - esik):
                pivot.append({"i": uc, "tip": "tepe"}); yon, uc = -1, i
        else:
            if v[i] < v[uc]:
                uc = i
            elif v[i] >= v[uc] * (1 + esik):
                pivot.append({"i": uc, "tip": "dip"}); yon, uc = 1, i
    if yon != 0:
        pivot.append({"i": uc, "tip": ("tepe" if yon == 1 else "dip"), "teyitsiz": True})
    for p in pivot:
        p["tarih"], p["fiyat"] = idx[p["i"]], float(v[p["i"]])
        p.setdefault("teyitsiz", False)
    return pivot


def _getiri(s: pd.Series | None, b: pd.Timestamp, e: pd.Timestamp) -> float:
    if s is None or s.index[0] > b or s.index[-1] < e - pd.Timedelta(days=7):
        return np.nan
    return float(s.asof(e) / s.asof(b) - 1)


def faz_tablosu(g_haftalik: pd.Series, panel: dict[str, pd.Series]) -> pd.DataFrame:
    p = zigzag(g_haftalik, ZIGZAG_ESIK)
    satirlar = []
    for a, b in zip(p[:-1], p[1:]):
        satir = {
            "baslangic": str(a["tarih"].date()), "bitis": str(b["tarih"].date()),
            "faz": "yükseliş" if b["fiyat"] > a["fiyat"] else "düşüş",
            "gumus_bas": a["fiyat"], "gumus_son": b["fiyat"],
            "gumus_degisim": b["fiyat"] / a["fiyat"] - 1,
            "sure_ay": round((b["tarih"] - a["tarih"]).days / 30.44, 1),
            "bitis_teyitsiz": b["teyitsiz"],
        }
        for k in FAZ_VARLIKLARI:
            satir[k] = _getiri(panel.get(k), a["tarih"], b["tarih"])
        satirlar.append(satir)
    return pd.DataFrame(satirlar)


def dongu_2011(g: pd.Series) -> dict:
    t11, p11 = zirve_bul(g, *ANALOG_2011)
    sonra = g.loc[t11:]
    dip_t = sonra.loc[:"2016-12-31"].idxmin()
    dip = float(sonra.loc[dip_t])
    dipten = g.loc[dip_t:]
    geri = dipten[dipten > p11]
    yeni_zirve_t = geri.index[0] if len(geri) else None
    return {
        "zirve_tarih": str(t11.date()), "zirve": p11,
        "dip_tarih": str(dip_t.date()), "dip": dip, "dusus": dip / p11 - 1,
        "dibe_yil": round((dip_t - t11).days / 365.25, 1),
        "dipten_12a": _getiri(g, dip_t, dip_t + pd.DateOffset(months=12)),
        "zirveyi_geri_alma_tarih": str(yeni_zirve_t.date()) if yeni_zirve_t is not None else None,
        "zirveyi_geri_alma_yil": round((yeni_zirve_t - t11).days / 365.25, 1) if yeni_zirve_t is not None else None,
    }


def hizalama(g: pd.Series, d11: dict) -> tuple[pd.DataFrame, dict]:
    """Kalan dip = 2011 DONGUSUNUN dibi (dongu_2011'deki dip), o noktadan sonra kaldiysa."""
    t11, p11 = zirve_bul(g, *ANALOG_2011)
    dip_j = g.index.get_loc(pd.Timestamp(d11["dip_tarih"])) - g.index.get_loc(t11)
    t26, p26 = zirve_bul(g, *ANALOG_2026)
    i11, i26 = g.index.get_loc(t11), g.index.get_loc(t26)
    k = len(g) - 1 - i26                                 # bugun, zirveden is gunu
    simdi_dusus = float(g.iloc[-1] / p26 - 1)
    yol11 = g.iloc[i11:].to_numpy() / p11 - 1            # 2011 zirvesinden bugune
    j_derinlik = int(np.argmax(yol11 <= simdi_dusus)) if (yol11 <= simdi_dusus).any() else None
    noktalar = {"zaman": k, "derinlik": j_derinlik}
    satirlar, bilgi = [], {"bugun_dusus": simdi_dusus, "zirveden_is_gunu": k}
    for ad, j in noktalar.items():
        if j is None or j >= len(yol11):
            continue
        taban = 1 + yol11[j]
        t = g.index[i11 + j]
        kalan = yol11[j:]
        kalan_dip_rel = dip_j - j if dip_j >= j else None     # 2011 dongu dibine kalan
        geri = np.nonzero(kalan[1:] >= 0)[0] + 1
        bilgi[ad] = {
            "2011_tarih": str(t.date()), "2011_dusus": float(yol11[j]),
            "zirveden_ay": round(j / IS_GUNU_AY, 1),
            "kalan_dip_ek_dusus": float((1 + kalan[kalan_dip_rel]) / taban - 1) if kalan_dip_rel is not None else None,
            "kalan_dibe_ay": round(kalan_dip_rel / IS_GUNU_AY, 1) if kalan_dip_rel is not None else None,
            "zirveye_donus_yil": round(geri[0] / 252, 1) if len(geri) else None,
        }
        for ay in HIZALAMA_UFUK_AY:
            h = j + ay * IS_GUNU_AY
            satirlar.append({"hizalama": ad, "ufuk_ay": ay,
                             "degisim": float((1 + yol11[h]) / taban - 1) if h < len(yol11) else np.nan})
    return pd.DataFrame(satirlar), bilgi


def grafik_fazlar(g_h: pd.Series, p: list[dict], d11: dict, yol) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(11, 5.8))
    ax.plot(g_h.index, g_h, color=RENK["gumus"], lw=1.2, alpha=0.8, label="Gümüş (haftalık kapanış)")
    xs = [q["tarih"] for q in p]
    ys = [q["fiyat"] for q in p]
    ax.plot(xs, ys, color="#111111", lw=1.0, ls="--", alpha=0.6, label=f"Faz çizgisi (±%{ZIGZAG_ESIK * 100:.0f})")
    for a, b in zip(p[:-1], p[1:]):
        deg = b["fiyat"] / a["fiyat"] - 1
        if abs(deg) >= ETIKET_ESIK:
            ax.annotate(f"{deg * 100:+.0f}%", xy=(b["tarih"], b["fiyat"]),
                        xytext=(0, 8 if deg > 0 else -14), textcoords="offset points", ha="center",
                        fontsize=8.5, color=RENK["yukselis"] if deg > 0 else RENK["dusus"])
    ax.axvspan(pd.Timestamp(d11["zirve_tarih"]), pd.Timestamp(d11["dip_tarih"]), color=RENK["dusus"], alpha=0.07)
    if d11["zirveyi_geri_alma_tarih"]:
        ax.axvspan(pd.Timestamp(d11["dip_tarih"]), pd.Timestamp(d11["zirveyi_geri_alma_tarih"]),
                   color=RENK["yukselis"], alpha=0.05)
    ax.set_yscale("log")
    ax.set_yticks([5, 10, 20, 50, 100], ["5", "10", "20", "50", "100"])
    ax.set_ylabel("$/ons (log ölçek)")
    geri = d11["zirveyi_geri_alma_yil"]
    ax.set_title(f"Gümüş: 2011 tepesinden sonra dip {d11['dibe_yil']:.1f} yıl, zirveyi geri almak "
                 f"{geri:.1f} yıl sürdü" if geri else "Gümüş döngü fazları", loc="left", fontweight="bold")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


def grafik_hizalama(tablo: pd.DataFrame, bilgi: dict, yol) -> None:
    plt = _plt()
    if len(tablo) == 0:
        return
    ufuklar = list(HIZALAMA_UFUK_AY)
    x = np.arange(len(ufuklar))
    fig, ax = plt.subplots(figsize=(9, 5))
    for kaydir, ad, renk in ((-0.2, "zaman", RENK["zaman"]), (0.2, "derinlik", RENK["derinlik"])):
        d = tablo[tablo["hizalama"] == ad].set_index("ufuk_ay").reindex(ufuklar)
        if ad not in bilgi:
            continue
        etiket = (f"Zaman hizası: 2011'de {bilgi[ad]['2011_tarih']} sonrası" if ad == "zaman"
                  else f"Derinlik hizası: 2011'de {bilgi[ad]['2011_tarih']} sonrası")
        ax.bar(x + kaydir, d["degisim"] * 100, 0.4, color=renk, label=etiket)
        for xi, v in zip(x + kaydir, d["degisim"]):
            if not np.isnan(v):
                ax.text(xi, v * 100, f"{v * 100:+.0f}%", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    ax.axhline(0, color="#888888", lw=0.8)
    ax.set_xticks(x, [f"+{u} ay" for u in ufuklar])
    ax.set_ylabel("2011'de o noktadan sonraki değişim %")
    ax.set_title(f"Bugünkü noktayı 2011'e iki şekilde hizalayınca (bugün zirveden {bilgi['bugun_dusus'] * 100:.0f}%)",
                 loc="left", fontweight="bold", fontsize=11)
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


def _yuzde(x) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.0f}%"


def kos(demo: bool = False) -> int:
    cikti = KLASOR / ("sonuclar_demo" if demo else "sonuclar") / ALT_KLASOR
    cikti.mkdir(parents=True, exist_ok=True)
    ham, hatali = sentetik() if demo else indir()
    if "gumus" not in ham:
        print(f"HATA: gumus yok | {hatali}", file=sys.stderr)
        return 1
    panel, notlar = panel_kur(ham)
    g = panel["gumus"]
    g_h = g.resample("W-FRI").last().dropna()
    pivotlar = zigzag(g_h, ZIGZAG_ESIK)
    fazlar = faz_tablosu(g_h, panel)
    fazlar.to_csv(cikti / "fazlar.csv", index=False, encoding="utf-8-sig")
    d11 = dongu_2011(g)
    hz, hz_bilgi = hizalama(g, d11)
    hz.to_csv(cikti / "hizalama.csv", index=False, encoding="utf-8-sig")
    grafik_fazlar(g_h, pivotlar, d11, cikti / "fazlar.png")
    grafik_hizalama(hz, hz_bilgi, cikti / "hizalama.png")
    ozet = {"uretim_zamani_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "demo": demo, "hatali": hatali, "veri_duzeltmeleri": notlar,
            "kural": f"zigzag esigi %{ZIGZAG_ESIK * 100:.0f}, haftalik (Cuma) kapanis; son faz teyitsiz",
            "dongu_2011": d11, "hizalama": hz_bilgi}
    (cikti / "ozet.json").write_text(json.dumps(_json_guvenli(ozet), ensure_ascii=False, indent=2), encoding="utf-8")

    sat = [f"# Backtest #2 — zirveden sonraki döngü ({ozet['uretim_zamani_utc']})", "",
           "## Gümüş fazları (zigzag ±%{:.0f}, haftalık)".format(ZIGZAG_ESIK * 100), "",
           "| başlangıç | bitiş | faz | gümüş | süre (ay) | " + " | ".join(AD[k] for k in FAZ_VARLIKLARI) + " |",
           "|---|---|---|---|---|" + "---|" * len(FAZ_VARLIKLARI)]
    for _, r in fazlar.iterrows():
        sat.append(f"| {r['baslangic']} | {r['bitis']}{' (teyitsiz)' if r['bitis_teyitsiz'] else ''} | {r['faz']} | "
                   f"{_yuzde(r['gumus_degisim'])} | {r['sure_ay']} | " +
                   " | ".join(_yuzde(r[k]) for k in FAZ_VARLIKLARI) + " |")
    sat += ["", "## 2011 döngüsü", f"- Zirve {d11['zirve_tarih']} ${d11['zirve']:.2f} → dip {d11['dip_tarih']} "
            f"${d11['dip']:.2f} ({_yuzde(d11['dusus'])}, {d11['dibe_yil']} yıl)",
            f"- Dipten sonraki 12 ay: {_yuzde(d11['dipten_12a'])}",
            f"- 2011 zirvesinin geri alınması: {d11['zirveyi_geri_alma_tarih']} ({d11['zirveyi_geri_alma_yil']} yıl)", "",
            "## Bugünü 2011'e hizalama"]
    for ad in ("zaman", "derinlik"):
        if ad in hz_bilgi:
            b = hz_bilgi[ad]
            sat.append(f"- **{ad}**: 2011'de {b['2011_tarih']} (zirveden {b['zirveden_ay']} ay, {_yuzde(b['2011_dusus'])}); "
                       f"2011 döngü dibine kalan {_yuzde(b['kalan_dip_ek_dusus'])} ({b['kalan_dibe_ay']} ay sonra), "
                       f"o noktadan 2011 zirvesine dönüş {b['zirveye_donus_yil']} yıl")
    sat += ["", "Geçmişin kaydıdır, tahmin değildir. Yatırım tavsiyesi değildir."]
    (cikti / "rapor.md").write_text("\n".join(sat) + "\n", encoding="utf-8")
    print(f"tamam: {cikti} | hatali: {hatali or 'yok'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    sys.exit(kos(demo=ap.parse_args().demo))
