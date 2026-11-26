"""
evds_rezerv.py — TCMB rezervleri: son durum (EVDS).

1) Brut rezerv (haftalik, resmi): bie_abres2 "Merkez Bankasi Rezervleri" — doviz, altin, toplam.
2) Net rezerv (gunluk, BIZIM hesabimiz, yaklasik): analitik bilancodan
   Dis Varliklar - Toplam Doviz Yukumlulukleri, USDTRY ile dolara cevrilir.
3) Swap bilgisi: "Uluslararasi Rezervler ve Doviz Likiditesi" (aylik) icinde swap/forward kalemleri listelenir.

Seri kodlari tahmin edilmez: once EVDS metadata (datagroups / serieList) okunur, kalemler ADLARINDAN bulunur,
bulunan ad ve kod ciktiya yazilir (denetlenebilir). Anahtar EVDS_API_KEY, hicbir ciktiya yazilmaz.
Cikti: sonuclar/rezerv/ (ozet tablolar + grafik; ham seri dokumu yok).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

from dongu_backtest import KLASOR, _json_guvenli, _plt

TABAN = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
BRUT_GRUP = "bie_abres2"
LIKIDITE_GRUP = "bie_ulusdovlkd"
ANALITIK_ANAHTAR = ("analitik bilanço", "analytical balance")
BRUT_BAS = "01-01-2023"
GUNLUK_GERI_GUN = 400
CIKTI = KLASOR / "sonuclar" / "rezerv"
RENK = {"doviz": "#2a78d6", "altin": "#eda100", "net": "#1B2631", "ikincil": "#52514e"}


class Evds:
    def __init__(self, anahtar: str):
        self.anahtar = anahtar
        self.log: list[str] = []

    def _get(self, yol: str):
        r = requests.get(TABAN + yol, headers={"key": self.anahtar, "User-Agent": "dongu-arastirma/0.1"}, timeout=90)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160].replace(self.anahtar, '***')}")
        return r.json()

    def gruplar(self) -> list[dict]:
        return self._get("datagroups/mode=0&type=json")

    def seriler(self, grup: str) -> list[dict]:
        return self._get(f"serieList/type=json&code={grup}")

    def veri(self, kodlar: list[str], bas: str, bit: str) -> pd.DataFrame:
        parcalar = []
        for i in range(0, len(kodlar), 20):
            grup = kodlar[i:i + 20]
            j = self._get(f"series={'-'.join(grup)}&startDate={bas}&endDate={bit}&type=json")
            satir = []
            for it in j.get("items", []):
                d = {"Tarih": it.get("Tarih")}
                for k in grup:
                    v = it.get(k.replace(".", "_"))
                    d[k] = float(v) if v not in (None, "", "null") else np.nan
                satir.append(d)
            df = pd.DataFrame(satir)
            if len(df):
                df.index = pd.DatetimeIndex([_tarih(t) for t in df.pop("Tarih")])
                parcalar.append(df[df.index.notna()])
        return pd.concat(parcalar, axis=1).sort_index() if parcalar else pd.DataFrame()


def _tarih(t) -> pd.Timestamp:
    t = str(t)
    if re.fullmatch(r"\d{4}-\d{1,2}", t):
        y, a = map(int, t.split("-"))
        return pd.Timestamp(y, a, 1) + pd.offsets.MonthEnd(0)
    if re.fullmatch(r"\d{4}-Q\d", t):
        return pd.Period(t, "Q").end_time.normalize()
    return pd.to_datetime(t, format="%d-%m-%Y", errors="coerce")


def _ad(s: dict) -> str:
    return str(s.get("SERIE_NAME") or "")


def _norm(t: str) -> str:
    tablo = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return re.sub(r"\s+", " ", t.translate(tablo).lower()).strip()


def bul(seriler: list[dict], *desenler: str, haric: tuple[str, ...] = ()) -> dict | None:
    for s in seriler:
        n = _norm(_ad(s))
        if all(_norm(d) in n for d in desenler) and not any(_norm(h) in n for h in haric):
            return s
    return None


def son_ve_degisim(s: pd.Series, gecmis_gun: dict[str, int]) -> dict:
    s = s.dropna()
    if not len(s):
        return {}
    t, v = s.index[-1], float(s.iloc[-1])
    out = {"tarih": f"{t:%Y-%m-%d}", "deger": v}
    for ad, g in gecmis_gun.items():
        o = s.asof(t - timedelta(days=g))
        out[ad] = v - float(o) if pd.notna(o) else None
    yb = s.asof(pd.Timestamp(t.year - 1, 12, 31))
    out["yilbasindan"] = v - float(yb) if pd.notna(yb) else None
    return out


def kos() -> int:
    anahtar = os.environ.get("EVDS_API_KEY", "").strip()
    if not anahtar:
        print("HATA: EVDS_API_KEY yok", file=sys.stderr)
        return 1
    CIKTI.mkdir(parents=True, exist_ok=True)
    e = Evds(anahtar)
    bugun = datetime.now(timezone.utc)
    bit = bugun.strftime("%d-%m-%Y")
    log, ozet, hatali = [], {"uretim_zamani_utc": bugun.isoformat(timespec="seconds")}, {}

    # --- metadata
    try:
        gruplar = e.gruplar()
    except Exception as ex:
        print(f"HATA: datagroups {ex}", file=sys.stderr)
        return 1
    analitik = [g for g in gruplar if any(a in _norm(f"{g.get('DATAGROUP_NAME', '')} {g.get('DATAGROUP_NAME_ENG', '')}") for a in map(_norm, ANALITIK_ANAHTAR))]
    log.append(f"[gruplar] analitik bilanco adayları: " + "; ".join(f"{g.get('DATAGROUP_CODE')} | {g.get('DATAGROUP_NAME')} | {g.get('FREQUENCY_STR')} | ..{g.get('END_DATE')}" for g in analitik))
    meta = {}
    for kod in [BRUT_GRUP, LIKIDITE_GRUP] + [g.get("DATAGROUP_CODE") for g in analitik]:
        try:
            meta[kod] = e.seriler(kod)
            log.append(f"[seriler] {kod}: {len(meta[kod])}")
            for s in meta[kod][:80]:
                log.append(f"    {s.get('SERIE_CODE')} | {_ad(s)} | {s.get('FREQUENCY_STR')} | {s.get('START_DATE')}..{s.get('END_DATE')}")
        except Exception as ex:
            hatali[f"seriler_{kod}"] = str(ex)

    # --- usdtry (gunluk)
    bas_g = (bugun - timedelta(days=GUNLUK_GERI_GUN)).strftime("%d-%m-%Y")
    try:
        kur = e.veri(["TP.DK.USD.A"], bas_g, bit)["TP.DK.USD.A"].dropna()
    except Exception as ex:
        kur = pd.Series(dtype=float)
        hatali["usdtry"] = str(ex)

    # --- 1) brut rezerv
    brut = {}
    br = meta.get(BRUT_GRUP, [])
    secim = {"altin": bul(br, "altın"), "doviz": bul(br, "döviz", haric=("altın",)), "toplam": bul(br, "toplam")}
    log.append("[brut secim] " + "; ".join(f"{k}={v.get('SERIE_CODE')} ({_ad(v)})" if v else f"{k}=YOK" for k, v in secim.items()))
    df_b = pd.DataFrame()
    try:
        kodlar = [s.get("SERIE_CODE") for s in br]
        df_b = e.veri(kodlar, BRUT_BAS, bit)
        degisim = {"1_hafta": 7, "4_hafta": 28, "52_hafta": 364}
        for s in br:
            k = s.get("SERIE_CODE")
            if k in df_b:
                brut[k] = {"ad": _ad(s), **son_ve_degisim(df_b[k], degisim)}
    except Exception as ex:
        hatali["brut"] = str(ex)
    ozet["brut"] = {"secim": {k: (v.get("SERIE_CODE"), _ad(v)) if v else None for k, v in secim.items()}, "seriler": brut}

    # --- 2) net rezerv (analitik bilanco, gunluk)
    net = None
    an_seri = [s for g in analitik for s in meta.get(g.get("DATAGROUP_CODE"), [])]
    dis_v = bul(an_seri, "dış varlıklar") or bul(an_seri, "dis varliklar")
    top_dy = bul(an_seri, "toplam döviz yükümlülükleri")
    yd_y = bul(an_seri, "yurt dışı yükümlülük") or bul(an_seri, "dış yükümlülük", haric=("yurt içi",))
    yi_dy = bul(an_seri, "yurt içi döviz yükümlülük")
    log.append("[net secim] " + "; ".join(f"{a}={s.get('SERIE_CODE')} ({_ad(s)})" if s else f"{a}=YOK"
                                         for a, s in (("dis_varlik", dis_v), ("toplam_doviz_yuk", top_dy), ("yurtdisi_yuk", yd_y), ("yurtici_doviz_yuk", yi_dy))))
    an_df = pd.DataFrame()
    if dis_v and (top_dy or (yd_y and yi_dy)):
        kodlar = [s.get("SERIE_CODE") for s in (dis_v, top_dy, yd_y, yi_dy) if s]
        try:
            an_df = e.veri(kodlar, bas_g, bit)
            yuk = an_df[top_dy.get("SERIE_CODE")] if top_dy else an_df[yd_y.get("SERIE_CODE")] + an_df[yi_dy.get("SERIE_CODE")]
            net_tl = (an_df[dis_v.get("SERIE_CODE")] - yuk).dropna()
            k = kur.reindex(net_tl.index, method="ffill")
            # birim: analitik bilanco "bin TL" -> milyon USD (oran kontrolu ile)
            dis_usd = an_df[dis_v.get("SERIE_CODE")].dropna() / kur.reindex(an_df.index, method="ffill").dropna()
            olcek = 1.0
            toplam_brut = brut.get(secim["toplam"].get("SERIE_CODE"), {}).get("deger") if secim["toplam"] else None
            if toplam_brut and len(dis_usd.dropna()):
                oran = float(dis_usd.dropna().iloc[-1]) / toplam_brut
                olcek = 10 ** round(np.log10(oran)) if oran > 0 else 1.0
                log.append(f"[net] dis varlik / brut toplam ham oran {oran:.4g} -> olcek {olcek:g} (birim uyumu)")
            net_usd = (net_tl / k / olcek).dropna()
            net = {"kalemler": {"dis_varlik": (dis_v.get("SERIE_CODE"), _ad(dis_v)),
                                "yukumluluk": ((top_dy.get("SERIE_CODE"), _ad(top_dy)) if top_dy else
                                               [(yd_y.get("SERIE_CODE"), _ad(yd_y)), (yi_dy.get("SERIE_CODE"), _ad(yi_dy))])},
                   "dis_varlik_usd_son": float((dis_usd / olcek).dropna().iloc[-1]),
                   **son_ve_degisim(net_usd, {"1_hafta": 7, "4_hafta": 28, "52_hafta": 364})}
            ozet["_net_seri"] = net_usd
        except Exception as ex:
            hatali["net"] = f"{type(ex).__name__}: {ex}"
    ozet["net"] = net

    # --- 3) likidite tablosu: swap / forward kalemleri (aylik)
    lk = meta.get(LIKIDITE_GRUP, [])
    swap_kalem = [s for s in lk if any(w in _norm(_ad(s)) for w in ("swap", "forward", "vadeli"))]
    swap = {}
    if swap_kalem:
        try:
            dfl = e.veri([s.get("SERIE_CODE") for s in swap_kalem][:40], "01-01-2025", bit)
            for s in swap_kalem[:40]:
                k = s.get("SERIE_CODE")
                if k in dfl and dfl[k].notna().any():
                    x = dfl[k].dropna()
                    swap[k] = {"ad": _ad(s), "tarih": f"{x.index[-1]:%Y-%m}", "deger": float(x.iloc[-1])}
        except Exception as ex:
            hatali["swap"] = str(ex)
    ozet["likidite_swap_kalemleri"] = swap
    ozet["usdtry_son"] = {"tarih": f"{kur.index[-1]:%Y-%m-%d}", "deger": float(kur.iloc[-1])} if len(kur) else None
    ozet["hatali"] = hatali

    # --- grafik
    if secim["altin"] and secim["doviz"] and len(df_b):
        plt = _plt()
        a, d = df_b[secim["altin"].get("SERIE_CODE")].dropna() / 1000, df_b[secim["doviz"].get("SERIE_CODE")].dropna() / 1000
        ix = a.index.intersection(d.index)
        fig, ax = plt.subplots(figsize=(11, 5.6))
        ax.stackplot(ix, d.loc[ix], a.loc[ix], colors=[RENK["doviz"], RENK["altin"]], alpha=0.85,
                     labels=[f"Döviz ({d.iloc[-1]:.1f} mlr $)", f"Altın ({a.iloc[-1]:.1f} mlr $)"], edgecolor="white", linewidth=0.6)
        if net is not None:
            n = ozet["_net_seri"] / 1000
            n = n.loc[n.index >= ix[0]]
            ax.plot(n.index, n, color=RENK["net"], lw=1.8, label=f"Net rezerv, yaklaşık ({n.iloc[-1]:.1f} mlr $)")
        ax.axhline(0, color=RENK["ikincil"], lw=0.8)
        ax.set_ylabel("milyar $")
        ax.grid(axis="y", color="#e6e5e1", lw=0.6)
        ax.legend(frameon=False, fontsize=9, loc="upper left")
        ax.set_title(f"TCMB rezervleri: brüt {(a.iloc[-1] + d.iloc[-1]):.1f} mlr $ ({ix[-1]:%d.%m.%Y})",
                     loc="left", fontweight="bold", fontsize=11.5)
        ax.text(1.0, -0.12, "Brüt: EVDS Merkez Bankası Rezervleri (haftalık). Net: analitik bilanço dış varlıklar − toplam döviz "
                "yükümlülükleri, USD/TRY ile; swap dahil. Kaynak: TCMB EVDS.", transform=ax.transAxes, ha="right",
                fontsize=7.8, color="#777777")
        fig.savefig(CIKTI / "rezerv.png", dpi=160, bbox_inches="tight")
        plt.close(fig)

    ozet.pop("_net_seri", None)
    (CIKTI / "ozet.json").write_text(json.dumps(_json_guvenli(ozet), ensure_ascii=False, indent=2), encoding="utf-8")
    (CIKTI / "kesif.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log[:3]))
    print(json.dumps(_json_guvenli({k: v for k, v in ozet.items() if k != "brut"}), ensure_ascii=False, indent=1)[:3000])
    print(json.dumps(_json_guvenli(ozet["brut"]), ensure_ascii=False, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(kos())
