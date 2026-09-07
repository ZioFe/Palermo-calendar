# Palermo Calendar

Feed iCalendar non ufficiale per seguire le partite della prima squadra del Palermo FC
nell'app Calendario di Apple.

## Come funziona

La GitHub Action esegue `update_calendar.py` ogni 6 ore. Lo script legge la pagina
ufficiale della prima squadra del Palermo e rigenera `palermo.ics`.

Quando sul sito del Palermo un orario è `00:00`, viene trattato come **orario da definire**
e la partita viene pubblicata come evento dell'intera giornata. Quando l'orario ufficiale
compare sul sito, lo stesso evento viene trasformato in un evento con orario.

Le amichevoli estive 2026 già note sono incluse nel file iniziale. La scoperta totalmente
automatica di nuove amichevoli annunciate solo tramite news non è ancora garantita.

## URL da usare su iPhone

Dopo aver caricato questi file nel repository, usa l'URL RAW di `palermo.ics` come
calendario in abbonamento. Se il repository si chiama `palermo-calendar`, la forma sarà:

`https://raw.githubusercontent.com/TUO-USERNAME/palermo-calendar/main/palermo.ics`

Su iPhone: Calendario → Calendari → Aggiungi calendario → Aggiungi calendario in abbonamento.

## Avvio iniziale

Vai su **Actions** → **Aggiorna calendario Palermo** → **Run workflow**.
Dopo il primo avvio comparirà/si aggiornerà `palermo.ics`.
