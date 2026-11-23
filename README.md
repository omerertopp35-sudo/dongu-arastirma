# dongu-arastirma — piyasa döngüleri araştırması

Makrodan mikroya döngü soruları ve backtestleri. Emir açmaz, sinyal üretmez:
geçmişin kaydıdır, tahmin değildir. Yatırım tavsiyesi değildir.

| script | ne yapar | çıktı |
|---|---|---|
| `dongu_backtest.py` | A) gümüş 2011↔2026 zirveye hizalı analog · B) parabolik tepe olay çalışması (çoklu varlık, rastgele gün kıyası) · C) gümüş+altın+Nasdaq aynı çeyrekte düşünce diğer varlıklar ve sonraki 4 çeyrekte toparlanma sırası · D) gümüş zirvesinden sonra varlık getirileri | `sonuclar/backtest/` |
| `dongu_fazlari.py` | backtest #2: gümüşün tepe/dip faz haritası (zigzag ±%25), 2011 döngüsünün tamamı, bugünü 2011'e zaman ve derinlikle hizalama | `sonuclar/fazlar/` |
| `dongu_1980.py` | backtest #3: 1980 · 2011 · 2026 gümüş tepeleri aynı ölçekte (Dünya Bankası aylık ortalama, 1960→), 1980 faz haritası, bugünü 1980 ve 2011'e hizalama | `sonuclar/dongu_1980/` |
| `dongu_zamanlama.py` | backtest #4: ay ay karşılaştırma ve zaman esnetme (2026 geçmiş döngüyü kaç kat hızlı oynuyor), mekanik tarih eşlemesi — ağ kullanmaz, `dongu_1980.py` çıktısını okur | `sonuclar/zamanlama/` |
| `cot_grafik.py` | altın, gümüş, Nasdaq 100, S&P 500, Dow: fonların uzun / kısa / net pozisyonu (üst panel) + ürünün fiyatı (alt panel), belirgin artırma/azaltma haftaları işaretli | `sonuclar/cot/` |

Veri: Yahoo (yfinance), CFTC Socrata ve Dünya Bankası Pink Sheet (aylık emtia fiyatları). Gizli anahtar gerekmez.

**Çalıştırma:** GitHub Actions (`.github/workflows/kos.yml`) — `main`'e script push'u
ya da Actions → kos → Run workflow. Sonuçlar `sonuclar/` altına commit edilir.

Kuru test (ağ yok, sentetik): `python dongu_backtest.py --demo` ve
`python cot_grafik.py --demo` → `sonuclar_demo/` (git dışı). Sentetik testten
geçmesi yalnız "kod çalışıyor" demektir.
