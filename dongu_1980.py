"""
dongu_1980.py — Backtest #3: Gumusun uc parabolik tepesi (1980, 2011, 2026) ayni olcekte.

Veri: Dunya Bankasi "Pink Sheet" aylik ortalama fiyatlar (1960 -> ), gumus/altin/bakir/petrol/platin.
WB'nin son ayindan sonrasi Yahoo vadelisinin aylik ortalamasiyla, son ortak ay hizalanarak uzatilir
(not ozet.json'a duser). Hisse ve dolar: Yahoo ^GSPC, ^IXIC, DX-Y.NYB aylik ortalama.
UC DONGU DE AYLIK ORTALAMAYLA olculur: gunluk kapanis tepeleri (1980 ~$49, 2026 ~$121) burada
gorunmez; amac ayni olcekte karsilastirma.

1) Uc dongu zirveye hizali (ay), dipler, zirveyi geri alma sureleri
2) 1980 dongusunun faz haritasi (zigzag) + fazlarda diger varliklar
3) Bugunu 1980 ve 2011'e ZAMAN ve DERINLIK ile hizalama
Gecmisin kaydidir, tahmin degildir.

Kullanim:
  python dongu_1980.py           # gercek veri
  python dongu_1980.py --demo    # sentetik kuru test
Cikti: sonuclar/dongu_1980/
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from dongu_backtest import KLASOR, _json_guvenli, _plt, _tarih_duzelt
from dongu_fazlari import zigzag

ALT_KLASOR = "dongu_1980"
WB_URLLER = (
    "https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx",
    "https://thedocs.worldbank.org/en/doc/18675f1d1639c7a34d463f59263ba0a2-0050012025/related/CMO-Historical-Data-Monthly.xlsx",
)
WB_KOLON = {"gumus": "Silver", "altin": "Gold", "platin": "Platinum", "bakir": "Copper", "petrol": "Crude oil, average"}
YAHOO_UZATMA = {"gumus": "SI=F", "altin": "GC=F", "platin": "PL=F", "bakir": "HG=F", "petrol": "CL=F"}
YAHOO_EK = {"sp500": "^GSPC", "nasdaq": "^IXIC", "dxy": "DX-Y.NYB"}
AD = {"gumus": "Gümüş", "altin": "Altın", "platin": "Platin", "bakir": "Bakır", "petrol": "Petrol (ham, ort.)",
      "sp500": "S&P 500", "nasdaq": "Nasdaq", "dxy": "Dolar Endeksi"}
FAZ_VARLIKLARI = ("altin", "bakir", "petrol", "sp500", "nasdaq", "dxy")

TEPE_PENCERE = {"1980": ("1979-06-30", "1980-12-31"),
                "2011": ("2010-06-30", "2011-12-31"),
                "2026": ("2025-06-30", "2026-06-30")}
DIP_PENCERE_YIL = 5           # "dongu dibi" = zirveden sonraki 5 yildaki en dusuk aylik ortalama
YOL_ONCE_AY, YOL_SONRA_AY = 36, 240
ZIGZAG_ESIK = 0.25
FAZ_ARALIK = ("1976-01-31", "1995-12-31")
UFUK_AY = (3, 6, 12, 24)
RENK = {"1980": "#B03A2E", "2011": "#7F8C8D", "2026": "#1B2631", "vurgu": "#2980B9"}


# ---------------------------------------------------------------------------
# Veri
# ---------------------------------------------------------------------------
def wb_ayristir(dosya) -> dict[str, pd.Series]:
    ham = pd.read_excel(dosya, sheet_name="Monthly Prices", header=None)
    bas = None
    for i in range(min(20, len(ham))):
        if "Silver" in [str(x).strip() for x in ham.iloc[i].tolist()]:
            bas = i
            break
    if bas is None:
        raise RuntimeError("WB: 'Silver' baslik satiri bulunamadi; ilk satirlar: "
                           + repr(ham.head(8).iloc[:, :6].values.tolist()))
    adlar = [str(x).strip() for x in ham.iloc[bas].tolist()]
    tarih = ham.iloc[:, 0].astype(str).str.strip()
    maske = tarih.str.match(r"^\d{4}M\d{2}$")
    idx = pd.to_datetime(tarih[maske].str.replace("M", "-", regex=False) + "-01") + pd.offsets.MonthEnd(0)
    cikti = {}
    for k, ad in WB_KOLON.items():
        if ad in adlar:
            seri = pd.to_numeric(ham.loc[maske, adlar.index(ad)], errors="coerce")
            seri.index = pd.DatetimeIndex(idx)
            cikti[k] = seri.dropna()
    if "gumus" not in cikti:
        raise RuntimeError("WB: gumus kolonu okunamadi")
    return cikti


def wb_indir() -> tuple[dict[str, pd.Series], str]:
    import requests
    hatalar = []
    for url in WB_URLLER:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (dongu-arastirma)"}, timeout=120)
            r.raise_for_status()
            return wb_ayristir(io.BytesIO(r.content)), url
        except Exception as e:
            hatalar.append(f"{url}: {type(e).__name__}: {e}")
    raise RuntimeError(" | ".join(hatalar))


def yahoo_aylik(tickerlar: dict[str, str], baslangic: str) -> tuple[dict[str, pd.Series], dict[str, str]]:
    import yfinance as yf
    cikti, hatali = {}, {}
    for k, tk in tickerlar.items():
        try:
            df = yf.download(tk, start=baslangic, auto_adjust=True, progress=False, threads=False)
            kap = df["Close"]
            if isinstance(kap, pd.DataFrame):
                kap = kap.iloc[:, 0]
            s = _tarih_duzelt(kap.dropna())
            s = s[s > 0]
            cikti[k] = s.resample("ME").mean().dropna()
        except Exception as e:
            hatali[k] = f"{tk}: {type(e).__name__}: {e}"
    return cikti, hatali


def uzat(wb: pd.Series, ya: pd.Series | None) -> tuple[pd.Series, str | None]:
    """WB'nin son ayindan sonrasini Yahoo aylik ortalamasiyla, son ortak ayda olcekleyerek ekler."""
    if ya is None:
        return wb, None
    ortak = wb.index.intersection(ya.index)
    if len(ortak) == 0:
        return wb, None
    son = ortak[-1]
    oran = float(wb[son] / ya[son])
    ek = ya[ya.index > wb.index[-1]] * oran
    if len(ek) == 0:
        return wb, None
    return (pd.concat([wb, ek]),
            f"{ek.index[0]:%Y-%m}..{ek.index[-1]:%Y-%m} Yahoo aylik ortalamasiyla uzatildi "
            f"(olcek {oran:.3f}, {son:%Y-%m} hizasi; son ay kismi olabilir)")


