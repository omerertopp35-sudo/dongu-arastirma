"""
dongu_zamanlama.py — Backtest #4: "Ay ay bakinca tarihler tutuyor mu?"

Girdi: dongu_1980.py ciktilari (sonuclar/dongu_1980/zirveye_hizali_yollar.csv, gumus_aylik.csv).
Ag kullanmaz.

1) TAKVIM AYI: 2026'yi 1980 ve 2011 ile ayni "zirveden ay" sayisinda karsilastir (RMSE, puan).
2) ESNEME: 2026'nin 1..k. aylari, gecmis dongunun f*1..f*k. aylarina en iyi hangi f ile oturuyor?
   f > 1 -> 2026 o donguyu f kat HIZLI oynuyor. f'nin k ile kararliligi da raporlanir.
3) MEKANIK ESLEME: en iyi f ile gecmis dongunun kilometre taslari (5 yillik dip, zirveyi geri alma)
   2026 takvimine cevrilir. TEK DONGUDEN uydurulmus bir katsayi: senaryo, tahmin degil.

Kullanim: python dongu_zamanlama.py   (once dongu_1980.py calismis olmali)
Cikti: sonuclar/zamanlama/
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from dongu_backtest import KLASOR, _json_guvenli, _plt

GIRDI = KLASOR / "sonuclar" / "dongu_1980"
CIKTI = KLASOR / "sonuclar" / "zamanlama"
ESNEME_ARALIK = (0.10, 6.00, 0.01)    # denenen hiz katsayilari
KARARLILIK_K = (4, 6, 8)              # f'yi bu ay sayilariyla da uydur (kararlilik kontrolu)
AY_AY_ARALIK = (-6, 24)
RENK = {"1980": "#B03A2E", "2011": "#7F8C8D", "2026": "#1B2631", "vurgu": "#2980B9"}


def esneme(gecmis: pd.Series, simdi: pd.Series, k: int) -> tuple[float, float]:
    h = gecmis.dropna()
    d = simdi.loc[1:k].to_numpy()
    en_iyi = (np.nan, np.inf)
    for f in np.arange(*ESNEME_ARALIK):
        xs = np.arange(1, k + 1) * f
        if xs.max() > h.index.max():
            continue
        r = float(np.sqrt(np.mean((np.interp(xs, h.index.to_numpy(), h.to_numpy()) - d) ** 2)))
        if r < en_iyi[1]:
            en_iyi = (float(f), r)
    return en_iyi


def kos() -> int:
    try:
        y = pd.read_csv(GIRDI / "zirveye_hizali_yollar.csv", index_col=0)
        oz = pd.read_csv(GIRDI / "dongu_ozetleri.csv").set_index("dongu")
    except FileNotFoundError as e:
        print(f"HATA: once dongu_1980.py calismali ({e})", file=sys.stderr)
        return 1
    y.columns = [str(c) for c in y.columns]
    oz.index = oz.index.astype(str)
    CIKTI.mkdir(parents=True, exist_ok=True)
    s26 = y["2026"].dropna()
    k = int(s26.index.max())
    zirve26 = pd.Timestamp(oz.loc["2026", "zirve_ay"])

    sonuc = {"bugun_ay": k, "bugun_dusus": float(s26.loc[k]), "donguler": {}}
    for c in ("1980", "2011"):
        ayni_ay = float(np.sqrt(np.mean((y[c].loc[1:k] - s26.loc[1:k]) ** 2)))
        f, r = esneme(y[c], s26, k)
        kararlilik = {f"k={kk}": round(esneme(y[c], s26, kk)[0], 2) for kk in KARARLILIK_K}
        zirve = pd.Timestamp(oz.loc[c, "zirve_ay"])
        ay = lambda t: (pd.Timestamp(t).year - zirve.year) * 12 + (pd.Timestamp(t).month - zirve.month)
        dip_ay = ay(oz.loc[c, "dip_ay"])
        geri = oz.loc[c, "zirveyi_geri_alma_ay"]
        geri_ay = ay(geri) if isinstance(geri, str) else None
        esle = lambda m: (zirve26 + pd.DateOffset(months=int(round(m / f)))).strftime("%Y-%m")
        sonuc["donguler"][c] = {
            "ayni_takvim_ayi_rmse_puan": round(ayni_ay * 100, 1),
            "en_iyi_hiz_katsayisi": round(f, 2), "esnetilmis_rmse_puan": round(r * 100, 1),
            "kararlilik": kararlilik,
            "esdeger_ay_bugun": round(k * f, 1),
            "dip_ay": dip_ay, "dip_2026_eslemesi": esle(dip_ay),
            "zirveyi_geri_alma_ay": geri_ay,
            "zirveyi_geri_alma_2026_eslemesi": esle(geri_ay) if geri_ay is not None else None,
        }

    a, b = AY_AY_ARALIK
    tablo = (y.loc[a:b] * 100).round(1)
    tablo.to_csv(CIKTI / "ay_ay.csv", encoding="utf-8-sig")

    plt = _plt()
    # 1) ayni takvim ayi
    fig, ax = plt.subplots(figsize=(11, 5.6))
    for c, lw in (("1980", 1.6), ("2011", 1.6), ("2026", 2.8)):
        s = y[c].loc[a:b].dropna()
        ax.plot(s.index, s * 100, color=RENK[c], lw=lw, marker="o", ms=3.5, label=c)
    ax.axvline(0, color="#BBBBBB", lw=1)
    ax.axvline(k, color=RENK["vurgu"], lw=1, ls="--")
    d = sonuc["donguler"]
    ax.set_title(f"Aynı ayda karşılaştırınca: 2026, 2011'e ortalama {d['2011']['ayni_takvim_ayi_rmse_puan']:.0f} puan, "
                 f"1980'e {d['1980']['ayni_takvim_ayi_rmse_puan']:.0f} puan uzak", loc="left", fontweight="bold", fontsize=11.5)
    ax.set_xlabel("Zirveden ay")
    ax.set_ylabel("Zirveye göre % (aylık ortalama)")
    ax.set_xticks(range(a, b + 1, 2))
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(CIKTI / "ay_ay.png", dpi=160)
    plt.close(fig)

    # 2) esnetilmis
    f11, f80 = d["2011"]["en_iyi_hiz_katsayisi"], d["1980"]["en_iyi_hiz_katsayisi"]
    ufuk = 30
    fig, ax = plt.subplots(figsize=(11, 5.6))
    for c, f in (("2011", f11), ("1980", f80)):
        s = y[c].dropna()
        s = s[(s.index >= 0) & (s.index / f <= ufuk)]
        ax.plot(s.index / f, s * 100, color=RENK[c], lw=1.6,
                label=f"{c}, zaman ekseni ÷{f:.2f} (2026 bu döngüyü {f:.2f} kat {'hızlı' if f > 1 else 'yavaş'} oynuyor)"
                if f > 1 else f"{c}, zaman ekseni ÷{f:.2f} (2026 bu döngüyü ~{1 / f:.1f} kat yavaş oynuyor)")
    s = s26.loc[0:]
    ax.plot(s.index, s * 100, color=RENK["2026"], lw=2.8, marker="o", ms=4, label="2026")
    ax.axvline(k, color=RENK["vurgu"], lw=1, ls="--")
    dip_x = d["2011"]["dip_ay"] / f11
    if dip_x <= ufuk:
        ax.axvline(dip_x, color=RENK["2011"], lw=1, ls=":")
        ax.text(dip_x, ax.get_ylim()[1] * 0.98 if ax.get_ylim()[1] < 0 else -2, f" 2011 dibinin eşlemesi\n {d['2011']['dip_2026_eslemesi']}",
                fontsize=9, color=RENK["2011"], va="top")
    ax.set_title(f"Zamanı sıkıştırınca: 2026, 2011 döngüsünü ~{f11:.1f} kat hızlı oynuyor (sapma {d['2011']['esnetilmis_rmse_puan']:.0f} puan)",
                 loc="left", fontweight="bold", fontsize=11.5)
    ax.set_xlabel("2026 zirvesinden ay (geçmiş döngüler sıkıştırılmış/esnetilmiş)")
    ax.set_ylabel("Zirveye göre % (aylık ortalama)")
    ax.legend(frameon=False, loc="lower left", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(CIKTI / "esnetilmis.png", dpi=160)
    plt.close(fig)

    sonuc["uretim_zamani_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sonuc["uyari"] = "Hiz katsayisi tek donguden ve 10 aylik veriden uydurulmustur; esleme tarihleri senaryodur, tahmin degildir."
    (CIKTI / "ozet.json").write_text(json.dumps(_json_guvenli(sonuc), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(_json_guvenli(sonuc), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(kos())
