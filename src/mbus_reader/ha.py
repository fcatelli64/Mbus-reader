"""Pubblicazione su MQTT con auto-discovery di Home Assistant."""

from __future__ import annotations

import json
import logging
import math
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
            if r.unit and r.device_class not in ("date", "timestamp"):
                payload["unit_of_measurement"] = r.unit
            if r.device_class and (r.unit or r.device_class in ("date", "timestamp")):
                payload["device_class"] = r.device_class
            if r.state_class:
                payload["state_class"] = r.state_class
            if r.quantity in _PRECISION and r.unit:
                payload["suggested_display_precision"] = _PRECISION[r.quantity]
            if r.storage or r.quantity in _DIAGNOSTIC:
                payload["entity_category"] = "diagnostic"
            out[f"{cfg.mqtt.discovery_prefix}/sensor/{uid}/{r.key}/config"] = payload
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

def read_all(cfg: Config) -> Iterator[Result]:
    """Legge tutti i contatori configurati; un errore non blocca gli altri."""
    bus = MBusClient(cfg.serial.port, cfg.serial.baudrate, cfg.serial.timeout,
                        cfg.serial.retries, wakeup=cfg.serial.wakeup)
    try:
        bus.open()
    except Exception as exc:
        for meter in cfg.meters:
            yield meter, exc
        return
    try:
        for meter in cfg.meters:
            try:
                yield meter, bus.read(meter.primary_address, meter.secondary_address)
            except Exception as exc:
                yield meter, exc
            time.sleep(0.2)
    finally:
        bus.close()


_SIM = (
    # chiave, quantità, unità
    ("energy", "energy", "kWh"),
    ("volume", "volume", "m³"),
    ("power", "power", "W"),
    ("volume_flow", "volume_flow", "m³/h"),
    ("flow_temperature", "flow_temperature", "°C"),
    ("return_temperature", "return_temperature", "°C"),
    ("temperature_difference", "temperature_difference", "K"),
)


def simulate_all(cfg: Config) -> Iterator[Result]:
    """Dati finti ma plausibili, per preparare Home Assistant senza contatori.

    Energia e volume restano volutamente senza valore ("sconosciuto"): numeri
    inventati finirebbero nelle statistiche a lungo termine e nel pannello
    Energia, falsando i consumi quando arriveranno le letture vere.
    """
    for n, meter in enumerate(cfg.meters):
        if not meter.secondary_address:
            yield meter, ValueError("per la simulazione serve 'secondary_address'")
            continue
        phase = time.time() / 600 + n
        flow_t = round(62 + 6 * math.sin(phase), 1)
        return_t = round(40 + 4 * math.sin(phase * 0.7 + 1), 1)
        flow = round(0.35 + 0.25 * math.sin(phase * 1.3 + 2), 3)
        delta = round(flow_t - return_t, 2)
        values = {
            "energy": None, "volume": None,
            "power": int(flow * delta * 1163),
            "volume_flow": flow, "flow_temperature": flow_t,
            "return_temperature": return_t, "temperature_difference": delta,
        }
        records = [
            Record(key=k, name=QUANTITIES[q][0], quantity=q, value=values[k], unit=u)
            for k, q, u in _SIM
        ]
        yield meter, [Telegram(
            meter_id=meter.secondary_address, manufacturer="EFE", version=0,
            medium_code=0x04, access_number=int(time.time() / 60) & 0xFF, status=0,
            records=records,
        )]


# -------------------------------------------------------------------- ciclo

def run(cfg: Config, once: bool = False, source: Callable[[Config], Iterator] = read_all,
        interval: int | None = None) -> None:
    """Ciclo principale: lettura periodica e pubblicazione su MQTT."""
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg.mqtt.client_id)
    if cfg.mqtt.username:
        client.username_pw_set(cfg.mqtt.username, cfg.mqtt.password)
    client.will_set(bridge_topic(cfg), "offline", qos=1, retain=True)

    ha_status = f"{cfg.mqtt.discovery_prefix}/status"
    resend_discovery = threading.Event()

    def on_connect(c, userdata, flags, reason_code, properties):
        log.info("MQTT connesso a %s:%s (%s)", cfg.mqtt.host, cfg.mqtt.port, reason_code)
        c.subscribe(ha_status)
        c.publish(bridge_topic(cfg), "online", qos=1, retain=True)
        resend_discovery.set()

    def on_message(c, userdata, msg):
        if msg.topic == ha_status and msg.payload == b"online":
            resend_discovery.set()  # Home Assistant è ripartito

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(cfg.mqtt.host, cfg.mqtt.port, keepalive=60)
    client.loop_start()

    interval = interval or cfg.poll_interval
    discovered: set[str] = set()
    failures: dict[str, int] = {}
    last = None
    ok = True
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
            for meter, result in source(cfg):
                if isinstance(result, Exception):
                    ok = False
                    failures[meter.name] = failures.get(meter.name, 0) + 1
                    log.warning("%s: lettura fallita (%d): %s", meter.name,
                                failures[meter.name], result)
                    if failures[meter.name] == 3 and meter.secondary_address:
                        client.publish(
                            f"{cfg.mqtt.base_topic}/{meter.secondary_address}/availability",
                            "offline", qos=1, retain=True)
                    continue
                failures[meter.name] = 0
                meter_id = result[0].meter_id
                base = f"{cfg.mqtt.base_topic}/{meter_id}"
                if meter_id not in discovered:
                    discovered.add(meter_id)
                    for topic, payload in discovery_messages(cfg, meter, result).items():
                        client.publish(topic, json.dumps(payload, ensure_ascii=False),
                                       qos=1, retain=True)
                client.publish(f"{base}/availability", "online", qos=1, retain=True)
                last = client.publish(
                    f"{base}/state", json.dumps(merge_state(result), ensure_ascii=False),
                    qos=1, retain=True)
                log.info("%s (%s): %d valori pubblicati", meter.name, meter_id,
                         sum(len(t.records) for t in result))
            if once:
                if last is not None:
                    last.wait_for_publish(10)
                if not ok:
                    raise SystemExit(1)
                return
            time.sleep(max(5.0, interval - (time.monotonic() - started)))
    finally:
        if client.is_connected():  # arresto pulito: il "last will" non scatterebbe
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
    return {"views": [{"title": "Calore", "path": "calore", "icon": "mdi:radiator",
                       "type": "sections", "max_columns": 3, "sections": sections}]}


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