def sentetik() -> tuple[dict[str, pd.Series], dict[str, pd.Series], str]:
    rng = np.random.default_rng(7)
    aylar = pd.date_range("1960-01-31", "2026-11-30", freq="ME")
    n = len(aylar)

    def seri(vol, tepe_listesi=()):
        y = np.exp(np.cumsum(rng.normal(0.002, vol, n)))
        for bas, tepe, carp in tepe_listesi:
            b, t = aylar.get_indexer([pd.Timestamp(bas)], method="nearest")[0], aylar.get_indexer([pd.Timestamp(tepe)], method="nearest")[0]
            yukari = np.ones(n)
            yukari[b:t] = np.linspace(1, carp, t - b)
            yukari[t:] = np.maximum(carp * np.exp(-np.arange(n - t) / 30), 0.35 * carp)
            y = y * yukari
        return pd.Series(10 * y, index=aylar)

    wb = {"gumus": seri(0.05, [("1978-01-31", "1980-01-31", 6), ("2009-01-31", "2011-04-30", 4),
                               ("2024-11-30", "2026-01-31", 4)]),
          "altin": seri(0.04), "platin": seri(0.05), "bakir": seri(0.05), "petrol": seri(0.07)}
    ek = {"sp500": seri(0.04), "nasdaq": seri(0.05), "dxy": seri(0.02)}
    return wb, ek, "sentetik"


