"""
evds_akim.py — Haftalik sermaye akimlari (EVDS): yurt disi yerlesiklerin menkul kiymet net alim/satimi
ve yurt ici yerlesiklerin doviz mevduati (DTH). Rezerv degisimini kimin surukledigine bakmak icin.

Seri kodlari tahmin edilmez: EVDS metadata (datagroups / serieList) okunur, haftalik gruplar ADLARINDAN
bulunur; bulunan grup/seri adlari ciktiya yazilir (denetlenebilir). Anahtar EVDS_API_KEY, ciktiya yazilmaz.
Cikti: sonuclar/akim/ (son haftalarin ozet tablosu + grafik + kesif listesi).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from dongu_backtest import KLASOR, _json_guvenli, _plt
from evds_rezerv import Evds, _ad, _norm

CIKTI = KLASOR / "sonuclar" / "akim"
GERI_GUN = 750
SON_HAFTA = 10
GRUP_ANAHTAR = ("yurt dışı yerleşik", "yurt disinda yerlesik", "yurtdışı yerleşik", "non-resident", "nonresident",
                "menkul kıymet", "döviz tevdiat", "döviz mevduat", "yurt içi yerleşik")
RENK = {"hisse": "#2a78d6", "dibs": "#eb6834", "ikincil": "#52514e"}


def _haftalik(g: dict) -> bool:
    return "haftal" in _norm(str(g.get("FREQUENCY_STR") or "")) or "week" in _norm(str(g.get("FREQUENCY_STR") or ""))


def kos() -> int:
    anahtar = os.environ.get("EVDS_API_KEY", "").strip()
    if not anahtar:
        print("HATA: EVDS_API_KEY yok", file=sys.stderr)
        return 1
    CIKTI.mkdir(parents=True, exist_ok=True)
    e = Evds(anahtar)
    bugun = datetime.now(timezone.utc)
    bas, bit = (bugun - timedelta(days=GERI_GUN)).strftime("%d-%m-%Y"), bugun.strftime("%d-%m-%Y")
    log, hatali, ozet = [], {}, {"uretim_zamani_utc": bugun.isoformat(timespec="seconds"), "gruplar": {}}

    gruplar = e.gruplar()
    aday = [g for g in gruplar if _haftalik(g) and any(_norm(k) in _norm(f"{g.get('DATAGROUP_NAME', '')} {g.get('DATAGROUP_NAME_ENG', '')}")
                                                        for k in GRUP_ANAHTAR)]
    log.append(f"[gruplar] haftalik aday: {len(aday)}")
    for g in aday:
        log.append(f"  {g.get('DATAGROUP_CODE')} | {g.get('DATAGROUP_NAME')} | {g.get('FREQUENCY_STR')} | {g.get('START_DATE')}..{g.get('END_DATE')}")

    tablolar = {}
    for g in aday:
        kod = g.get("DATAGROUP_CODE")
        try:
            seriler = e.seriler(kod)
        except Exception as ex:
            hatali[kod] = str(ex)
            continue
        log.append(f"[seriler] {kod}: {len(seriler)}")
        for s in seriler[:60]:
            log.append(f"    {s.get('SERIE_CODE')} | {_ad(s)} | {s.get('START_DATE')}..{s.get('END_DATE')}")
        if len(seriler) > 60:
            continue
        try:
            df = e.veri([s.get("SERIE_CODE") for s in seriler], bas, bit)
        except Exception as ex:
            hatali[f"veri_{kod}"] = str(ex)
            continue
        if not len(df):
            continue
        df = df.dropna(how="all")
        adlar = {s.get("SERIE_CODE"): _ad(s) for s in seriler}
        son = df.tail(SON_HAFTA)
        tablolar[kod] = (g.get("DATAGROUP_NAME"), son, adlar, df)
        ozet["gruplar"][kod] = {"ad": g.get("DATAGROUP_NAME"), "son_tarih": f"{df.index[-1]:%Y-%m-%d}",
                                "seriler": {k: {"ad": adlar.get(k), "son": son[k].round(1).tolist()} for k in son.columns},
                                "tarihler": [f"{t:%Y-%m-%d}" for t in son.index]}

    # --- metin rapor
    sat = [f"# Haftalık akımlar (EVDS) — {ozet['uretim_zamani_utc']}", ""]
    for kod, (ad, son, adlar, _df) in tablolar.items():
        sat += [f"## {kod} — {ad}", "", "| seri | " + " | ".join(f"{t:%d.%m}" for t in son.index) + " |",
                "|---|" + "---|" * len(son.index)]
        for k in son.columns:
            sat.append(f"| {adlar.get(k, k)[:90]} ({k}) | " + " | ".join("—" if pd.isna(v) else f"{v:,.0f}" for v in son[k]) + " |")
        sat.append("")
    (CIKTI / "rapor.md").write_text("\n".join(sat) + "\n", encoding="utf-8")

    # --- grafik: yurt disi yerlesik hisse + DIBS haftalik net alim (adlardan)
    secim = {}
    for kod, (ad, _son, adlar, df) in tablolar.items():
        if not any(w in _norm(ad) for w in ("yurt dis", "yurtdis", "non-res")):
            continue
        for k, a in adlar.items():
            n = _norm(a)
            if k not in df:
                continue
            if "hisse" in n and "hisse" not in secim:
                secim["hisse"] = (k, a, df[k])
            if ("devlet ic borclanma" in n or "dibs" in n) and "dibs" not in secim:
                secim["dibs"] = (k, a, df[k])
    log.append("[grafik secim] " + "; ".join(f"{t}={v[0]} ({v[1]})" for t, v in secim.items()) if secim else "[grafik secim] YOK")
    if secim:
        plt = _plt()
        fig, axlar = plt.subplots(len(secim), 1, figsize=(11, 3.2 * len(secim)), sharex=True)
        axlar = np.atleast_1d(axlar)
        for ax, (t, (k, a, s)) in zip(axlar, secim.items()):
            s = s.dropna().tail(52)
            ax.bar(s.index, s, width=5, color=[RENK[t] if v >= 0 else "#e34948" for v in s])
            ax.axhline(0, color=RENK["ikincil"], lw=0.8)
            ax.set_title(f"{a} — son hafta {s.iloc[-1]:+,.0f} ({s.index[-1]:%d.%m.%Y}), 4 hafta {s.tail(4).sum():+,.0f}",
                         loc="left", fontsize=10, fontweight="bold")
            ax.grid(axis="y", color="#e6e5e1", lw=0.6)
        axlar[-1].text(1.0, -0.25, "Kaynak: TCMB EVDS, haftalık menkul kıymet istatistikleri. Seri adları olduğu gibi.",
                       transform=axlar[-1].transAxes, ha="right", fontsize=8, color="#777777")
        fig.tight_layout()
        fig.savefig(CIKTI / "akim.png", dpi=160, bbox_inches="tight")
        plt.close(fig)

    ozet["hatali"] = hatali
    (CIKTI / "ozet.json").write_text(json.dumps(_json_guvenli(ozet), ensure_ascii=False, indent=2), encoding="utf-8")
    (CIKTI / "kesif.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    print((CIKTI / "rapor.md").read_text(encoding="utf-8")[:12000])
    return 0


if __name__ == "__main__":
    sys.exit(kos())
