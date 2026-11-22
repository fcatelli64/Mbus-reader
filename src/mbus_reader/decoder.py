"""Livello applicativo M-Bus (EN 13757-3): decodifica dei record DIF/VIF."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .frames import CI_RSP_VARIABLE, Frame


class DecodeError(ValueError):
    pass


MEDIA = {
    0x00: "Altro",
    0x02: "Elettricità",
    0x03: "Gas",
    0x04: "Calore (ritorno)",
    0x06: "Acqua calda",
    0x07: "Acqua",
    0x08: "Ripartitore di calore",
    0x0A: "Raffrescamento (ritorno)",
    0x0B: "Raffrescamento (mandata)",
    0x0C: "Calore (mandata)",
    0x0D: "Calore / Raffrescamento",
    0x16: "Acqua fredda",
}

FUNCTIONS = ("inst", "max", "min", "err")
TIME_UNITS = ("s", "min", "h", "d")

# quantity -> (nome, device_class HA, state_class HA per il valore corrente)
QUANTITIES: dict[str, tuple[str, str | None, str | None]] = {
    "energy": ("Energia", "energy", "total_increasing"),
    "cooling_energy": ("Energia raffrescamento", "energy", "total_increasing"),
    "volume": ("Volume", "volume", "total_increasing"),
    "mass": ("Massa", "weight", "total_increasing"),
    "power": ("Potenza", "power", "measurement"),
    "volume_flow": ("Portata", "volume_flow_rate", "measurement"),
    "mass_flow": ("Portata massica", None, "measurement"),
    "flow_temperature": ("Temperatura mandata", "temperature", "measurement"),
    "return_temperature": ("Temperatura ritorno", "temperature", "measurement"),
    "temperature_difference": ("Differenza temperatura", None, "measurement"),
    "external_temperature": ("Temperatura esterna", "temperature", "measurement"),
    "pressure": ("Pressione", "pressure", "measurement"),
    "on_time": ("Tempo di accensione", "duration", None),
    "operating_time": ("Tempo di funzionamento", "duration", None),
    "averaging_duration": ("Durata media", "duration", None),
    "actuality_duration": ("Durata attualità", "duration", None),
    "date": ("Data", "date", None),
    "datetime": ("Data e ora", "timestamp", None),
    "hca_units": ("Unità HCA", None, "total_increasing"),
    "fabrication_number": ("Numero di fabbricazione", None, None),
    "enhanced_id": ("Identificazione", None, None),
    "bus_address": ("Indirizzo bus", None, None),
    "access_number": ("Numero di accesso", None, None),
    "medium": ("Mezzo", None, None),
    "manufacturer": ("Costruttore", None, None),
    "parameter_set_id": ("Set parametri", None, None),
    "model_version": ("Modello / versione", None, None),
    "hardware_version": ("Versione hardware", None, None),
    "firmware_version": ("Versione firmware", None, None),
    "software_version": ("Versione software", None, None),
    "customer_location": ("Ubicazione cliente", None, None),
    "customer": ("Cliente", None, None),
    "error_flags": ("Flag di errore", None, None),
    "error_mask": ("Maschera errori", None, None),
    "digital_output": ("Uscita digitale", None, None),
    "digital_input": ("Ingresso digitale", None, None),
    "baudrate": ("Baudrate", None, None),
    "duration_since_readout": ("Tempo dall'ultima lettura", "duration", None),
    "dimensionless": ("Valore", None, None),
    "voltage": ("Tensione", "voltage", "measurement"),
    "current": ("Corrente", "current", "measurement"),
    "reset_counter": ("Contatore reset", None, None),
    "cumulation_counter": ("Contatore cumulativo", None, None),
    "battery_operating_time": ("Tempo di funzionamento batteria", "duration", None),
    "battery_change_date": ("Data cambio batteria", None, None),
    "battery_remaining": ("Vita residua batteria", "duration", None),
    "manufacturer_specific": ("Valore specifico costruttore", None, None),
    "unknown": ("Sconosciuto", None, None),
}

# quantità identificative: pubblicate come stringa
_ID_QUANTITIES = {
    "fabrication_number", "enhanced_id", "customer", "customer_location",
    "parameter_set_id", "model_version", "hardware_version", "firmware_version",
    "software_version",
}


@dataclass
class Record:
    key: str
    name: str
    quantity: str
    value: Any
    unit: str | None
    function: str = "inst"
    storage: int = 0
    tariff: int = 0
    subunit: int = 0
    header: str = ""  # DIF/VIF grezzi in esadecimale

    @property
    def device_class(self) -> str | None:
        return QUANTITIES.get(self.quantity, QUANTITIES["unknown"])[1]

    @property
    def state_class(self) -> str | None:
        if self.function != "inst" or self.storage or isinstance(self.value, (str, date)):
            return None
        return QUANTITIES.get(self.quantity, QUANTITIES["unknown"])[2]

    @property
    def json_value(self) -> Any:
        if isinstance(self.value, datetime):
            # l'orologio del contatore è in ora locale
            return self.value.astimezone().isoformat()
        if isinstance(self.value, date):
            return self.value.isoformat()
        return self.value


@dataclass
class Telegram:
    meter_id: str
    manufacturer: str
    version: int
    medium_code: int
    access_number: int
    status: int
    records: list[Record] = field(default_factory=list)
    manufacturer_data: bytes = b""
    more_follows: bool = False

    @property
    def medium(self) -> str:
        return MEDIA.get(self.medium_code, f"0x{self.medium_code:02X}")

    @property
    def battery_low(self) -> bool:
        return bool(self.status & 0x04)

    @property
    def permanent_error(self) -> bool:
        return bool(self.status & 0x08)

    @property
    def temporary_error(self) -> bool:
        return bool(self.status & 0x10)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {r.key: r.json_value for r in self.records}
        out.update(
            status=self.status,
            battery_low=self.battery_low,
            permanent_error=self.permanent_error,
            temporary_error=self.temporary_error,
            access_number=self.access_number,
        )
        return out


def decode_manufacturer(code: int) -> str:
    return "".join(chr(((code >> s) & 0x1F) + 64) for s in (10, 5, 0))


# --------------------------------------------------------------------- VIF

def _primary_vif(v: int) -> tuple[str, str | None, int, float]:
    """VIF primario (senza bit di estensione) -> (quantità, unità, esponente, fattore)."""
    n3, n2 = v & 0x07, v & 0x03
    if v <= 0x07:
        return "energy", "kWh", n3 - 6, 1
    if v <= 0x0F:
        return "energy", "MJ", n3 - 6, 1
    if v <= 0x17:
        return "volume", "m³", n3 - 6, 1
    if v <= 0x1F:
        return "mass", "kg", n3 - 3, 1
    if v <= 0x23:
        return "on_time", TIME_UNITS[n2], 0, 1
    if v <= 0x27:
        return "operating_time", TIME_UNITS[n2], 0, 1
    if v <= 0x2F:
        return "power", "W", n3 - 3, 1
    if v <= 0x37:
        return "power", "W", n3, 1 / 3600  # J/h
    if v <= 0x3F:
        return "volume_flow", "m³/h", n3 - 6, 1
    if v <= 0x47:
        return "volume_flow", "m³/h", n3 - 7, 60  # m³/min
    if v <= 0x4F:
        return "volume_flow", "m³/h", n3 - 9, 3600  # m³/s
    if v <= 0x57:
        return "mass_flow", "kg/h", n3 - 3, 1
    if v <= 0x5B:
        return "flow_temperature", "°C", n2 - 3, 1
    if v <= 0x5F:
        return "return_temperature", "°C", n2 - 3, 1
    if v <= 0x63:
        return "temperature_difference", "K", n2 - 3, 1
    if v <= 0x67:
        return "external_temperature", "°C", n2 - 3, 1
    if v <= 0x6B:
        return "pressure", "bar", n2 - 3, 1
    if v == 0x6C:
        return "date", None, 0, 1
    if v == 0x6D:
        return "datetime", None, 0, 1
    if v == 0x6E:
        return "hca_units", None, 0, 1
    if 0x70 <= v <= 0x73:
        return "averaging_duration", TIME_UNITS[n2], 0, 1
    if 0x74 <= v <= 0x77:
        return "actuality_duration", TIME_UNITS[n2], 0, 1
    if v == 0x78:
        return "fabrication_number", None, 0, 1
    if v == 0x79:
        return "enhanced_id", None, 0, 1
    if v == 0x7A:
        return "bus_address", None, 0, 1
    return "unknown", None, 0, 1


_FD_SIMPLE = {
    0x08: "access_number", 0x09: "medium", 0x0A: "manufacturer",
    0x0B: "parameter_set_id", 0x0C: "model_version", 0x0D: "hardware_version",
    0x0E: "firmware_version", 0x0F: "software_version", 0x10: "customer_location",
    0x11: "customer", 0x17: "error_flags", 0x18: "error_mask",
    0x1A: "digital_output", 0x1B: "digital_input", 0x1C: "baudrate",
    0x3A: "dimensionless", 0x60: "reset_counter", 0x61: "cumulation_counter",
    0x70: "battery_change_date",
}


def _fd_vif(v: int) -> tuple[str, str | None, int, float]:
    """Tabella di estensione 0xFD."""
    if v in _FD_SIMPLE:
        return _FD_SIMPLE[v], None, 0, 1
    if 0x30 <= v <= 0x33:
        return "duration_since_readout", TIME_UNITS[v & 3], 0, 1
    if 0x40 <= v <= 0x4F:
        return "voltage", "V", (v & 0x0F) - 9, 1
    if 0x50 <= v <= 0x5F:
        return "current", "A", (v & 0x0F) - 12, 1
    if 0x6C <= v <= 0x6F:
        return "battery_operating_time", ("h", "d", "mo", "y")[v & 3], 0, 1
    if 0x74 <= v <= 0x77:
        return "battery_remaining", ("h", "d", "mo", "y")[v & 3], 0, 1
    return "unknown", None, 0, 1


def _fb_vif(v: int) -> tuple[str, str | None, int, float]:
    """Tabella di estensione 0xFB."""
    n1 = v & 1
    if v <= 0x01:
        return "energy", "kWh", n1 + 2, 1  # 10^(n-1) MWh
    if 0x08 <= v <= 0x09:
        return "energy", "MJ", n1 + 2, 1  # 10^(n-1) GJ
    if 0x10 <= v <= 0x11:
        return "volume", "m³", n1 + 2, 1
    if 0x28 <= v <= 0x29:
        return "power", "W", n1 + 5, 1  # 10^(n-1) MW
    if 0x30 <= v <= 0x31:
        return "power", "W", n1 + 8, 1 / 3600  # 10^(n-1) GJ/h
    return "unknown", None, 0, 1


# ------------------------------------------------------------------- valori

def _bcd(data: bytes) -> int | None:
    digits = data[::-1].hex()
    negative = digits[0] == "f"
    if negative:
        digits = "0" + digits[1:]
    if not digits.isdigit():
        return None  # valore non valido / errore del contatore
    return -int(digits) if negative else int(digits)


def _year(lo: int, hi: int) -> int:
    y = ((lo & 0xE0) >> 5) | ((hi & 0xF0) >> 1)
    return 2000 + y if y < 81 else 1900 + y


def _date_g(d: bytes) -> date | None:
    try:
        return date(_year(d[0], d[1]), d[1] & 0x0F, d[0] & 0x1F)
    except ValueError:
        return None


def _datetime_f(d: bytes) -> datetime | None:
    if d[0] & 0x80:
        return None
    try:
        return datetime(_year(d[2], d[3]), d[3] & 0x0F, d[2] & 0x1F, d[1] & 0x1F, d[0] & 0x3F)
    except ValueError:
        return None


def _datetime_i(d: bytes) -> datetime | None:
    try:
        return datetime(
            _year(d[3], d[4]), d[4] & 0x0F, d[3] & 0x1F, d[2] & 0x1F, d[1] & 0x3F, d[0] & 0x3F
        )
    except ValueError:
        return None


_INT_LEN = {1: 1, 2: 2, 3: 3, 4: 4, 6: 6, 7: 8}
_BCD_LEN = {0x9: 1, 0xA: 2, 0xB: 3, 0xC: 4, 0xE: 6}


def _scale(raw: int | float, exp: int, factor: float) -> int | float:
    if exp == 0 and factor == 1:
        return raw
    digits = max(0, -exp) + (4 if factor != 1 else 0)
    value = round(raw * (10.0 ** exp) * factor, digits)
    return int(value) if digits == 0 else value


# ------------------------------------------------------------------ records

def decode_records(data: bytes) -> tuple[list[Record], bytes, bool]:
    """Decodifica i record; ritorna (record, dati_costruttore, altri_telegrammi)."""
    records: list[Record] = []
    used: dict[str, int] = {}
    i, n = 0, len(data)

    def take(count: int) -> bytes:
        nonlocal i
        if i + count > n:
            raise DecodeError("telegramma troncato")
        chunk = data[i : i + count]
        i += count
        return chunk

    while i < n:
        start = i
        dif = take(1)[0]
        if dif == 0x2F:  # riempitivo
            continue
        if dif in (0x0F, 0x1F):
            return records, bytes(data[i:]), dif == 0x1F
        if dif & 0x0F == 0x0F:  # altre funzioni speciali: ci fermiamo
            break

        storage = (dif >> 6) & 1
        tariff = subunit = 0
        ext, k = dif & 0x80, 0
        while ext:
            dife = take(1)[0]
            storage |= (dife & 0x0F) << (1 + 4 * k)
            tariff |= ((dife >> 4) & 0x03) << (2 * k)
            subunit |= ((dife >> 6) & 0x01) << k
            ext, k = dife & 0x80, k + 1

        vif = take(1)[0]
        code = vif & 0x7F
        text_unit = None
        if code == 0x7C:  # unità in testo libero
            text_unit = take(take(1)[0])[::-1].decode("latin-1").strip()
        vifes: list[int] = []
        ext = vif & 0x80
        while ext:
            v = take(1)[0]
            vifes.append(v & 0x7F)
            ext = v & 0x80

        if vif in (0xFD, 0xFB) and vifes:
            quantity, unit, exp, factor = (_fd_vif if vif == 0xFD else _fb_vif)(vifes.pop(0))
        elif code == 0x7C:
            quantity, unit, exp, factor = "dimensionless", text_unit, 0, 1
        elif code == 0x7F:
            quantity, unit, exp, factor = "manufacturer_specific", None, 0, 1
        else:
            quantity, unit, exp, factor = _primary_vif(code)

        extras: list[int] = []
        for v in vifes:
            if 0x70 <= v <= 0x77:
                exp += (v & 0x07) - 6
            elif v == 0x7D:
                exp += 3
            elif not 0x78 <= v <= 0x7B:
                extras.append(v)

        # --- dati
        df = dif & 0x0F
        value: Any
        if df == 0x0:
            value = None
        elif df in _INT_LEN:
            raw = take(_INT_LEN[df])
            if quantity == "date" and len(raw) == 2:
                value = _date_g(raw)
            elif quantity == "datetime" and len(raw) == 4:
                value = _datetime_f(raw)
            elif quantity == "datetime" and len(raw) == 6:
                value = _datetime_i(raw)
            elif quantity == "battery_change_date" and len(raw) == 2:
                value = _date_g(raw)
            else:
                value = _scale(int.from_bytes(raw, "little", signed=True), exp, factor)
        elif df == 0x5:
            value = _scale(struct.unpack("<f", take(4))[0], exp, factor)
        elif df in _BCD_LEN:
            bcd = _bcd(take(_BCD_LEN[df]))
            value = None if bcd is None else _scale(bcd, exp, factor)
        elif df == 0xD:
            lvar = take(1)[0]
            if lvar <= 0xBF:
                value = take(lvar)[::-1].decode("latin-1").strip()
            elif lvar <= 0xC9:
                bcd = _bcd(take(lvar - 0xC0))
                value = None if bcd is None else _scale(bcd, exp, factor)
            elif 0xD0 <= lvar <= 0xD9:
                bcd = _bcd(take(lvar - 0xD0))
                value = None if bcd is None else _scale(-bcd, exp, factor)
            elif 0xE0 <= lvar <= 0xEF:
                value = _scale(int.from_bytes(take(lvar - 0xE0), "little", signed=True), exp, factor)
            else:
                raise DecodeError(f"LVAR 0x{lvar:02X} non supportato")
        else:  # 0x8: selezione per lettura
            value = None

        if quantity in _ID_QUANTITIES and value is not None:
            value = str(value)

        function = FUNCTIONS[(dif >> 4) & 0x03]
        key = quantity
        name = QUANTITIES[quantity][0]
        if function != "inst":
            key += f"_{function}"
            name += {"max": " max", "min": " min", "err": " (errore)"}[function]
        for x in extras:
            key += f"_x{x:02x}"
            name += f" [VIFE {x:02X}]"
        if tariff:
            key += f"_t{tariff}"
            name += f" tariffa {tariff}"
        if subunit:
            key += f"_u{subunit}"
            name += f" unità {subunit}"
        if storage:
            key += f"_s{storage}"
            name += f" (storico {storage})"
        used[key] = used.get(key, 0) + 1
        if used[key] > 1:
            name += f" #{used[key]}"
            key += f"_n{used[key]}"

        records.append(
            Record(
                key=key, name=name, quantity=quantity, value=value, unit=unit,
                function=function, storage=storage, tariff=tariff, subunit=subunit,
                header=bytes(data[start : i]).hex(),
            )
        )
    return records, b"", False


def decode_telegram(frame: Frame) -> Telegram:
    """Decodifica una risposta RSP_UD con struttura dati variabile (CI 0x72)."""
    if frame.kind != "long":
        raise DecodeError("serve un frame lungo (RSP_UD)")
    if frame.ci != CI_RSP_VARIABLE:
        raise DecodeError(f"campo CI 0x{frame.ci:02X} non supportato (atteso 0x72)")
    d = frame.data
    if len(d) < 12:
        raise DecodeError("intestazione troppo corta")
    records, mfr, more = decode_records(d[12:])
    if d[7] == 0x0D:
        # Contatori caldo/freddo (Engelmann SensoStar): il registro "tariffa 1"
        # dell'energia è l'energia di raffrescamento.
        for r in records:
            if r.quantity == "energy" and r.tariff == 1:
                r.quantity = "cooling_energy"
                r.key = r.key.replace("energy_t1", "cooling_energy", 1)
                r.name = r.name.replace("Energia tariffa 1", "Energia raffrescamento", 1)
    return Telegram(
        meter_id=d[0:4][::-1].hex(),
        manufacturer=decode_manufacturer(int.from_bytes(d[4:6], "little")),
        version=d[6],
        medium_code=d[7],
        access_number=d[8],
        status=d[9],
        records=records,
        manufacturer_data=mfr,
        more_follows=more,
    )
