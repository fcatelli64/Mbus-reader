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


@dataclass
class MeterConfig:
    name: str = "Contabilizzatore calore"
    primary_address: int = 254
    secondary_address: str | None = None
    poll_interval: int = 900  # secondi


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
    meter: MeterConfig = field(default_factory=MeterConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)


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
    unknown = set(raw) - {"serial", "meter", "mqtt"}
    if unknown:
        raise ValueError(f"sezioni sconosciute nella configurazione: {sorted(unknown)}")
    cfg = Config(
        serial=_build(SerialConfig, raw.get("serial")),
        meter=_build(MeterConfig, raw.get("meter")),
        mqtt=_build(MqttConfig, raw.get("mqtt")),
    )
    if cfg.meter.secondary_address is not None:
        cfg.meter.secondary_address = str(cfg.meter.secondary_address)
    # la password può arrivare dall'ambiente, per non scriverla nel file
    cfg.mqtt.password = os.environ.get("MQTT_PASSWORD", cfg.mqtt.password)
    return cfg
