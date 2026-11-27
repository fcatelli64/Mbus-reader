"""Pubblicazione su MQTT con auto-discovery di Home Assistant."""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import threading
import time
import unicodedata
import re
from typing import Callable, Iterator

from . import __version__
from .client import MBusClient
from .config import Config, MeterConfig
from .decoder import QUANTITIES, Record, Telegram

log = logging.getLogger(__name__)

# quantità mostrate come entità "diagnostiche" in Home Assistant
_DIAGNOSTIC = {
    "fabrication_number", "enhanced_id", "bus_address", "access_number", "medium",
    "manufacturer", "parameter_set_id", "model_version", "hardware_version",
    "firmware_version", "software_version", "customer_location", "customer",
    "error_flags", "error_mask", "baudrate", "reset_counter", "datetime",
    "on_time", "operating_time", "battery_operating_time", "battery_change_date",
    "battery_remaining", "manufacturer_specific", "unknown",
}

# decimali mostrati in Home Assistant (altrimenti la portata diventa "0 m³/h")
_PRECISION = {"volume_flow": 3, "volume": 3, "energy": 1, "flow_temperature": 1,
              "return_temperature": 1, "temperature_difference": 1}

_BINARY = (
    ("battery_low", "Batteria scarica", "battery"),
    ("permanent_error", "Errore permanente", "problem"),
    ("temporary_error", "Errore temporaneo", "problem"),
)

Result = "tuple[MeterConfig, list[Telegram] | Exception]"


def slugify(text: str) -> str:
    """Come Home Assistant ricava l'entity_id da nome dispositivo + nome entità."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def merge_state(telegrams: list[Telegram]) -> dict:
    state: dict = {}
    for t in telegrams:
        state.update(t.as_dict())
    return state


class OffsetStore:
    """Correzioni delle letture dei contatori dell'acqua, salvate su file.

    Il contabilizzatore conta gli impulsi a partire da un valore che può non
    coincidere con quello del contatore fisico: la differenza (pochi litri)
    viene memorizzata qui e sommata alla lettura mostrata.
    """

    def __init__(self, path: str | None):
        self.path = path
        self.data: dict[str, dict[str, float]] = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    self.data = json.load(fh)
            except (OSError, ValueError) as exc:
                log.warning("correzioni non leggibili da %s: %s", path, exc)

    def get(self, meter_id: str, n: int) -> float:
        return float(self.data.get(meter_id, {}).get(str(n), 0.0))

    def set(self, meter_id: str, n: int, offset: float) -> None:
        self.data.setdefault(meter_id, {})[str(n)] = offset
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=1)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("correzione non salvata su %s (vale fino al riavvio): %s", self.path, exc)


def build_state(telegrams: list[Telegram], store: OffsetStore | None = None) -> dict:
    """Stato pubblicato: valori del contatore più le letture dell'acqua corrette."""
    state = merge_state(telegrams)
    meter_id = telegrams[0].meter_id
    for n in (1, 2):
        key = f"volume_u{n}"
        if key not in state:
            continue
        raw = state[key]
        offset = store.get(meter_id, n) if store else 0.0
        state[f"water{n}_reading"] = (
            round(raw + offset, 3) if isinstance(raw, (int, float)) else None)
    return state


def bridge_topic(cfg: Config) -> str:
    return f"{cfg.mqtt.base_topic}/bridge/availability"


