from datetime import date, datetime

import pytest

from mbus_reader import frames
from mbus_reader.client import MBusClient, MBusTimeout
from mbus_reader.config import Config, MeterConfig, load_config
from mbus_reader.decoder import decode_records, decode_telegram
from mbus_reader.ha import dashboard, discovery_messages, merge_state, simulate_all

# Esempio ufficiale della documentazione M-Bus (cap. 6.6)
DOC_EXAMPLE = bytes.fromhex(
    "681F1F6808027278563412244001075500000003131531 00DA023B13018B60043718021816"
)


def heat_meter_frame(more=False):
    """Telegramma sintetico in stile contatore di calore Engelmann."""
    header = bytes.fromhex("14293861") + bytes.fromhex("C514") + bytes([0x00, 0x04, 0x2A, 0x04, 0, 0])
    recs = bytes.fromhex(
        "0C05 45230100"      # energia 12345 * 100 Wh = 1234.5 kWh
        "0C13 78563412"      # volume 12345.678 m3
        "0B3B 250100"        # portata 0.125 m3/h
        "0B2B 004500"        # potenza 4500 W
        "0A5A 5306"          # mandata 65.3 C
        "0A5E 1204"          # ritorno 41.2 C
        "0B61 102400"        # delta T 24.10 K
        "0C78 14293861"      # numero di fabbricazione
        "426C DF2C"          # data storico 1: 31.12.2022
        "4C05 00900000"      # energia storico 1: 900.0 kWh
        "046D 1E0F513B"      # data/ora 17.11.2026 15:30
        "02FD17 0000"        # flag errore
        "8C4013 21430000"    # volume ingresso impulsi 1: 4.321 m3
        "2F2F"
    )
    tail = bytes([0x1F]) if more else b""
    return frames.long_frame(0x08, 0x00, 0x72, header + recs + tail)


def test_frame_builders():
    assert frames.snd_nke(254) == bytes.fromhex("1040FE3E16")
    assert frames.req_ud2(254) == bytes.fromhex("105BFE5916")
    assert frames.req_ud2(1, fcb=True) == bytes.fromhex("107B017C16")
    sel = frames.select_secondary("61382914")
    assert sel == bytes.fromhex("680B0B6853FD5214293861FFFFFFFF") + sel[-2:]
    assert frames.next_frame(sel)[0].ci == 0x52


def test_next_frame_noise_and_partial():
    frame, used = frames.next_frame(b"\x00\xff" + DOC_EXAMPLE + b"\xe5")
    assert frame.kind == "long" and used == 2 + len(DOC_EXAMPLE)
    assert frames.next_frame(DOC_EXAMPLE[:10]) == (None, 0)
    bad = bytearray(DOC_EXAMPLE)
    bad[-2] ^= 0xFF
    assert frames.next_frame(bytes(bad))[0] is None


def test_doc_example():
    t = decode_telegram(frames.next_frame(DOC_EXAMPLE)[0])
    assert (t.meter_id, t.manufacturer, t.version, t.medium_code) == ("12345678", "PAD", 1, 7)
    vol, flow, energy = t.records
    assert (vol.key, vol.value, vol.unit) == ("volume", 12.565, "m³")
    assert (flow.key, flow.value, flow.storage) == ("volume_flow_max_s5", 0.113, 5)
    assert (energy.key, energy.value, energy.unit) == ("energy_t2_u1", 218.37, "kWh")


def test_heat_meter():
    t = decode_telegram(frames.next_frame(heat_meter_frame())[0])
    s = t.as_dict()
    assert t.meter_id == "61382914" and t.manufacturer == "EFE"
    assert s["energy"] == 1234.5
    assert s["volume"] == 12345.678
    assert s["volume_flow"] == 0.125
    assert s["power"] == 4500
    assert s["flow_temperature"] == 65.3
    assert s["return_temperature"] == 41.2
    assert s["temperature_difference"] == 24.1
    assert s["fabrication_number"] == "61382914"
    assert s["date_s1"] == "2022-12-31"
    assert s["energy_s1"] == 900.0
    assert s["datetime"].startswith("2026-11-17T15:30:00")
    assert s["error_flags"] == 0
    assert s["volume_u1"] == 4.321
    assert s["battery_low"] is True and s["permanent_error"] is False


def test_value_types():
    recs, mfr, more = decode_records(bytes.fromhex(
        "02 5A FFFF"            # int16 negativo: -0.1 C
        "0A 5A FFFF"            # BCD non valido -> None
        "05 2E 0000C03F"        # float 1.5 kW -> 1500 W
        "0D 78 03 434241"       # stringa "ABC"
        "04 86 3B 10270000"     # energia 10000 kWh con VIFE 0x3B
        "0F 0102"
    ))
    assert [r.value for r in recs] == [-0.1, None, 1500, "ABC", 10000]
    assert recs[4].key == "energy_x3b"
    assert mfr == b"\x01\x02" and more is False


def test_against_pymeterbus():
    meterbus = pytest.importorskip("meterbus")
    import json

    ref = json.loads(meterbus.load(heat_meter_frame()).to_JSON())
    ours = decode_telegram(frames.next_frame(heat_meter_frame())[0])
    ref_records = list(ref["body"]["records"])
    assert len(ref_records) == len(ours.records)
    for theirs, mine in zip(ref_records, ours.records):
        assert theirs["storage_number"] == mine.storage, mine.key
        if isinstance(mine.value, (int, float)):
            factor = 1000 if mine.unit == "kWh" else 1  # la libreria riporta i Wh
            assert float(theirs["value"]) == pytest.approx(mine.value * factor), mine.key
        elif mine.quantity in ("date", "datetime"):
            assert mine.value.isoformat().startswith(theirs["value"]), mine.key


