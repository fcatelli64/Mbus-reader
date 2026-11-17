"""Livello data-link M-Bus (EN 13757-2): costruzione e riconoscimento dei frame."""

from __future__ import annotations

from dataclasses import dataclass

ACK = 0xE5
START_SHORT = 0x10
START_LONG = 0x68
STOP = 0x16

ADDR_SECONDARY = 0xFD  # indirizzo di rete usato dopo la selezione secondaria
ADDR_BROADCAST_REPLY = 0xFE  # broadcast con risposta (ok con un solo contatore)

C_SND_NKE = 0x40
C_SND_UD = 0x53
C_REQ_UD2 = 0x5B
FCB = 0x20

CI_SELECT = 0x52
CI_RSP_VARIABLE = 0x72


@dataclass(frozen=True)
class Frame:
    kind: str  # "ack" | "short" | "long"
    raw: bytes
    control: int | None = None
    address: int | None = None
    ci: int | None = None
    data: bytes = b""


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def short_frame(control: int, address: int) -> bytes:
    return bytes([START_SHORT, control, address, (control + address) & 0xFF, STOP])


def long_frame(control: int, address: int, ci: int, data: bytes = b"") -> bytes:
    body = bytes([control, address, ci]) + data
    length = len(body)
    return bytes([START_LONG, length, length, START_LONG]) + body + bytes([checksum(body), STOP])


def snd_nke(address: int) -> bytes:
    return short_frame(C_SND_NKE, address)


def req_ud2(address: int, fcb: bool = False) -> bytes:
    return short_frame(C_REQ_UD2 | (FCB if fcb else 0), address)


def select_secondary(
    meter_id: str, manufacturer: int = 0xFFFF, version: int = 0xFF, medium: int = 0xFF
) -> bytes:
    """Frame di selezione per indirizzo secondario.

    ``meter_id`` sono le 8 cifre del numero di serie; ``F`` vale come jolly.
    """
    meter_id = str(meter_id).strip().upper().rjust(8, "0")
    if len(meter_id) != 8 or any(c not in "0123456789F" for c in meter_id):
        raise ValueError(f"indirizzo secondario non valido: {meter_id!r}")
    data = (
        bytes.fromhex(meter_id)[::-1]
        + manufacturer.to_bytes(2, "little")
        + bytes([version, medium])
    )
    return long_frame(C_SND_UD, ADDR_SECONDARY, CI_SELECT, data)


def next_frame(buf: bytes) -> tuple[Frame | None, int]:
    """Cerca il primo frame completo in ``buf``.

    Restituisce ``(frame, byte_consumati)``. Se il buffer contiene solo l'inizio
    di un frame, restituisce ``(None, n)`` dove ``n`` sono i byte di rumore che
    lo precedono e che si possono scartare.
    """
    i = 0
    n = len(buf)
    while i < n:
        b = buf[i]
        if b == ACK:
            return Frame("ack", buf[i : i + 1]), i + 1
        if b == START_SHORT:
            if n - i < 5:
                return None, i
            if buf[i + 4] == STOP and (buf[i + 1] + buf[i + 2]) & 0xFF == buf[i + 3]:
                raw = bytes(buf[i : i + 5])
                return Frame("short", raw, control=raw[1], address=raw[2]), i + 5
        elif b == START_LONG:
            if n - i < 4:
                return None, i
            length = buf[i + 1]
            if buf[i + 2] == length and buf[i + 3] == START_LONG and length >= 3:
                total = length + 6
                if n - i < total:
                    return None, i
                body = bytes(buf[i + 4 : i + 4 + length])
                if buf[i + total - 1] == STOP and checksum(body) == buf[i + total - 2]:
                    raw = bytes(buf[i : i + total])
                    return (
                        Frame("long", raw, control=body[0], address=body[1], ci=body[2], data=body[3:]),
                        i + total,
                    )
        i += 1
    return None, n
