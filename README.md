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
- **Raspberry Pi 2**: non ha il Wi-Fi integrato, serve una chiavetta Wi-Fi USB
  (oppure il cavo Ethernet). Basta Raspberry Pi OS Lite.
- L'adattatore compare come `/dev/ttyUSB0`. Il percorso stabile si trova con
  `ls -l /dev/serial/by-id/`.

## 2. Home Assistant

1. Installa l'add-on **Mosquitto broker** e l'integrazione **MQTT**.
2. Crea un utente dedicato (es. `mbus`) in *Impostazioni → Persone → Utenti*.

## 3. Installazione sul Raspberry

```bash
sudo apt update && sudo apt install -y git python3-venv
sudo useradd --system --groups dialout --home /opt/mbus-reader mbus
sudo git clone https://github.com/fcatelli64/Mbus-reader.git /opt/mbus-reader
cd /opt/mbus-reader
sudo python3 -m venv .venv
sudo .venv/bin/pip install .

sudo mkdir /etc/mbus-reader
sudo cp config.example.yaml /etc/mbus-reader/config.yaml
sudo nano /etc/mbus-reader/config.yaml      # porta seriale e dati MQTT
sudo chown mbus /etc/mbus-reader/config.yaml && sudo chmod 600 /etc/mbus-reader/config.yaml
```

## 4. Prima prova

```bash
cd /opt/mbus-reader
sudo -u mbus .venv/bin/mbus-reader -c /etc/mbus-reader/config.yaml read --raw
```

Deve comparire la tabella dei valori. Se va in timeout:

- `mbus-reader -c … -v read` mostra i byte trasmessi e ricevuti;
- `mbus-reader -c … scan` cerca il contatore sugli indirizzi 0–250;
- prova `baudrate: 300` o `9600`;
- prova l'indirizzo secondario (`secondary_address: "61382914"`, il numero
  stampato sul frontale);
- controlla che l'adattatore sia un *master* M-Bus (deve fornire circa 30 V sul bus).

La riga `RAW:` è il telegramma grezzo: conservala, serve per ogni diagnosi
(`mbus-reader decode <hex>` la decodifica anche senza contatore).

Poi una pubblicazione di prova: `mbus-reader -c … run --once`. In Home
Assistant il dispositivo compare sotto *Impostazioni → Dispositivi e servizi → MQTT*.

## 5. Servizio

```bash
sudo cp systemd/mbus-reader.service /etc/systemd/system/
sudo systemctl enable --now mbus-reader
journalctl -u mbus-reader -f
```

## Note

- **Batteria**: il SensoStar 2 è alimentato a batteria e ogni lettura M-Bus ne
  consuma un po'; il contatore limita inoltre il numero di letture. Il default
  è una lettura ogni 15 minuti (`poll_interval: 900`): prima di scendere,
  verifica sul manuale Engelmann la frequenza di lettura ammessa.
- **Pannello Energia**: l'entità *Energia* (kWh, `total_increasing`) è già
  utilizzabile nelle statistiche di Home Assistant.
- I valori storici (data di riferimento, mesi precedenti) e i dati di servizio
  sono creati come entità *diagnostiche*.
- Con un solo contatore sul bus l'indirizzo `254` funziona sempre; con più
  contatori usa `secondary_address`.

## Sviluppo

```bash
pip install -e ".[dev]"
pytest
```
