# SMI Bot – powiadomienia Telegram ze strategii SMI

Bot pobiera świece (Binance dla krypto, Yahoo Finance dla akcji, forexu, surowców i GPW), liczy SMI tak samo jak Twój skrypt Pine i wysyła wiadomość na Telegram, gdy:

- pojawi się **pierwszy czerwony trójkąt** (SMI przebija 65 w górę),
- pojawi się **pierwszy zielony trójkąt** (SMI przebija -65 w dół),
- strategia daje **wejście LONG** (SMI < -75) lub **SHORT** (SMI > 75),
- strategia **zamyka pozycję** (SMI > 60 dla long, SMI < -60 dla short).

Sygnał przychodzi po zamknięciu świecy, czyli tak samo jak alert „once per bar close” w TradingView.

---

## 1. Bot na Telegramie (5 minut)

1. W Telegramie napisz do **@BotFather**, wyślij `/newbot`, podaj nazwę i login bota (login musi kończyć się na `bot`).
2. BotFather odpowie tokenem w stylu `123456789:AAH...`. To jest **TELEGRAM_TOKEN**.
3. Otwórz swojego nowego bota i wyślij mu dowolną wiadomość, np. `hej`.
4. W przeglądarce otwórz `https://api.telegram.org/bot<TOKEN>/getUpdates` (w miejsce `<TOKEN>` wstaw swój token).
   Znajdź `"chat":{"id":123456789` – ta liczba to **TELEGRAM_CHAT_ID**.

## 2. Ustawienia (już gotowe)

Bot ma już wpisane instrumenty i interwały **H1 + H4**:

| Nazwa | Symbol Yahoo | Co to jest |
|---|---|---|
| US100 | `NQ=F` | kontrakt futures na Nasdaq 100 |
| US500 | `ES=F` | kontrakt futures na S&P 500 |
| GOLD | `PAXGUSDT` (Binance) | złoto – PAXG notowany 1:1 do XAUUSD spot |
| WTI | `CL=F` | ropa WTI (futures) |
| NATGAS | `NG=F` | gaz ziemny (futures) |
| USDJPY | `JPY=X` | forex |
| GBPJPY | `GBPJPY=X` | forex |
| USDCHF | `CHF=X` | forex |
| EURCHF | `EURCHF=X` | forex |
| GBPCHF | `GBPCHF=X` | forex |
| AUDCHF | `AUDCHF=X` | forex |
| EURUSD | `EURUSD=X` | forex |
| VIX | `^VIX` | indeks zmienności CBOE |
| WHEAT | `ZW=F` | pszenica (futures CBOT) |
| CORN | `ZC=F` | kukurydza (futures CBOT) |
| COCOA | `CC=F` | kakao (futures ICE US) |

Yahoo nie ma świec H4, więc bot składa je z H1. Pierwsza świeca dnia zaczyna się o 17:00 czasu nowojorskiego (23:00 w Polsce), tak jak na forexie u większości brokerów. Jeśli SMI na H4 nie zgadza się z Twoim wykresem, zmień `H4_ANCHOR_NY_HOUR` na górze pliku.

---

## Opcja A – w chmurze, za darmo (GitHub Actions), komputer może być wyłączony

1. Załóż konto na github.com i utwórz **publiczne** repozytorium (dla publicznych repozytoriów minuty Actions są darmowe bez limitu).
   Token nie trafi do kodu, bo zapiszesz go jako sekret.
2. Wrzuć do repozytorium `smi_bot.py`, a plik `smi-bot.yml` umieść w folderze `.github/workflows/`.
   Pełna ścieżka: `.github/workflows/smi-bot.yml`.
3. W repozytorium wejdź w **Settings → Secrets and variables → Actions → New repository secret** i dodaj:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Wejdź w zakładkę **Actions → SMI Bot → Run workflow**, żeby uruchomić bota ręcznie i sprawdzić, czy działa.

Bot sprawdza rynek co 15 minut. Musisz jednak wiedzieć o kilku ograniczeniach:

- GitHub często opóźnia start o 5–20 minut, więc na interwałach 1m i 5m to rozwiązanie się nie sprawdzi. Do 15m, 1h, 4h i 1d jest w porządku.
- W repozytorium prywatnym masz 2000 darmowych minut miesięcznie. Wtedy zmień cron na `"0 * * * *"` (co godzinę) albo `"*/30 * * * *"`.
- Jeśli przez 60 dni nic nie zmienisz w repozytorium, GitHub wyłączy harmonogram. Wystarczy wtedy zrobić dowolny commit albo kliknąć „Enable workflow”.

## Opcja B – na własnym komputerze / Raspberry Pi / VPS

Wymagany jest Python 3.8+ (python.org). Nie trzeba instalować żadnych bibliotek.

Windows (cmd):

```
set TELEGRAM_TOKEN=123456789:AAH...
set TELEGRAM_CHAT_ID=123456789
python smi_bot.py --test
python smi_bot.py --loop
```

Linux/macOS:

```
export TELEGRAM_TOKEN=123456789:AAH...
export TELEGRAM_CHAT_ID=123456789
python3 smi_bot.py --test
python3 smi_bot.py --loop
```

Zamiast ustawiać zmienne możesz też wpisać token i chat id bezpośrednio w `smi_bot.py`.
W trybie `--loop` bot sprawdza rynek kilkanaście sekund po zamknięciu każdej świecy. Działa tylko wtedy, gdy komputer jest włączony.

---

## Przydatne komendy

| Komenda | Co robi |
|---|---|
| `python smi_bot.py --test` | wysyła testową wiadomość na Telegram |
| `python smi_bot.py --status` | pokazuje aktualne SMI i pozycję strategii (porównaj z TradingView) |
| `python smi_bot.py --loop` | działa non stop |
| `python smi_bot.py` | jedno sprawdzenie (dla crona / GitHub Actions) |

## Uwagi

- **Aktualne ustawienie alertów:** tylko WEJŚCIE LONG (SMI przebija -70 w dół) i WEJŚCIE SHORT (SMI przebija +70 w górę), przy każdym przebiciu, niezależnie od otwartej pozycji. Trójkąty i zamknięcia są wyłączone (`ALERT_TRIANGLES`, `ALERT_EXITS`, `ENTRIES_IGNORE_POSITION` na górze `smi_bot.py`).
- **US100, US500, WTI, NATGAS, WHEAT, CORN i COCOA to kontrakty futures z Yahoo**, a nie CFD Twojego brokera. Kształt wykresu jest prawie ten sam, ale ceny mogą się różnić o kilka punktów, a przy rolowaniu kontraktu (zwłaszcza NATGAS i WTI) nawet bardziej. Dlatego SMI może się minimalnie różnić od wykresu CFD.
- **Porównaj z TradingView.** Wartość SMI z `--status` powinna być taka sama lub bardzo zbliżona do tej z wykresu dla tego samego symbolu i interwału. Małe różnice mogą wynikać z innego źródła danych: Binance a inna giełda, Yahoo a dostawca TradingView.
- Pozycja strategii (long/short/brak) jest liczona na historii świec pobranej przez bota. Może więc czasem różnić się od TradingView, który ma inny początek historii. Nie dotyczy to trójkątów.
- Alert przychodzi zwykle 1–15 minut po zamknięciu świecy H1/H4. W GitHub Actions może dojść jeszcze opóźnienie po stronie GitHuba.
- Czasy w wiadomościach są czasem polskim i oznaczają otwarcie świecy.
- To narzędzie do powiadomień, a nie rada inwestycyjna.
