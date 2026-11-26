# BIST adım 4 — reel faiz rejimi (2026-11-26T12:04:44+00:00)

Veri 2002-02→2026-10 aylık (TCMB EVDS; EEM Yahoo). Ham veri yayımlanmaz.
Kurallar: {"reel_faiz": "(1+i)/(1+yillik TUFE)-1", "bilgi_gecikmesi_ay": 1, "olay": ">= 6 ay r<=0 sonra ilk r>0, olaylar arasi >= 12 ay", "yon": "politika faizi 6 aylik degisim < 0 = indirim", "test": "dairesel kaydirma >= 24 ay, tum kaydirmalar; plasebo 2000 cekilis"}

**Şu an (2026-10):** reel faiz +4,8%, politika %36.0, yıllık TÜFE +29,8%, 6 aylık faiz değişimi -1.0 puan → **pozitif · indirim**

## A) Rejim ayları — politika

| rejim | ay | BIST $ yıllık ort. | aylık medyan | + ay oranı | ileri 12a medyan | EEM farkı yıllık ort. | EEM farkı ileri 12a medyan |
|---|---|---|---|---|---|---|---|
| negatif | 135 | +2% | +0,3% | 53% | -2% | +2% | -10% |
| pozitif | 160 | +5% | +2,1% | 56% | +11% | -9% | -1% |

Fark testi (dairesel kaydırma, 248 kaydırma): BIST $ p=0.80; EEM farkı p=0.28. Bağımsız blok: {'pozitif': 12, 'negatif': 12}.

## B) İşaret × faiz yönü — politika

| hücre | ay | BIST $ yıllık ort. | EEM farkı yıllık ort. | BIST $ ileri 12a medyan | p (BIST $, hücre vs geri kalan)* | p (EEM farkı)* |
|---|---|---|---|---|---|---|
| negatif · indirim değil | 72 | +16% | +10% | -7% | 0.55 | 0.17 |
| negatif · indirim | 59 | -6% | -7% | +11% | 0.44 | 0.80 |
| pozitif · indirim değil | 56 | -15% | -16% | -1% | 0.17 | 0.26 |
| pozitif · indirim | 102 | +21% | -5% | +23% | 0.24 | 0.90 |

*Hücre testleri sonuçlar görüldükten sonra eklendi (ön-kayıtta yoktu); yalnız temkin için, kanıt sayılmaz.

## C) Pozitife dönüş olayları — politika

| olay | bilindi | reel | politika | TÜFE | 12a içi dip | BIST $ +6 | +12 | +24 | EEM farkı +6 | +12 | +24 | BIST $ bugüne |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2010-12 | 2011-01 | +0,1% | %6.5 | +6,4% | -31% | -6% | -17% | +14% | -9% | -12% | +13% | -45% |
| 2014-01 | 2014-02 | +2,1% | %10.0 | +7,8% | +0% | +34% | +21% | -8% | +17% | +15% | +15% | -23% |
| 2016-03 | 2016-04 | +0,0% | %7.5 | +7,5% | -29% | -16% | -12% | -15% | -23% | -26% | -40% | -29% |
| 2018-06 | 2018-07 | +2,0% | %17.8 | +15,4% | -27% | -1% | -8% | -18% | +2% | -3% | -19% | +9% |
| 2020-11 | 2020-12 | +0,9% | %15.0 | +14,0% | -29% | -23% | -29% | +46% | -28% | -26% | +91% | +8% |
| 2024-09 | 2024-10 | +0,4% | %50.0 | +49,4% | -11% | -9% | +1% | -16% | -9% | -21% | -42% | -16% |