# ---------------------------------------------------------------------------
# Hesap
# ---------------------------------------------------------------------------
def zirveye_hizali(g: pd.Series, t: pd.Timestamp) -> pd.Series:
    i = g.index.get_loc(t)
    lo, hi = max(0, i - YOL_ONCE_AY), min(len(g), i + YOL_SONRA_AY + 1)
    return pd.Series(g.iloc[lo:hi].to_numpy() / g.iloc[i] - 1, index=np.arange(lo - i, hi - i))


def dongu_ozeti(g: pd.Series, ad: str) -> dict:
    w = g.loc[TEPE_PENCERE[ad][0]:TEPE_PENCERE[ad][1]]
    t, p = w.idxmax(), float(w.max())
    sonra = g.loc[t:]
    pen = sonra.loc[: t + pd.DateOffset(years=DIP_PENCERE_YIL)]
    dip_t, dip = pen.idxmin(), float(pen.min())
    geri = sonra.iloc[1:][sonra.iloc[1:] >= p]
    geri_t = geri.index[0] if len(geri) else None
    tam = g.loc[t: geri_t] if geri_t is not None else sonra
    tam_t = tam.idxmin()
    ay = lambda a, b: int(round((b - a).days / 30.44))
    return {
        "dongu": ad, "zirve_ay": f"{t:%Y-%m}", "zirve": p,
        "dip_ay": f"{dip_t:%Y-%m}", "dip": dip, "dusus": dip / p - 1, "dibe_ay": ay(t, dip_t),
        "dipten_12a": float(g.asof(dip_t + pd.DateOffset(months=12)) / dip - 1)
                      if dip_t + pd.DateOffset(months=12) <= g.index[-1] else None,
        "tam_dongu_dibi_ay": f"{tam_t:%Y-%m}", "tam_dongu_dusus": float(tam.min() / p - 1),
        "zirveyi_geri_alma_ay": f"{geri_t:%Y-%m}" if geri_t is not None else None,
        "zirveyi_geri_alma_yil": round((geri_t - t).days / 365.25, 1) if geri_t is not None else None,
        "dip_teyitsiz": ad == "2026",
    }


def hizala(yollar: dict[str, pd.Series], ozetler: dict[str, dict]) -> tuple[pd.DataFrame, dict]:
    y26 = yollar["2026"]
    k = int(y26.index.max())
    d = float(y26.loc[k])
    satir, bilgi = [], {"bugun_ay_sonra": k, "bugun_dusus_aylik_ort": d}
    for c in ("1980", "2011"):
        y = yollar[c]
        dip_j = int(round((pd.Timestamp(ozetler[c]["dip_ay"]) - pd.Timestamp(ozetler[c]["zirve_ay"])).days / 30.44))
        pozitif = y[y.index >= 0]
        aday = pozitif[pozitif <= d]
        noktalar = {"zaman": k, "derinlik": int(aday.index[0]) if len(aday) else None}
        for tur, j in noktalar.items():
            if j is None or j not in y.index:
                continue
            taban = 1 + y.loc[j]
            kalan = y.loc[j:]
            geri = kalan[kalan.index > j]
            geri = geri[geri >= 0]
            b = {"esdeger_ay": (pd.Timestamp(ozetler[c]["zirve_ay"]) + pd.DateOffset(months=j)).strftime("%Y-%m"),
                 "zirveden_ay": j, "o_noktadaki_dusus": float(y.loc[j]),
                 "dibe_kalan": float((1 + y.loc[dip_j]) / taban - 1) if dip_j >= j else None,
                 "dibe_kalan_ay": dip_j - j if dip_j >= j else None,
                 "zirveye_donus_yil": round((int(geri.index[0]) - j) / 12, 1) if len(geri) else None}
            for u in UFUK_AY:
                h = j + u
                deg = float((1 + y.loc[h]) / taban - 1) if h in y.index else np.nan
                b[f"+{u}ay"] = deg
                satir.append({"dongu": c, "hizalama": tur, "ufuk_ay": u, "degisim": deg})
            bilgi[f"{c}_{tur}"] = b
    return pd.DataFrame(satir), bilgi