def discovery_messages(cfg: Config, meter: MeterConfig, telegrams: list[Telegram]) -> dict[str, dict]:
    """Ritorna ``{topic: payload}`` di configurazione per ogni entità."""
    first = telegrams[0]
    uid = f"mbus_{first.meter_id}"
    base = f"{cfg.mqtt.base_topic}/{first.meter_id}"
    device = {
        "identifiers": [uid],
        "name": meter.name,
        "manufacturer": first.manufacturer,
        "model": f"{first.medium} (v{first.version})",
        "serial_number": first.meter_id,
        "sw_version": f"mbus-reader {__version__}",
    }
    common = {
        "state_topic": f"{base}/state",
        # non disponibile se il servizio è fermo oppure il contatore non risponde
        "availability": [{"topic": bridge_topic(cfg)}, {"topic": f"{base}/availability"}],
        "availability_mode": "all",
        "device": device,
    }
    out: dict[str, dict] = {}
    for t in telegrams:
        for r in t.records:
            payload = {
                **common,
                "name": r.name,
                "unique_id": f"{uid}_{r.key}",
                "value_template": f"{{{{ value_json.{r.key} }}}}",
            }
            water = r.quantity == "volume" and r.subunit in (1, 2)
            if water:  # ingressi a impulsi: contatori dell'acqua
                label = meter.input1 if r.subunit == 1 else meter.input2
                payload["name"] = r.name.replace(f"Volume unità {r.subunit}", label, 1)
            if r.unit and r.device_class not in ("date", "timestamp"):
                payload["unit_of_measurement"] = r.unit
            if r.device_class and (r.unit or r.device_class in ("date", "timestamp")):
                payload["device_class"] = r.device_class
            if water and r.unit:
                payload["device_class"] = "water"
            if r.state_class:
                payload["state_class"] = r.state_class
            if r.quantity in _PRECISION and r.unit:
                payload["suggested_display_precision"] = _PRECISION[r.quantity]
            if r.storage or r.quantity in _DIAGNOSTIC or re.search(r"_x[0-9a-f]{2}", r.key):
                payload["entity_category"] = "diagnostic"
            out[f"{cfg.mqtt.discovery_prefix}/sensor/{uid}/{r.key}/config"] = payload
    keys = {r.key for t in telegrams for r in t.records}
    for n, label in ((1, meter.input1), (2, meter.input2)):
        if f"volume_u{n}" not in keys:
            continue
        # campo modificabile: scrivendo la lettura del contatore fisico, il
        # programma memorizza la differenza rispetto al conteggio M-Bus
        out[f"{cfg.mqtt.discovery_prefix}/number/{uid}/water{n}_reading/config"] = {
            **common,
            "name": f"{label} lettura reale",
            "unique_id": f"{uid}_water{n}_reading",
            "command_topic": f"{base}/water{n}/set",
            "value_template": f"{{{{ value_json.water{n}_reading }}}}",
            "unit_of_measurement": "m³",
            "device_class": "water",
            "min": 0, "max": 999999, "step": 0.001, "mode": "box",
            "entity_category": "config",
        }
    out[f"{cfg.mqtt.discovery_prefix}/button/{uid}/read/config"] = {
        "name": "Leggi ora",
        "unique_id": f"{uid}_read",
        "command_topic": f"{base}/read",
        "payload_press": "PRESS",
        "icon": "mdi:refresh",
        # utilizzabile anche se il contatore risulta non disponibile
        "availability": [{"topic": bridge_topic(cfg)}],
        "device": device,
    }
    for key, name, device_class in _BINARY:
        out[f"{cfg.mqtt.discovery_prefix}/binary_sensor/{uid}/{key}/config"] = {
            **common,
            "name": name,
            "unique_id": f"{uid}_{key}",
            "device_class": device_class,
            "entity_category": "diagnostic",
            "value_template": f"{{{{ 'ON' if value_json.{key} else 'OFF' }}}}",
        }
    return out


# ------------------------------------------------------------------ sorgenti

def read_all(cfg: Config, meters: list[MeterConfig] | None = None) -> Iterator[Result]:
    """Legge i contatori (tutti, o solo quelli indicati); un errore non blocca gli altri."""
    meters = cfg.meters if meters is None else meters
    bus = MBusClient(cfg.serial.port, cfg.serial.baudrate, cfg.serial.timeout,
                        cfg.serial.retries, wakeup=cfg.serial.wakeup)
    try:
        bus.open()
    except Exception as exc:
        for meter in meters:
            yield meter, exc
        return
    try:
        for meter in meters:
            try:
                yield meter, bus.read(meter.primary_address, meter.secondary_address)
            except Exception as exc:
                yield meter, exc
            time.sleep(0.2)
    finally:
        bus.close()


_SIM = (
    # chiave, quantità, unità, ingresso impulsi
    ("energy", "energy", "kWh", 0),
    ("cooling_energy", "cooling_energy", "kWh", 0),
    ("volume", "volume", "m³", 0),
    ("volume_u1", "volume", "m³", 1),
    ("volume_u2", "volume", "m³", 2),
    ("power", "power", "W", 0),
    ("volume_flow", "volume_flow", "m³/h", 0),
    ("flow_temperature", "flow_temperature", "°C", 0),
    ("return_temperature", "return_temperature", "°C", 0),
    ("temperature_difference", "temperature_difference", "K", 0),
)