- plasebo usd_6a: n=6, olay ort. -5%, medyan -7%, tüm aylar medyanı +4%, plasebo yüzdeliği 22
- plasebo usd_12a: n=6, olay ort. -9%, medyan -10%, tüm aylar medyanı +4%, plasebo yüzdeliği 14
- plasebo usd_24a: n=6, olay ort. -2%, medyan -11%, tüm aylar medyanı +2%, plasebo yüzdeliği 23
- plasebo fazla_6a: n=6, olay ort. -10%, medyan -9%, tüm aylar medyanı -1%, plasebo yüzdeliği 12
- plasebo fazla_12a: n=6, olay ort. -13%, medyan -16%, tüm aylar medyanı -6%, plasebo yüzdeliği 15
- plasebo fazla_24a: n=6, olay ort. -6%, medyan -4%, tüm aylar medyanı -13%, plasebo yüzdeliği 56

## A) Rejim ayları — efektif

| rejim | ay | BIST $ yıllık ort. | aylık medyan | + ay oranı | ileri 12a medyan | EEM farkı yıllık ort. | EEM farkı ileri 12a medyan |
|---|---|---|---|---|---|---|---|
| negatif | 108 | +5% | +0,7% | 56% | +6% | +4% | -7% |
| pozitif | 187 | +3% | +1,4% | 54% | +2% | -9% | -6% |

Fark testi (dairesel kaydırma, 248 kaydırma): BIST $ p=0.85; EEM farkı p=0.25. Bağımsız blok: {'pozitif': 14, 'negatif': 14}.

## B) İşaret × faiz yönü — efektif

| hücre | ay | BIST $ yıllık ort. | EEM farkı yıllık ort. | BIST $ ileri 12a medyan | p (BIST $, hücre vs geri kalan)* | p (EEM farkı)* |
|---|---|---|---|---|---|---|
| negatif · indirim değil | 49 | +30% | +18% | -3% | 0.27 | 0.11 |
| negatif · indirim | 55 | -5% | -7% | +13% | 0.48 | 0.80 |
| pozitif · indirim değil | 79 | -13% | -13% | -7% | 0.09 | 0.24 |
| pozitif · indirim | 106 | +19% | -5% | +19% | 0.28 | 0.92 |

*Hücre testleri sonuçlar görüldükten sonra eklendi (ön-kayıtta yoktu); yalnız temkin için, kanıt sayılmaz.

## C) Pozitife dönüş olayları — efektif

| olay | bilindi | reel | politika | TÜFE | 12a içi dip | BIST $ +6 | +12 | +24 | EEM farkı +6 | +12 | +24 | BIST $ bugüne |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2010-12 | 2011-01 | +0,1% | %6.5 | +6,4% | -31% | -6% | -17% | +14% | -9% | -12% | +13% | -45% |
| 2012-05 | 2012-06 | +1,4% | %5.8 | +8,3% | +0% | +30% | +18% | +10% | +14% | +17% | -4% | -36% |
| 2014-02 | 2014-03 | +2,0% | %10.0 | +7,9% | -2% | +3% | -2% | -7% | +1% | -2% | +6% | -32% |
| 2020-10 | 2020-11 | +0,3% | %10.2 | +11,9% | -13% | +1% | -13% | +62% | -11% | -15% | +93% | +32% |
| 2024-09 | 2024-10 | +0,9% | %50.0 | +49,4% | -11% | -9% | +1% | -16% | -9% | -21% | -42% | -16% |

- plasebo usd_6a: n=5, olay ort. +3%, medyan +1%, tüm aylar medyanı +4%, plasebo yüzdeliği 49
- plasebo usd_12a: n=5, olay ort. -3%, medyan -2%, tüm aylar medyanı +4%, plasebo yüzdeliği 25
- plasebo usd_24a: n=5, olay ort. +9%, medyan +10%, tüm aylar medyanı +2%, plasebo yüzdeliği 47
- plasebo fazla_6a: n=5, olay ort. -3%, medyan -9%, tüm aylar medyanı -1%, plasebo yüzdeliği 42
- plasebo fazla_12a: n=5, olay ort. -7%, medyan -12%, tüm aylar medyanı -6%, plasebo yüzdeliği 36
- plasebo fazla_24a: n=5, olay ort. +5%, medyan +6%, tüm aylar medyanı -13%, plasebo yüzdeliği 80

Geçmişin kaydıdır, tahmin değildir. Yatırım tavsiyesi değildir.
