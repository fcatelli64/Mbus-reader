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

## Lettura con testina ottica

Il SensoStar 2 ha anche un'interfaccia ottica sul frontale (la finestrella
rotonda), che parla lo stesso protocollo M-Bus. Con una testina IR a 3,3 V
(IEC 62056-21, uscita seriale TTL) collegata ai pin del Raspberry si può
leggere il contatore senza cavo M-Bus: utile per le prove, **non** per la
lettura continua, perché l'interfaccia ottica va attivata a mano e consuma batteria.

Collegamento ai pin del Raspberry Pi 3:

| Testina | Raspberry |
|---|---|
| VCC 3,3 V | pin 1 (3V3) — **mai** i pin 2/4 a 5 V |
| GND | pin 6 |
| TX (dati dalla testina) | pin 10 (GPIO15, RXD) |
| RX (dati verso la testina) | pin 8 (GPIO14, TXD) |

Preparazione (una volta sola):

```bash
sudo raspi-config nonint do_serial_hw 0      # abilita la porta seriale
sudo raspi-config nonint do_serial_cons 1    # niente console di login sulla seriale
echo "dtoverlay=disable-bt" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

L'ultima riga spegne il Bluetooth del Pi 3: è necessario, perché la porta
seriale che resta libera altrimenti non supporta la parità richiesta da M-Bus.

Nella configurazione: `port: /dev/serial0`, `baudrate: 2400`, senza `wakeup`.
Procedura verificata su un SensoStar 2 del 2016:

1. premi il tasto del contatore: l'interfaccia ottica resta attiva 60 secondi;
2. appoggia la testina sulla finestrella. **Nel contatore i due LED sono uno
   sopra l'altro**: se nella testina sono affiancati, va ruotata di un quarto
   di giro (cavo di lato);
3. lancia `mbus-reader -c … read --raw`.

Con tutti i contatori elencati nella configurazione (nome e numero di serie),
`mbus-reader -c … optical` fa tutto da solo: cerca la risposta, riconosce il
contatore dal numero di serie, mostra i valori e li pubblica su Home Assistant
sotto il nome giusto. Va ripetuto contatore per contatore.

Per trovare la posizione, `mbus-reader -c … aim` invia richieste a ripetizione
e segnala subito quando il contatore risponde. Il contatore ammette al massimo
300 letture ottiche al giorno. `probe` e l'opzione `wakeup` servono solo per
altri modelli che richiedono una sequenza di risveglio.

## Pannello per smartphone

`homeassistant/calore-panel.js` è un pannello autonomo per Home Assistant: una
pagina principale con la potenza totale e un riquadro per contabilizzatore, più
una pagina di dettaglio per ciascuno (valori istantanei, energia, potenza delle
ultime 24 ore, consumi degli ultimi 6 mesi). Non ha barra superiore e non
richiede HACS né altre integrazioni.

1. Copia `calore-panel.js` nella cartella `www` della configurazione di Home
   Assistant (`/config/www/`; se la cartella non esiste, creala).
2. Genera la configurazione con `mbus-reader -c /etc/mbus-reader/config.yaml panel`
   e incollala in fondo a `configuration.yaml`. In `name` puoi cambiare il testo
   mostrato (es. "Di Pietro"); `id` deve restare com'è.
3. Riavvia Home Assistant: nella barra laterale compare "Calore".

Opzioni utili in `config:`:

- `weather: weather.nome_entita` per scegliere l'entità meteo (di default la prima disponibile);
- per contatore, `entities: {cooling: sensor.xxx}` per indicare l'entità
  dell'energia di raffrescamento (compaiono il secondo contatore e le barre blu);
  con le altre chiavi (`energy`, `power`, `flow`, `t_in`, `t_out`) si può
  sostituire qualsiasi entità.
- per contatore, `entities: {water_hot: sensor.xxx, water_cold: sensor.yyy}` per
  i volumi dei due ingressi impulsi (acqua calda e fredda dell'appartamento);
  di default `sensor.<id>_acqua_calda` e `sensor.<id>_acqua_fredda`;
- per contatore, `water_offset: {hot: 12.34, cold: 56.78}` (m³) per allineare la
  lettura mostrata al rullo del contatore meccanico.

La pagina principale mostra la potenza totale, l'energia e l'acqua del mese in
corso; il pulsante *Annuale* apre i grafici mese per mese (riscaldamento,
raffrescamento, acqua) sommati su tutti i contabilizzatori.

Aprendo `/calore?demo` il pannello mostra dati di esempio. Dopo aver aggiornato
il file, aumenta il numero in `?v=1` e riavvia, altrimenti il browser usa la
copia vecchia. Su smartphone la barra laterale è già nascosta; su PC si può
nascondere dal profilo utente ("Nascondi sempre la barra laterale").

## Lettura a richiesta e allineamento dei contatori dell'acqua

Con il servizio continuo attivo, ogni contabilizzatore ha in Home Assistant:

- un pulsante **Leggi ora**, che fa partire subito una lettura M-Bus di quel
  contabilizzatore senza aspettare il giro successivo;
- due campi **lettura reale** (acqua fredda e calda), modificabili.

Il contabilizzatore conta gli impulsi dei contatori dell'acqua a partire da un
valore che può differire di qualche decina di litri da quello del contatore
fisico. Per allineare: premi *Leggi ora*, leggi il contatore fisico e scrivi
il valore nel campo *lettura reale*. Il programma rilegge il contabilizzatore,
memorizza la differenza in `/var/lib/mbus-reader/state.json` e da quel momento
mostra la lettura corretta (anche nel pannello per smartphone).

La correzione riguarda solo la lettura mostrata: i sensori *Acqua fredda* e
*Acqua calda*, da cui si calcolano i consumi, restano il conteggio originale,
così l'allineamento non genera consumi fittizi.

`mbus-reader -c … dashboard` genera anche la vista "Allineamento acqua" con
pulsante, campi e conteggi di tutti i contabilizzatori.

## Note

- **Frequenza di lettura**: il manuale del SensoStar 2/2+ (certificato PTB025)
  limita le letture giornaliere in base al numero di contatori sul bus. Con
  indirizzo secondario: 275 al giorno con 3 contatori, 170 con 20; con
  indirizzo primario 655 e 485. Le letture non usate si accumulano. Il default
  di una lettura ogni 15 minuti (`poll_interval: 900`, 96 al giorno) resta
  ampiamente entro il limite; sotto i 10 minuti è meglio non scendere.
- **Interfaccia ottica**: al massimo 300 letture al giorno.
- **Indirizzo primario** di fabbrica: 0, uguale per tutti i contatori; per
  questo con più contatori si usa l'indirizzo secondario (numero di serie).
- **Cavo del contatore** (versione M-Bus + 2 ingressi impulsi, 6 fili): grigio
  e rosa sono l'M-Bus; bianco/marrone e giallo/verde sono i due ingressi impulsi.
- Mentre il contatore comunica via M-Bus, tasto e interfaccia ottica non sono
  utilizzabili, e viceversa.
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