def simulate_all(cfg: Config, meters: list[MeterConfig] | None = None) -> Iterator[Result]:
    """Dati finti ma plausibili, per preparare Home Assistant senza contatori.

    Energia e volume restano volutamente senza valore ("sconosciuto"): numeri
    inventati finirebbero nelle statistiche a lungo termine e nel pannello
    Energia, falsando i consumi quando arriveranno le letture vere.
    """
    for n, meter in enumerate(cfg.meters):
        if meters is not None and meter not in meters:
            continue
        if not meter.secondary_address:
            yield meter, ValueError("per la simulazione serve 'secondary_address'")
            continue
        phase = time.time() / 600 + n
        flow_t = round(62 + 6 * math.sin(phase), 1)
        return_t = round(40 + 4 * math.sin(phase * 0.7 + 1), 1)
        flow = round(0.35 + 0.25 * math.sin(phase * 1.3 + 2), 3)
        delta = round(flow_t - return_t, 2)
        values = {
            "energy": None, "cooling_energy": None, "volume": None,
            "volume_u1": None, "volume_u2": None,
            "power": int(flow * delta * 1163),
            "volume_flow": flow, "flow_temperature": flow_t,
            "return_temperature": return_t, "temperature_difference": delta,
        }
        records = [
            Record(key=k, name=QUANTITIES[q][0] if not sub else f"Volume unità {sub}",
                   quantity=q, value=values[k], unit=u, subunit=sub)
            for k, q, u, sub in _SIM
        ]
        yield meter, [Telegram(
            meter_id=meter.secondary_address, manufacturer="EFE", version=0,
            medium_code=0x0D, access_number=int(time.time() / 60) & 0xFF, status=0,
            records=records,
        )]


# -------------------------------------------------------------------- ciclo

