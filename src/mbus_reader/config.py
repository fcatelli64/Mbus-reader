"""Caricamento della configurazione YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SerialConfig:
    port: str = "/dev/ttyUSB0"
    baudrate: int = 2400
    timeout: float = 3.0
    retries: int = 3
    wakeup: float = 0.0  # secondi di risveglio (solo testina ottica)


@dataclass
class MeterConfig:
    name: str = "Contabilizzatore calore"
    primary_address: int = 254
    secondary_address: str | None = None


@dataclass
class MqttConfig:
    host: str = "homeassistant.local"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    base_topic: str = "mbus"
    discovery_prefix: str = "homeassistant"
    client_id: str = "mbus-reader"


@dataclass
class Config:
    serial: SerialConfig = field(default_factory=SerialConfig)
    meters: list[MeterConfig] = field(default_factory=lambda: [MeterConfig()])
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    poll_interval: int = 3600  # secondi tra un giro di letture e il successivo


def _build(cls, data: dict | None):
    data = data or {}
    unknown = set(data) - set(cls.__dataclass_fields__)
    if unknown:
        raise ValueError(f"chiavi sconosciute in '{cls.__name__}': {sorted(unknown)}")
    return cls(**data)


def load_config(path: str | Path | None) -> Config:
    raw: dict = {}
    if path:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    unknown = set(raw) - {"serial", "meters", "mqtt", "poll_interval"}
    if unknown:
        raise ValueError(f"sezioni sconosciute nella configurazione: {sorted(unknown)}")
    meters = [_build(MeterConfig, m) for m in raw.get("meters") or [{}]]
    for m in meters:
        if m.secondary_address is not None:
            m.secondary_address = str(m.secondary_address).rjust(8, "0")
    if len(meters) > 1:
        if any(not m.secondary_address for m in meters):
            raise ValueError("con più contatori ognuno deve avere 'secondary_address'")
        if len({m.name for m in meters}) != len(meters):
            raise ValueError("i contatori devono avere nomi diversi")
    cfg = Config(
        serial=_build(SerialConfig, raw.get("serial")),
        meters=meters,
        mqtt=_build(MqttConfig, raw.get("mqtt")),
        poll_interval=int(raw.get("poll_interval", 3600)),
    )
    # la password può arrivare dall'ambiente, per non scriverla nel file
    cfg.mqtt.password = os.environ.get("MQTT_PASSWORD", cfg.mqtt.password)
    return cfg
