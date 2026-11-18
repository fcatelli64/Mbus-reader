# mbus-reader

Legge un contabilizzatore di calore **Engelmann SensoStar 2** (o qualsiasi altro
contatore M-Bus cablato) tramite un adattatore USB/M-Bus collegato a un
Raspberry Pi e pubblica i valori su **Home Assistant** via MQTT, con creazione
automatica delle entità (MQTT discovery).

```
SensoStar 2 ──M-Bus (2 fili)── adattatore USB/M-Bus ──USB── Raspberry Pi ──Wi-Fi/MQTT── Home Assistant
```

Le entità non sono cablate nel codice: il programma decodifica tutto ciò che il
contatore trasmette (energia, volume, potenza, portata, temperature di mandata e
ritorno, ΔT, valori storici, ingressi impulsi, data/ora, errori…) e crea
un'entità per ogni valore.

## 1. Hardware

- **Cavo M-Bus**: i due fili del cavo M-Bus che esce dal contatore vanno ai due
  morsetti M-Bus dell'adattatore. La polarità è indifferente. Gli altri fili
  del contatore (i 2 ingressi impulsi) non vanno collegati all'adattatore.
- **Raspberry Pi 3**: installa *Raspberry Pi OS Lite (64-bit)* con Raspberry Pi
  Imager, impostando già lì Wi-Fi (solo 2,4 GHz), utente e SSH.
- L'adattatore compare come `/dev/ttyUSB0`. Il percorso stabile si trova con
  `ls -l /dev/serial/by-id/`.

## 2. Home Assistant

1. Installa l'add-on **Mosquitto broker** e l'integrazione **MQTT**.
2. Crea un utente dedicato (es. `mbus`) in *Impostazioni → Persone → Utenti*.

## 3. Installazione sul Raspberry

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/fcatelli64/Mbus-reader.git
cd Mbus-reader
sudo ./install.sh
sudo nano /etc/mbus-reader/config.yaml      # dati MQTT e contatori
```

Lo script installa il programma in `/opt/mbus-reader`, crea l'utente di
servizio `mbus`, la configurazione e il servizio systemd (non ancora avviato).
Per aggiornare in futuro: `git pull && sudo ./install.sh`.

## 4. Prima prova

```bash
sudo -u mbus mbus-reader -c /etc/mbus-reader/config.yaml read --raw
```

Deve comparire la tabella dei valori. Se va in timeout:

- `mbus-reader -c … -v read` mostra i byte trasmessi e ricevuti;
- `mbus-reader -c … scan` cerca il contatore sugli indirizzi 0–250;
- prova `baudrate: 300` o `9600`;
- con un solo contatore collegato, togli `secondary_address` dalla
  configurazione: viene usato l'indirizzo 254, a cui risponde qualsiasi contatore;
- controlla che l'adattatore sia un *master* M-Bus (deve fornire circa 30 V sul bus).

La riga `RAW:` è il telegramma grezzo: conservala, serve per ogni diagnosi
(`mbus-reader decode <hex>` la decodifica anche senza contatore).

Poi una pubblicazione di prova: `mbus-reader -c … run --once`. In Home
Assistant il dispositivo compare sotto *Impostazioni → Dispositivi e servizi → MQTT*.

## 5. Servizio

```bash
sudo systemctl start mbus-reader
journalctl -u mbus-reader -f
```

## Più contatori

I contatori si collegano tutti in parallelo sugli stessi due fili del bus.
Non serve riprogrammarli: ognuno viene interrogato con il proprio numero di
serie (indirizzo secondario), stampato sul frontale. Basta aggiungere un blocco
per contatore sotto `meters:` e riavviare il servizio.

Verifica che l'adattatore USB/M-Bus sia dichiarato per almeno 6 dispositivi
(ogni contatore assorbe circa 1,5 mA dal bus).

## Preparare Home Assistant senza contatori

Su qualsiasi PC con Python (non serve il Raspberry né l'adattatore):

```bash
pip install .
mbus-reader -c config.yaml simulate      # pubblica dati finti ogni 60 s; Ctrl+C per fermare
mbus-reader -c config.yaml dashboard > dashboard.yaml
```

- `simulate` crea in Home Assistant gli stessi dispositivi ed entità che
  creeranno le letture vere (stessi identificativi, basati sul numero di
  serie), con temperature, portata e potenza inventate. **Energia e volume
  restano "sconosciuto"** di proposito: valori finti sporcherebbero le
  statistiche dei consumi.
- `dashboard` stampa una vista con una sezione per contatore più il confronto.
  In Home Assistant: nuova dashboard → *Modifica* → ⋮ → *Editor di
  configurazione testuale* → incolla il contenuto.

Quando arrivano i contatori veri non c'è nulla da rifare: le entità sono le
stesse e iniziano a ricevere i dati reali.

## Note

- **Batteria**: il SensoStar 2 è alimentato a batteria e ogni lettura M-Bus ne
  consuma un po'; il contatore limita inoltre il numero di letture. Il default
  è una lettura ogni 15 minuti (`poll_interval: 900`): prima di scendere,
  verifica sul manuale Engelmann la frequenza di lettura ammessa.
- **Pannello Energia**: l'entità *Energia* (kWh, `total_increasing`) è già
  utilizzabile nelle statistiche di Home Assistant.
- I valori storici (data di riferimento, mesi precedenti) e i dati di servizio
  sono creati come entità *diagnostiche*.
- Se il servizio si ferma o un contatore non risponde per 3 letture di fila,
  le sue entità diventano "non disponibile".

## Sviluppo

```bash
pip install -e ".[dev]"
pytest
```