def run(cfg: Config, once: bool = False, source: Callable[..., Iterator] = read_all,
        interval: int | None = None) -> None:
    """Ciclo principale: lettura periodica e pubblicazione su MQTT.

    Nel servizio continuo ascolta anche i comandi di Home Assistant: il
    pulsante "Leggi ora" e la scrittura della lettura reale dei contatori
    dell'acqua.
    """
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg.mqtt.client_id)
    if cfg.mqtt.username:
        client.username_pw_set(cfg.mqtt.username, cfg.mqtt.password)
    client.will_set(bridge_topic(cfg), "offline", qos=1, retain=True)

    base_topic = cfg.mqtt.base_topic
    ha_status = f"{cfg.mqtt.discovery_prefix}/status"
    resend_discovery = threading.Event()
    commands: queue.Queue = queue.Queue()

    def on_connect(c, userdata, flags, reason_code, properties):
        log.info("MQTT connesso a %s:%s (%s)", cfg.mqtt.host, cfg.mqtt.port, reason_code)
        c.subscribe(ha_status)
        if not once:
            for suffix in ("read", "water1/set", "water2/set"):
                c.subscribe(f"{base_topic}/+/{suffix}", qos=1)
        c.publish(bridge_topic(cfg), "online", qos=1, retain=True)
        resend_discovery.set()

    def on_message(c, userdata, msg):
        if msg.topic == ha_status:
            if msg.payload == b"online":
                resend_discovery.set()  # Home Assistant è ripartito
            return
        parts = msg.topic[len(base_topic) + 1:].split("/")
        if len(parts) == 2 and parts[1] == "read":
            commands.put(("read", parts[0]))
        elif len(parts) == 3 and parts[1] in ("water1", "water2") and parts[2] == "set":
            try:
                commands.put(("set", parts[0], int(parts[1][-1]), float(msg.payload)))
            except ValueError:
                log.warning("valore non numerico su %s: %r", msg.topic, msg.payload)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(cfg.mqtt.host, cfg.mqtt.port, keepalive=60)
    client.loop_start()

    interval = interval or cfg.poll_interval
    store = OffsetStore(cfg.state_file)
    by_id: dict[str, MeterConfig] = {
        m.secondary_address: m for m in cfg.meters if m.secondary_address}
    last_read: dict[str, list[Telegram]] = {}
    discovered: set[str] = set()
    failures: dict[str, int] = {}
    last = None
    ok = True

    def publish(meter: MeterConfig, result: list[Telegram]):
        nonlocal last
        meter_id = result[0].meter_id
        by_id[meter_id] = meter
        last_read[meter_id] = result
        base = f"{base_topic}/{meter_id}"
        if meter_id not in discovered:
            discovered.add(meter_id)
            for topic, payload in discovery_messages(cfg, meter, result).items():
                client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=True)
        client.publish(f"{base}/availability", "online", qos=1, retain=True)
        last = client.publish(
            f"{base}/state", json.dumps(build_state(result, store), ensure_ascii=False),
            qos=1, retain=True)

    def poll(meters: list[MeterConfig] | None = None) -> None:
        nonlocal ok
        for meter, result in source(cfg, meters):
            if isinstance(result, Exception):
                ok = False
                failures[meter.name] = failures.get(meter.name, 0) + 1
                log.warning("%s: lettura fallita (%d): %s", meter.name,
                            failures[meter.name], result)
                if failures[meter.name] == 3 and meter.secondary_address:
                    client.publish(f"{base_topic}/{meter.secondary_address}/availability",
                                   "offline", qos=1, retain=True)
                continue
            failures[meter.name] = 0
            publish(meter, result)
            log.info("%s (%s): %d valori pubblicati", meter.name, result[0].meter_id,
                     sum(len(t.records) for t in result))

    def handle(command: tuple) -> None:
        kind, meter_id = command[0], command[1]
        meter = by_id.get(meter_id)
        if meter is None:
            log.warning("comando per un contatore sconosciuto: %s", meter_id)
            return
        if kind == "read":
            log.info("%s: lettura richiesta da Home Assistant", meter.name)
            poll([meter])
            return
        n, value = command[2], command[3]
        poll([meter])  # la lettura reale va confrontata con un conteggio appena letto
        result = last_read.get(meter_id)
        raw = merge_state(result).get(f"volume_u{n}") if result else None
        if not isinstance(raw, (int, float)):
            log.warning("%s: nessun conteggio disponibile per l'ingresso %d, "
                        "lettura reale non applicata", meter.name, n)
            return
        offset = round(value - raw, 3)
        store.set(meter_id, n, offset)
        log.info("%s: ingresso %d allineato a %.3f m³ (conteggio %.3f, correzione %+.3f)",
                 meter.name, n, value, raw, offset)
        publish(meter, result)

    try:
        while True:
            # senza broker le letture andrebbero perse (e consumano batteria)
            for _ in range(60):
                if client.is_connected():
                    break
                time.sleep(0.5)
            else:
                log.warning("broker MQTT %s:%s non raggiungibile", cfg.mqtt.host, cfg.mqtt.port)
                if once:
                    raise SystemExit(1)
                continue
            started = time.monotonic()
            if resend_discovery.is_set():
                resend_discovery.clear()
                discovered.clear()
            poll()
            if once:
                if last is not None:
                    last.wait_for_publish(10)
                if not ok:
                    raise SystemExit(1)
                return
            # fino al prossimo giro si eseguono i comandi di Home Assistant
            deadline = time.monotonic() + max(5.0, interval - (time.monotonic() - started))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    command = commands.get(timeout=remaining)
                except queue.Empty:
                    break
                try:
                    handle(command)
                except Exception as exc:  # un comando sbagliato non ferma il servizio
                    log.warning("comando %s non eseguito: %s", command[0], exc)
    finally:
        # Arresto pulito del servizio continuo: il "last will" non scatterebbe.
        # Dopo una lettura singola (--once) i valori devono invece restare
        # visibili in Home Assistant.
        if client.is_connected() and not once:
            client.publish(bridge_topic(cfg), "offline", qos=1, retain=True).wait_for_publish(5)
        client.loop_stop()
        client.disconnect()


# ---------------------------------------------------------------- dashboard