class FakeSerial:
    """Simula adattatore + contatore; con echo=True rimanda indietro il TX."""

    def __init__(self, replies, echo=False):
        self.replies, self.echo = replies, echo
        self.rx = b""
        self.sent = []

    def reset_input_buffer(self):
        self.rx = b""

    def write(self, data):
        self.sent.append(bytes(data))
        self.rx = (bytes(data) if self.echo else b"") + self.replies.get(bytes(data), b"")

    def flush(self):
        pass

    def read(self, n):
        out, self.rx = self.rx[:n], self.rx[n:]
        return out

    def close(self):
        pass


@pytest.mark.parametrize("echo", [False, True])
def test_client_primary(echo):
    fake = FakeSerial({
        frames.snd_nke(254): b"\xe5",
        frames.req_ud2(254, True): heat_meter_frame(more=True),
        frames.req_ud2(254, False): DOC_EXAMPLE,
    }, echo=echo)
    with MBusClient("x", timeout=0.3, retries=1, serial_factory=lambda: fake) as bus:
        telegrams = bus.read(254)
    assert [t.meter_id for t in telegrams] == ["61382914", "12345678"]


def test_client_secondary_and_timeout():
    fake = FakeSerial({
        frames.select_secondary("61382914"): b"\xe5",
        frames.req_ud2(253, True): heat_meter_frame(),
    }, echo=True)
    with MBusClient("x", timeout=0.2, retries=1, serial_factory=lambda: fake) as bus:
        assert bus.read(secondary="61382914")[0].meter_id == "61382914"
        with pytest.raises(MBusTimeout):
            bus.read(5)


def test_discovery():
    t = decode_telegram(frames.next_frame(heat_meter_frame())[0])
    msgs = discovery_messages(Config(), MeterConfig(name="Calore 1"), [t])
    energy = msgs["homeassistant/sensor/mbus_61382914/energy/config"]
    assert energy["device_class"] == "energy"
    assert energy["state_class"] == "total_increasing"
    assert energy["unit_of_measurement"] == "kWh"
    assert energy["state_topic"] == "mbus/61382914/state"
    assert energy["device"]["name"] == "Calore 1"
    assert msgs["homeassistant/sensor/mbus_61382914/volume_flow/config"][
        "suggested_display_precision"] == 3
    assert [a["topic"] for a in energy["availability"]] == [
        "mbus/bridge/availability", "mbus/61382914/availability"]
    hist = msgs["homeassistant/sensor/mbus_61382914/energy_s1/config"]
    assert "state_class" not in hist and hist["entity_category"] == "diagnostic"
    assert msgs["homeassistant/sensor/mbus_61382914/date_s1/config"]["device_class"] == "date"
    assert "device_class" not in msgs["homeassistant/sensor/mbus_61382914/temperature_difference/config"]
    assert "homeassistant/binary_sensor/mbus_61382914/battery_low/config" in msgs
    assert set(merge_state([t])) >= {m["unique_id"].removeprefix("mbus_61382914_") for m in msgs.values()}


def test_multi_meter_config_simulation_dashboard(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(
        "poll_interval: 600\n"
        "meters:\n"
        "  - {name: Calore Interno 1, secondary_address: 61382914}\n"
        "  - {name: Calore Unità 2, secondary_address: '61382915'}\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.poll_interval == 600
    assert [m.secondary_address for m in cfg.meters] == ["61382914", "61382915"]

    results = list(simulate_all(cfg))
    assert [t[0].meter_id for _, t in results] == ["61382914", "61382915"]
    state = merge_state(results[0][1])
    assert state["energy"] is None and 50 < state["flow_temperature"] < 70
    # la simulazione crea le stesse entità (stessi unique_id e classi) dei dati veri
    sim = discovery_messages(cfg, cfg.meters[0], results[0][1])
    real = discovery_messages(
        cfg, cfg.meters[0], [decode_telegram(frames.next_frame(heat_meter_frame())[0])])
    for topic, payload in sim.items():
        assert payload == real[topic], topic

    yaml_text = str(dashboard(cfg))
    assert "sensor.calore_interno_1_energia" in yaml_text
    assert "sensor.calore_unita_2_temperatura_mandata" in yaml_text

    path.write_text("meters:\n  - {name: A}\n  - {name: B}\n")
    with pytest.raises(ValueError):
        load_config(path)


def test_optical_wakeup():
    fake = FakeSerial({
        frames.snd_nke(254): b"\xe5",
        frames.req_ud2(254, True): heat_meter_frame(),
    }, echo=True)
    with MBusClient("x", timeout=0.3, retries=1, serial_factory=lambda: fake, wakeup=0.5) as bus:
        assert bus.read(254)[0].meter_id == "61382914"
    assert fake.sent[0] == b"\x55" * 120  # 2400 baud / 10 bit * 0,5 s
    assert fake.parity == "E"  # dopo il risveglio si torna alla parità pari
    assert fake.sent[1] == frames.req_ud2(254, True)  # niente SND_NKE dopo il risveglio


def test_probe_optical_finds_reply():
    fake = FakeSerial({frames.req_ud2(254): heat_meter_frame()}, echo=True)
    fake.parity = "E"
    with MBusClient("x", serial_factory=lambda: fake) as bus:
        label, data, frame = next(bus.probe_optical(listen=0.05))
    assert "8N1" in label and frame.kind == "long" and data == heat_meter_frame()
