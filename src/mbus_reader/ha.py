"""Pubblicazione su MQTT con auto-discovery di Home Assistant."""

from __future__ import annotations

import json
import logging
import threading
import time

from . import __version__
from .client import MBusClient
from .config import Config
from .decoder import Telegram

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

_BINARY = (
    ("battery_low", "Batteria scarica", "battery"),
    ("permanent_error", "Errore permanente", "problem"),
    ("temporary_error", "Errore temporaneo", "problem"),
)


def merge_state(telegrams: list[Telegram]) -> dict:
    state: dict = {}
    for t in telegrams:
        state.update(t.as_dict())
    return state


def discovery_messages(cfg: Config, telegrams: list[Telegram]) -> dict[str, dict]:
    """Ritorna ``{topic: payload}`` di configurazione per ogni entità."""
    first = telegrams[0]
    uid = f"mbus_{first.meter_id}"
    base = f"{cfg.mqtt.base_topic}/{first.meter_id}"
    device = {
        "identifiers": [uid],
        "name": cfg.meter.name,
        "manufacturer": first.manufacturer,
        "model": f"{first.medium} (v{first.version})",
        "serial_number": first.meter_id,
        "sw_version": f"mbus-reader {__version__}",
    }
    common = {
        "state_topic": f"{base}/state",
        "availability_topic": f"{base}/availability",
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


def read_meter(cfg: Config) -> list[Telegram]:
    with MBusClient(cfg.serial.port, cfg.serial.baudrate, cfg.serial.timeout,
                    cfg.serial.retries) as bus:
        return bus.read(cfg.meter.primary_address, cfg.meter.secondary_address)


def run(cfg: Config, once: bool = False) -> None:
    """Ciclo principale: lettura periodica e pubblicazione su MQTT."""
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg.mqtt.client_id)
    if cfg.mqtt.username:
        client.username_pw_set(cfg.mqtt.username, cfg.mqtt.password)

    ha_status = f"{cfg.mqtt.discovery_prefix}/status"
    resend_discovery = threading.Event()
    resend_discovery.set()
    availability_topic: str | None = None
    if cfg.meter.secondary_address:
        # id noto in anticipo: possiamo registrare il "last will"
        availability_topic = (
            f"{cfg.mqtt.base_topic}/{cfg.meter.secondary_address.rjust(8, '0')}/availability"
        )
        client.will_set(availability_topic, "offline", qos=1, retain=True)

    def on_connect(c, userdata, flags, reason_code, properties):
        log.info("MQTT connesso a %s:%s (%s)", cfg.mqtt.host, cfg.mqtt.port, reason_code)
        c.subscribe(ha_status)
        resend_discovery.set()

    def on_message(c, userdata, msg):
        if msg.topic == ha_status and msg.payload == b"online":
            resend_discovery.set()  # Home Assistant è ripartito

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(cfg.mqtt.host, cfg.mqtt.port, keepalive=60)
    client.loop_start()

    failures = 0
    try:
        while True:
            started = time.monotonic()
            try:
                telegrams = read_meter(cfg)
                failures = 0
                base = f"{cfg.mqtt.base_topic}/{telegrams[0].meter_id}"
                availability_topic = f"{base}/availability"
                if resend_discovery.is_set():
                    resend_discovery.clear()
                    for topic, payload in discovery_messages(cfg, telegrams).items():
                        client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=True)
                client.publish(availability_topic, "online", qos=1, retain=True)
                info = client.publish(
                    f"{base}/state", json.dumps(merge_state(telegrams), ensure_ascii=False),
                    qos=1, retain=True,
                )
                log.info("lettura ok: %d valori pubblicati",
                         sum(len(t.records) for t in telegrams))
                if once:
                    info.wait_for_publish(10)
                    return
            except Exception as exc:  # un servizio non deve morire per una lettura
                failures += 1
                log.warning("lettura fallita (%d): %s", failures, exc)
                if failures == 3 and availability_topic:
                    client.publish(availability_topic, "offline", qos=1, retain=True)
                if once:
                    raise SystemExit(1)
            time.sleep(max(5.0, cfg.meter.poll_interval - (time.monotonic() - started)))
    finally:
        client.loop_stop()
        client.disconnect()