def faz_tablosu(g: pd.Series, ek: dict[str, pd.Series]) -> pd.DataFrame:
    p = zigzag(g.loc[FAZ_ARALIK[0]:FAZ_ARALIK[1]], ZIGZAG_ESIK)
    satirlar = []
    for a, b in zip(p[:-1], p[1:]):
        s = {"baslangic": f"{a['tarih']:%Y-%m}", "bitis": f"{b['tarih']:%Y-%m}",
             "faz": "yükseliş" if b["fiyat"] > a["fiyat"] else "düşüş",
             "gumus_degisim": b["fiyat"] / a["fiyat"] - 1,
             "sure_ay": int(round((b["tarih"] - a["tarih"]).days / 30.44))}
        for k in FAZ_VARLIKLARI:
            seri = ek.get(k)
            s[k] = (float(seri.asof(b["tarih"]) / seri.asof(a["tarih"]) - 1)
                    if seri is not None and seri.index[0] <= a["tarih"] else np.nan)
        satirlar.append(s)
    return pd.DataFrame(satirlar)


# ---------------------------------------------------------------------------
# Grafikler
# ---------------------------------------------------------------------------
def grafik_uc_dongu(yollar, ozetler, bilgi, yol) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(11, 5.8))
    for c, lw in (("1980", 1.8), ("2011", 1.8), ("2026", 2.8)):
        y = yollar[c]
        y = y[(y.index >= -24) & (y.index <= 120)]
        o = ozetler[c]
        ax.plot(y.index, y * 100, color=RENK[c], lw=lw,
                label=f"{c} (zirve {o['zirve_ay']}, aylık ort. ${o['zirve']:.2f})")
    k, d = bilgi["bugun_ay_sonra"], bilgi["bugun_dusus_aylik_ort"]
    ax.axvline(0, color="#BBBBBB", lw=1)
    ax.axvline(k, color=RENK["vurgu"], lw=1, ls="--")
    y80, y11 = yollar["1980"], yollar["2011"]
    yakin = "1980" if abs(y80.get(k, np.nan) - d) < abs(y11.get(k, np.nan) - d) else "2011"
    ax.text(0.99, 0.97, f"Bugün (zirveden {k} ay): {d * 100:.0f}%\n1980 aynı ay: {y80.get(k, np.nan) * 100:.0f}%"
            f"\n2011 aynı ay: {y11.get(k, np.nan) * 100:.0f}%", transform=ax.transAxes, ha="right", va="top",
            fontsize=10, color=RENK["vurgu"])
    ax.set_xlabel("Zirveden ay")
    ax.set_ylabel("Zirveye göre % (aylık ortalama)")
    ax.set_title(f"Gümüşün üç tepesi: 2026'nın ilk {k} ayı {yakin} düşüşüne daha yakın",
                 loc="left", fontweight="bold")
    ax.legend(loc="lower left", frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


def grafik_uzun(g: pd.Series, ozetler, yol) -> None:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(11, 5.6))
    ax.plot(g.index, g, color="#455A64", lw=1.3)
    for c in ("1980", "2011", "2026"):
        o = ozetler[c]
        t = pd.Timestamp(o["zirve_ay"]) + pd.offsets.MonthEnd(0)
        ax.annotate(f"{c} tepesi\n${o['zirve']:.0f}", xy=(t, o["zirve"]), xytext=(0, 10),
                    textcoords="offset points", ha="center", fontsize=9, color=RENK[c], fontweight="bold")
        bitis = (pd.Timestamp(o["zirveyi_geri_alma_ay"]) if o["zirveyi_geri_alma_ay"] else g.index[-1])
        ax.axvspan(t, bitis, color=RENK[c], alpha=0.06)
    ax.set_yscale("log")
    ax.set_yticks([1, 2, 5, 10, 20, 50, 100], ["1", "2", "5", "10", "20", "50", "100"])
    ax.set_ylabel("$/ons (aylık ortalama, log)")
    o80, o11 = ozetler["1980"], ozetler["2011"]
    ax.set_title(f"Gümüş 1960–2026: 1980 zirvesi {o80['zirveyi_geri_alma_yil']} yıl, 2011 zirvesi "
                 f"{o11['zirveyi_geri_alma_yil']} yıl sonra geri alındı", loc="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


def grafik_hizalama(tablo: pd.DataFrame, bilgi: dict, yol) -> None:
    plt = _plt()
    d = tablo[tablo["hizalama"] == "derinlik"]
    if len(d) == 0:
        return
    x = np.arange(len(UFUK_AY))
    fig, ax = plt.subplots(figsize=(9, 5))
    for kaydir, c in ((-0.2, "1980"), (0.2, "2011")):
        r = d[d["dongu"] == c].set_index("ufuk_ay").reindex(UFUK_AY)["degisim"]
        b = bilgi.get(f"{c}_derinlik")
        if b is None:
            continue
        ax.bar(x + kaydir, r * 100, 0.4, color=RENK[c],
               label=f"{c}: {b['esdeger_ay']} sonrası ({b['o_noktadaki_dusus'] * 100:.0f}%)")
        for xi, v in zip(x + kaydir, r):
            if not np.isnan(v):
                ax.text(xi, v * 100, f"{v * 100:+.0f}%", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    ax.axhline(0, color="#888888", lw=0.8)
    ax.set_xticks(x, [f"+{u} ay" for u in UFUK_AY])
    ax.set_ylabel("O noktadan sonraki değişim % (aylık ort.)")
    ax.set_title(f"Aynı derinlikten sonra ne oldu? (bugün zirveden {bilgi['bugun_dusus_aylik_ort'] * 100:.0f}%, aylık ort.)",
                 loc="left", fontweight="bold", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(yol, dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------------------
def _y(x) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.0f}%"


def kos(demo: bool = False) -> int:
    cikti = KLASOR / ("sonuclar_demo" if demo else "sonuclar") / ALT_KLASOR
    cikti.mkdir(parents=True, exist_ok=True)
    notlar, hatali = [], {}
    if demo:
        wb, ek, kaynak = sentetik()
    else:
        try:
            wb, kaynak = wb_indir()
        except Exception as e:
            print(f"HATA: Dunya Bankasi verisi alinamadi: {e}", file=sys.stderr)
            return 1
        uzatma, h1 = yahoo_aylik(YAHOO_UZATMA, "2000-01-01")
        ek, h2 = yahoo_aylik(YAHOO_EK, "1960-01-01")
        hatali.update(h1)
        hatali.update(h2)
        for k in list(wb):
            wb[k], nt = uzat(wb[k], uzatma.get(k))
            if nt:
                notlar.append(f"{k}: {nt}")
    g = wb["gumus"]
    ek_tum = {**{k: v for k, v in wb.items() if k != "gumus"}, **ek}

    ozetler = {c: dongu_ozeti(g, c) for c in TEPE_PENCERE}
    yollar = {c: zirveye_hizali(g, pd.Timestamp(ozetler[c]["zirve_ay"]) + pd.offsets.MonthEnd(0))
              for c in TEPE_PENCERE}
    hz, hz_bilgi = hizala(yollar, ozetler)
    fazlar = faz_tablosu(g, ek_tum)

    pd.DataFrame(ozetler.values()).to_csv(cikti / "dongu_ozetleri.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({c: y for c, y in yollar.items()}).rename_axis("zirveden_ay").to_csv(
        cikti / "zirveye_hizali_yollar.csv", encoding="utf-8-sig")
    hz.to_csv(cikti / "hizalama.csv", index=False, encoding="utf-8-sig")
    fazlar.to_csv(cikti / "faz_1980.csv", index=False, encoding="utf-8-sig")
    g.to_frame("gumus_aylik_ort").to_csv(cikti / "gumus_aylik.csv", encoding="utf-8-sig", index_label="ay")
    grafik_uc_dongu(yollar, ozetler, hz_bilgi, cikti / "uc_dongu.png")
    grafik_uzun(g, ozetler, cikti / "gumus_1960_2026.png")
    grafik_hizalama(hz, hz_bilgi, cikti / "hizalama_1980_2011.png")

    ozet = {"uretim_zamani_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "demo": demo, "kaynak": kaynak, "veri_son_ay": f"{g.index[-1]:%Y-%m}",
            "uzatma_notlari": notlar, "hatali": hatali,
            "kurallar": {"olcek": "aylik ortalama", "dip": f"zirveden sonraki {DIP_PENCERE_YIL} yildaki en dusuk",
                         "zigzag": f"%{ZIGZAG_ESIK * 100:.0f}"},
            "donguler": ozetler, "hizalama": hz_bilgi}
    (cikti / "ozet.json").write_text(json.dumps(_json_guvenli(ozet), ensure_ascii=False, indent=2), encoding="utf-8")

    sat = [f"# Backtest #3 — 1980 · 2011 · 2026 ({ozet['uretim_zamani_utc']}{', DEMO' if demo else ''})",
           f"Kaynak: {kaynak} · son ay {ozet['veri_son_ay']} · aylık ortalama", "",
           "| döngü | zirve | 5 yıl içindeki dip | düşüş | dibe (ay) | dipten 12 ay | tam döngü dibi | zirveyi geri alma |",
           "|---|---|---|---|---|---|---|---|"]
    for o in ozetler.values():
        sat.append(f"| {o['dongu']} | {o['zirve_ay']} ${o['zirve']:.2f} | {o['dip_ay']} ${o['dip']:.2f}"
                   f"{' (teyitsiz)' if o['dip_teyitsiz'] else ''} | {_y(o['dusus'])} | {o['dibe_ay']} | "
                   f"{_y(o['dipten_12a'])} | {o['tam_dongu_dibi_ay']} {_y(o['tam_dongu_dusus'])} | "
                   f"{o['zirveyi_geri_alma_ay'] or '—'} ({o['zirveyi_geri_alma_yil'] or '—'} yıl) |")
    sat += ["", "## Hizalama", f"Bugün zirveden {hz_bilgi['bugun_ay_sonra']} ay, {_y(hz_bilgi['bugun_dusus_aylik_ort'])} (aylık ort.)", "",
            "| döngü · hizalama | eşdeğer ay | o noktada | +3 | +6 | +12 | +24 | dibe kalan | zirveye dönüş |",
            "|---|---|---|---|---|---|---|---|---|"]
    for anahtar, b in hz_bilgi.items():
        if not isinstance(b, dict):
            continue
        sat.append(f"| {anahtar} | {b['esdeger_ay']} | {_y(b['o_noktadaki_dusus'])} | {_y(b['+3ay'])} | {_y(b['+6ay'])} | "
                   f"{_y(b['+12ay'])} | {_y(b['+24ay'])} | {_y(b['dibe_kalan'])} ({b['dibe_kalan_ay']} ay) | "
                   f"{b['zirveye_donus_yil'] if b['zirveye_donus_yil'] is not None else '—'} yıl |")
    sat += ["", f"## 1980 döngüsü fazları (zigzag ±%{ZIGZAG_ESIK * 100:.0f}, aylık ort.)", "",
            "| başlangıç | bitiş | faz | gümüş | süre (ay) | " + " | ".join(AD[k] for k in FAZ_VARLIKLARI) + " |",
            "|---|---|---|---|---|" + "---|" * len(FAZ_VARLIKLARI)]
    for _, r in fazlar.iterrows():
        sat.append(f"| {r['baslangic']} | {r['bitis']} | {r['faz']} | {_y(r['gumus_degisim'])} | {r['sure_ay']} | "
                   + " | ".join(_y(r[k]) for k in FAZ_VARLIKLARI) + " |")
    sat += ["", "Geçmişin kaydıdır, tahmin değildir. Yatırım tavsiyesi değildir."]
    (cikti / "rapor.md").write_text("\n".join(sat) + "\n", encoding="utf-8")
    print(f"tamam: {cikti} | hatali: {hatali or 'yok'} | uzatma: {notlar or 'yok'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    sys.exit(kos(demo=ap.parse_args().demo))
