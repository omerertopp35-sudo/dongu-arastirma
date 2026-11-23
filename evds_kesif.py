"""
evds_kesif.py — TCMB EVDS erisim kesfi (tek seferlik arac).

1) Hangi taban adres + anahtar iletim bicimi calisiyor (EVDS 3 / EVDS 2, header / query)?
2) Veri gruplari icinde BIST, TUFE, kur ve faiz anahtar kelimeleriyle eslesenler hangileri?
3) Aday serilerin kapsami (ilk-son tarih, gozlem sayisi).

Anahtar ortam degiskeninden (EVDS_API_KEY) okunur ve HICBIR ciktiya yazilmaz.
Cikti: sonuclar/evds/kesif.json + kesif.txt  (public repoya commit edilir, anahtar icermez)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import requests

from dongu_backtest import KLASOR

CIKTI = KLASOR / "sonuclar" / "evds"
TABANLAR = ("https://evds3.tcmb.gov.tr/igmevdsms-dis/", "https://evds2.tcmb.gov.tr/service/evds/")
TEST_SERI = "TP.DK.USD.A"
ANAHTAR_KELIMELER = ("BIST", "Borsa", "Hisse", "Tüketici Fiyat", "TÜFE", "Consumer Price",
                     "Politika", "Policy", "Fonlama", "Döviz Kur", "Exchange Rate", "Reserve", "Rezerv",
                     "Cari", "Current Account", "CDS", "Kredi")
ADAY_SERILER = ("TP.DK.USD.A", "TP.DK.USD.S", "TP.MK.F.BILESIK", "TP.FG.J0", "TP.FE.OKTG01",
                "TP.APIFON4", "TP.PY.P02.1H", "TP.AB.TOPLAM")
ZAMAN_ASIMI = 60


def _maskele(metin: str, anahtar: str) -> str:
    return metin.replace(anahtar, "***") if anahtar else metin


def istek(taban: str, yol: str, anahtar: str, bicim: str) -> requests.Response:
    url = taban + yol
    basliklar = {"User-Agent": "dongu-arastirma/0.1"}
    if bicim == "header":
        basliklar["key"] = anahtar
    else:
        url += ("&" if "=" in yol else "?") + f"key={anahtar}"
    return requests.get(url, headers=basliklar, timeout=ZAMAN_ASIMI)


def calisan_yontem(anahtar: str, log: list[str]) -> tuple[str, str] | None:
    yol = f"series={TEST_SERI}&startDate=02-01-2024&endDate=31-01-2024&type=json"
    for taban in TABANLAR:
        for bicim in ("header", "query"):
            try:
                r = istek(taban, yol, anahtar, bicim)
                govde = _maskele(r.text[:200].replace("\n", " "), anahtar)
                log.append(f"[deneme] {taban} {bicim} -> {r.status_code} | {govde}")
                if r.status_code == 200 and '"items"' in r.text:
                    return taban, bicim
            except Exception as e:
                log.append(f"[deneme] {taban} {bicim} -> {type(e).__name__}: {_maskele(str(e), anahtar)[:150]}")
    return None


def kos() -> int:
    anahtar = os.environ.get("EVDS_API_KEY", "").strip()
    CIKTI.mkdir(parents=True, exist_ok=True)
    log, sonuc = [], {"uretim_zamani_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if not anahtar:
        log.append("HATA: EVDS_API_KEY ortam degiskeni bos (GitHub secret workflow'a gecmiyor olabilir)")
        (CIKTI / "kesif.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
        print("\n".join(log))
        return 1
    yontem = calisan_yontem(anahtar, log)
    sonuc["calisan_yontem"] = {"taban": yontem[0], "anahtar_iletimi": yontem[1]} if yontem else None
    if yontem is None:
        log.append("HATA: hicbir taban/bicim calismadi")
    else:
        taban, bicim = yontem
        # veri gruplari
        try:
            r = istek(taban, "datagroups/mode=0&type=json", anahtar, bicim)
            gruplar = r.json() if r.status_code == 200 else []
            log.append(f"[gruplar] {r.status_code}, {len(gruplar)} grup")
            eslesen = []
            for g in gruplar:
                ad = f"{g.get('DATAGROUP_NAME', '')} | {g.get('DATAGROUP_NAME_ENG', '')}"
                if any(k.lower() in ad.lower() for k in ANAHTAR_KELIMELER):
                    eslesen.append({"kod": g.get("DATAGROUP_CODE"), "ad": ad,
                                    "frekans": g.get("FREQUENCY_STR") or g.get("FREQUENCY"),
                                    "baslangic": g.get("START_DATE"), "bitis": g.get("END_DATE")})
            sonuc["eslesen_gruplar"] = eslesen
            log.append(f"[gruplar] anahtar kelimeyle eslesen: {len(eslesen)}")
            for e in eslesen:
                log.append(f"  {e['kod']} | {e['ad']} | {e['frekans']} | {e['baslangic']}..{e['bitis']}")
        except Exception as e:
            log.append(f"[gruplar] HATA {type(e).__name__}: {_maskele(str(e), anahtar)[:200]}")
        # BIST / TUFE gruplarinin serileri
        sonuc["seri_listeleri"] = {}
        for e in sonuc.get("eslesen_gruplar", [])[:40]:
            ad = e["ad"].lower()
            if not any(k in ad for k in ("bist", "hisse", "borsa", "tüketici fiyat", "consumer price", "politika", "fonlama")):
                continue
            try:
                r = istek(taban, f"serieList/type=json&code={e['kod']}", anahtar, bicim)
                seriler = r.json() if r.status_code == 200 else []
                kisa = [{"kod": s.get("SERIE_CODE"), "ad": s.get("SERIE_NAME"), "frekans": s.get("FREQUENCY_STR"),
                         "baslangic": s.get("START_DATE"), "bitis": s.get("END_DATE")} for s in seriler][:60]
                sonuc["seri_listeleri"][e["kod"]] = kisa
                log.append(f"[seriler] {e['kod']}: {len(seriler)} seri")
                for s in kisa[:25]:
                    log.append(f"    {s['kod']} | {s['ad']} | {s['frekans']} | {s['baslangic']}..{s['bitis']}")
            except Exception as ex:
                log.append(f"[seriler] {e['kod']} HATA {type(ex).__name__}")
        # aday seri kapsamlari
        sonuc["aday_kapsam"] = {}
        for kod in ADAY_SERILER:
            try:
                r = istek(taban, f"series={kod}&startDate=01-01-1980&endDate=31-12-2026&type=json", anahtar, bicim)
                if r.status_code != 200:
                    sonuc["aday_kapsam"][kod] = f"HTTP {r.status_code}"
                    log.append(f"[aday] {kod}: HTTP {r.status_code}")
                    continue
                items = r.json().get("items", [])
                kol = kod.replace(".", "_")
                dolu = [i for i in items if i.get(kol) not in (None, "", "null")]
                sonuc["aday_kapsam"][kod] = {"gozlem": len(dolu),
                                            "ilk": dolu[0]["Tarih"] if dolu else None,
                                            "son": dolu[-1]["Tarih"] if dolu else None,
                                            "ornek_son_deger": dolu[-1].get(kol) if dolu else None}
                log.append(f"[aday] {kod}: {sonuc['aday_kapsam'][kod]}")
            except Exception as ex:
                sonuc["aday_kapsam"][kod] = f"{type(ex).__name__}"
                log.append(f"[aday] {kod}: HATA {type(ex).__name__}")
    (CIKTI / "kesif.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=2), encoding="utf-8")
    (CIKTI / "kesif.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    return 0 if yontem else 1


if __name__ == "__main__":
    sys.exit(kos())