def dashboard(cfg: Config) -> dict:
    """Vista Lovelace con una colonna per contatore.

    Gli entity_id sono quelli che Home Assistant genera da nome del dispositivo
    + nome dell'entità (es. ``sensor.calore_interno_1_energia``).
    """
    def eid(meter: MeterConfig, quantity: str) -> str:
        return f"sensor.{slugify(meter.name + ' ' + QUANTITIES[quantity][0])}"

    sections = []
    for meter in cfg.meters:
        sections.append({
            "type": "grid",
            "cards": [
                {"type": "heading", "heading": meter.name, "icon": "mdi:radiator"},
                {"type": "tile", "entity": eid(meter, "energy"), "name": "Energia"},
                {"type": "tile", "entity": eid(meter, "power"), "name": "Potenza"},
                {"type": "tile", "entity": eid(meter, "flow_temperature"), "name": "Mandata"},
                {"type": "tile", "entity": eid(meter, "return_temperature"), "name": "Ritorno"},
                {"type": "tile", "entity": eid(meter, "volume_flow"), "name": "Portata"},
                {"type": "tile", "entity": eid(meter, "temperature_difference"), "name": "ΔT"},
                {"type": "history-graph", "hours_to_show": 24, "entities": [
                    {"entity": eid(meter, "flow_temperature"), "name": "Mandata"},
                    {"entity": eid(meter, "return_temperature"), "name": "Ritorno"},
                ]},
                {"type": "history-graph", "hours_to_show": 24, "entities": [
                    {"entity": eid(meter, "power"), "name": "Potenza"},
                ]},
                {"type": "statistics-graph", "title": "Consumo giornaliero",
                 "chart_type": "bar", "period": "day", "days_to_show": 30,
                 "stat_types": ["change"],
                 "entities": [{"entity": eid(meter, "energy"), "name": "Energia"}]},
            ],
        })
    summary = {
        "type": "grid",
        "cards": [
            {"type": "heading", "heading": "Confronto", "icon": "mdi:chart-bar"},
            {"type": "statistics-graph", "title": "Consumo giornaliero per contatore",
             "chart_type": "bar", "period": "day", "days_to_show": 30,
             "stat_types": ["change"],
             "entities": [{"entity": eid(m, "energy"), "name": m.name} for m in cfg.meters]},
            {"type": "history-graph", "title": "Potenza", "hours_to_show": 24,
             "entities": [{"entity": eid(m, "power"), "name": m.name} for m in cfg.meters]},
        ],
    }
    if len(cfg.meters) > 1:
        sections.insert(0, summary)
    def ent(domain: str, meter: MeterConfig, name: str) -> str:
        return f"{domain}.{slugify(meter.name + ' ' + name)}"

    # vista per allineare le letture dell'acqua al contatore fisico
    align = [{
        "type": "grid",
        "cards": [
            {"type": "heading", "heading": meter.name, "icon": "mdi:water"},
            {"type": "entities", "entities": [
                {"entity": ent("button", meter, "Leggi ora"), "name": "Leggi ora"},
                {"entity": ent("number", meter, f"{meter.input1} lettura reale"),
                 "name": f"{meter.input1} · lettura reale"},
                {"entity": ent("sensor", meter, meter.input1),
                 "name": f"{meter.input1} · conteggio contabilizzatore"},
                {"entity": ent("number", meter, f"{meter.input2} lettura reale"),
                 "name": f"{meter.input2} · lettura reale"},
                {"entity": ent("sensor", meter, meter.input2),
                 "name": f"{meter.input2} · conteggio contabilizzatore"},
            ]},
        ],
    } for meter in cfg.meters]
    return {"views": [
        {"title": "Calore", "path": "calore", "icon": "mdi:radiator",
         "type": "sections", "max_columns": 3, "sections": sections},
        {"title": "Allineamento acqua", "path": "acqua", "icon": "mdi:water-sync",
         "type": "sections", "max_columns": 3, "sections": align},
    ]}


def panel_config(cfg: Config) -> dict:
    """Blocco ``panel_custom`` per configuration.yaml (pannello per smartphone)."""
    return {"panel_custom": [{
        "name": "calore-panel",
        "sidebar_title": "Calore",
        "sidebar_icon": "mdi:radiator",
        "url_path": "calore",
        "module_url": "/local/calore-panel.js?v=1",
        "config": {
            "title": "Home",
            "group_title": "Condomini",
            # name = testo mostrato (modificabile); id = prefisso delle entità (non toccare)
            "meters": [{"name": m.name.replace("_", " "), "id": slugify(m.name)}
                       for m in cfg.meters],
        },
    }]}
