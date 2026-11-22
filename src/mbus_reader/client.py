"""Master M-Bus su porta seriale (adattatore USB/M-Bus)."""

from __future__ import annotations

import logging
import time

from . import frames
from .decoder import Telegram, decode_telegram
from .frames import Frame

log = logging.getLogger(__name__)


class MBusError(Exception):
    pass


class MBusTimeout(MBusError):
    pass


class MBusClient:
    """Uso: ``with MBusClient("/dev/ttyUSB0") as bus: bus.read(254)``."""

    def __init__(self, port: str, baudrate: int = 2400, timeout: float = 3.0, retries: int = 3,
                 serial_factory=None, wakeup: float = 0.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.retries = retries
        self.wakeup = wakeup
        self._factory = serial_factory
        self._ser = None

    # -- porta ---------------------------------------------------------------
    def open(self) -> None:
        if self._factory is not None:
            self._ser = self._factory()
        else:
            import serial

            self._ser = serial.Serial(
                self.port, self.baudrate, bytesize=8, parity=serial.PARITY_EVEN,
                stopbits=1, timeout=0.1,
            )
        time.sleep(0.3)  # lascia stabilizzare la tensione del bus
        self._ser.reset_input_buffer()

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def __enter__(self) -> "MBusClient":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- scambio -------------------------------------------------------------
    def _exchange(self, request: bytes, timeout: float | None = None) -> Frame:
        """Invia ``request`` e ritorna il primo frame di risposta.

        Molti adattatori USB/M-Bus rimandano indietro l'eco di ciò che si
        trasmette: un frame identico alla richiesta viene scartato.
        """
        ser = self._ser
        if ser is None:
            raise MBusError("porta non aperta")
        ser.reset_input_buffer()
        log.debug("TX %s", request.hex(" "))
        ser.write(request)
        ser.flush()
        deadline = time.monotonic() + (timeout or self.timeout)
        buf = bytearray()
        echo_pending = True
        while time.monotonic() < deadline:
            chunk = ser.read(256)
            if not chunk:
                continue
            log.debug("RX %s", bytes(chunk).hex(" "))
            buf += chunk
            while True:
                frame, used = frames.next_frame(bytes(buf))
                del buf[:used]
                if frame is None:
                    break
                if echo_pending and frame.raw == request:
                    echo_pending = False
                    continue
                return frame
        raise MBusTimeout("nessuna risposta dal contatore")

    def _retry(self, request: bytes, timeout: float | None = None) -> Frame:
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                return self._exchange(request, timeout)
            except MBusTimeout as exc:
                last = exc
                log.debug("tentativo %d fallito", attempt + 1)
                time.sleep(0.5)
        raise last  # type: ignore[misc]

    def wake(self) -> None:
        """Sveglia l'interfaccia ottica del contatore con una raffica di 0x55.

        Serve solo con una testina ottica (``serial.wakeup`` = durata in secondi):
        sul bus cablato il contatore è sempre in ascolto.
        """
        if self.wakeup <= 0 or self._ser is None:
            return
        count = max(1, int(self.baudrate / 11 * self.wakeup))  # 11 bit per byte in 8E1
        log.debug("TX risveglio: %d x 0x55", count)
        self._ser.write(b"\x55" * count)
        self._ser.flush()
        time.sleep(0.15)
        self._ser.reset_input_buffer()

    # -- operazioni ----------------------------------------------------------
    def ping(self, address: int, timeout: float | None = None) -> bool:
        """SND_NKE: vero se il contatore risponde con ACK."""
        try:
            return self._exchange(frames.snd_nke(address), timeout).kind == "ack"
        except MBusTimeout:
            return False

    def select(self, secondary: str) -> None:
        """Seleziona un contatore tramite indirizzo secondario (numero di serie)."""
        self.ping(frames.ADDR_SECONDARY, timeout=0.5)  # deseleziona eventuali altri
        reply = self._retry(frames.select_secondary(secondary))
        if reply.kind != "ack":
            raise MBusError(f"selezione di {secondary} non confermata")

    def read(self, primary: int | None = frames.ADDR_BROADCAST_REPLY,
             secondary: str | None = None, max_telegrams: int = 8) -> list[Telegram]:
        """Legge tutti i telegrammi del contatore (REQ_UD2)."""
        self.wake()
        if secondary:
            self.select(secondary)
            address = frames.ADDR_SECONDARY
        else:
            address = frames.ADDR_BROADCAST_REPLY if primary is None else primary
            # normalizza: riporta il contatore al primo telegramma
            self.ping(address, timeout=1.0)

        telegrams: list[Telegram] = []
        fcb = True
        while len(telegrams) < max_telegrams:
            reply = self._retry(frames.req_ud2(address, fcb))
            if reply.kind != "long":
                raise MBusError(f"risposta inattesa: {reply.raw.hex(' ')}")
            telegram = decode_telegram(reply)
            telegram.raw = reply.raw  # type: ignore[attr-defined]
            telegrams.append(telegram)
            if not telegram.more_follows:
                break
            fcb = not fcb
        return telegrams

    def scan(self, addresses=range(0, 251), timeout: float = 0.4):
        """Scansione degli indirizzi primari; genera quelli che rispondono."""
        for address in addresses:
            if self.ping(address, timeout=timeout):
                yield address
