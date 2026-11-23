#!/bin/bash
# Installa (o aggiorna) mbus-reader su Raspberry Pi OS.
# Uso, dalla cartella del repository:  sudo ./install.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Esegui con sudo: sudo ./install.sh" >&2
    exit 1
fi

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/mbus-reader
CONF=/etc/mbus-reader/config.yaml

echo "==> Pacchetti di sistema"
apt-get update -qq
apt-get install -y -qq python3-venv

echo "==> Utente di servizio 'mbus'"
id mbus >/dev/null 2>&1 || useradd --system --groups dialout --home "$DEST" --shell /usr/sbin/nologin mbus

echo "==> Programma in $DEST"
mkdir -p "$DEST"
[ -d "$DEST/.venv" ] || python3 -m venv "$DEST/.venv"
# niente residui di installazioni precedenti: si ricostruisce sempre dai sorgenti
rm -rf "$SRC/build" "$SRC"/src/*.egg-info
"$DEST/.venv/bin/pip" install --quiet --upgrade --force-reinstall --no-deps "$SRC"
"$DEST/.venv/bin/pip" install --quiet "$SRC"
"$DEST/.venv/bin/python" -c "from mbus_reader.ha import run, panel_config; from mbus_reader.cli import main" \
    || { echo "ERRORE: installazione incompleta (vedi sopra)" >&2; exit 1; }
ln -sf "$DEST/.venv/bin/mbus-reader" /usr/local/bin/mbus-reader

echo "==> Configurazione"
mkdir -p /etc/mbus-reader
if [ ! -f "$CONF" ]; then
    cp "$SRC/config.example.yaml" "$CONF"
    NEW_CONF=1
fi
chown mbus "$CONF"
chmod 600 "$CONF"

echo "==> Servizio systemd"
cp "$SRC/systemd/mbus-reader.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --quiet mbus-reader

if [ "${NEW_CONF:-0}" = 1 ]; then
    cat <<MSG

Installazione completata. Ora:
  1. sudo nano $CONF            (dati MQTT e contatori)
  2. sudo -u mbus mbus-reader -c $CONF read --raw     (prova di lettura)
  3. sudo systemctl start mbus-reader
MSG
else
    systemctl try-restart mbus-reader   # riavvia solo se era già in esecuzione
    echo
    echo "Aggiornamento completato (config esistente mantenuta)."
    echo "Stato del servizio: $(systemctl is-active mbus-reader || true)"
fi
