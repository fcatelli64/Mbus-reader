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
            if attempt:
                self.wake()  # l'interfaccia ottica si riaddormenta dopo pochi secondi
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
        # Raffica in 8N1 (segnale perfettamente alternato), poi si torna a 8E1 e
        # si invia la richiesta entro pochi millisecondi, come sugli altri
        # contatori di calore con interfaccia ottica.
        count = max(1, int(self.baudrate / 10 * self.wakeup))  # 10 bit per byte in 8N1
        log.debug("TX risveglio: %d x 0x55", count)
        ser = self._ser
        try:
            ser.parity = "N"
        except Exception:  # porta che non permette il cambio al volo: resta in 8E1
            log.debug("cambio di parità non supportato, risveglio in 8E1")
        ser.write(b"\x55" * count)
        ser.flush()
        try:
            ser.parity = "E"
        except Exception as exc:
            try:
                self.close()
                self.open()
            except Exception:
                raise MBusError(f"la porta {self.port} non accetta il ritorno a 8E1: {exc}") from exc
            return
        time.sleep(0.05)
        ser.reset_input_buffer()

    # -- operazioni ----------------------------------------------------------
    def ping(self, address: int, timeout: float | None = None) -> bool:
        """SND_NKE: vero se il contatore risponde con ACK."""
        try:
            return self._exchange(frames.snd_nke(address), timeout).kind == "ack"
        except MBusTimeout:
            return False

    def select(self, secondary: str) -> None:
        """Seleziona un contatore tramite indirizzo secondario (numero di serie)."""
        # Niente SND_NKE prima della selezione: sul SensoStar 2 consuma parte delle
        # letture giornaliere disponibili, e i contatori che non corrispondono
        # all'indirizzo richiesto si deselezionano comunque da soli.
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
            if self.wakeup <= 0:
                # normalizza: riporta il contatore al primo telegramma
                self.ping(address, timeout=1.0)
            # con la testina ottica si va dritti alla richiesta: la finestra di
            # ascolto dopo il risveglio è breve

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

    def probe_optical(self, listen: float = 2.5):
        """Prova varie sequenze di risveglio per l'interfaccia ottica.

        Genera ``(descrizione, byte_ricevuti, frame)`` per ogni variante; ci si
        può fermare alla prima che ottiene un frame valido.
        """
        ser = self._ser
        if ser is None:
            raise MBusError("porta non aperta")
        requests = (
            ("REQ_UD2", frames.req_ud2(frames.ADDR_BROADCAST_REPLY)),
            ("SND_NKE", frames.snd_nke(frames.ADDR_BROADCAST_REPLY)),
        )
        # Prima le richieste dirette: sul SensoStar 2 l'interfaccia si attiva con
        # il tasto e resta aperta 60 secondi, quindi vanno provate subito.
        variants = [(None, 0.0, name, req) for name, req in requests]
        variants += [(mode, pause, name, req)
                     for mode in ("N", "E") for pause in (0.03, 0.1, 0.35)
                     for name, req in requests]
        for mode, pause, name, req in variants:
            if mode:
                count = int(self.baudrate / (10 if mode == "N" else 11) * 2.2)
                ser.parity = mode
                ser.write(b"\x55" * count)
                ser.flush()
                ser.parity = "E"
                time.sleep(pause)
                label = f"risveglio 8{mode}1 2,2 s, pausa {int(pause * 1000)} ms, {name}"
            else:
                label = f"senza risveglio, {name}"
            ser.reset_input_buffer()
            ser.write(req)
            ser.flush()
            buf = bytearray()
            deadline = time.monotonic() + listen
            while time.monotonic() < deadline:
                buf += ser.read(256)
            data = bytes(buf)
            if data.startswith(req):  # eco della testina
                data = data[len(req):]
            frame, _ = frames.next_frame(data)
            if frame is not None and frame.kind == "ack" and name == "SND_NKE":
                # il contatore è sveglio: chiedi subito i dati
                ser.reset_input_buffer()
                ser.write(frames.req_ud2(frames.ADDR_BROADCAST_REPLY, True))
                ser.flush()
                buf = bytearray()
                deadline = time.monotonic() + listen
                while time.monotonic() < deadline:
                    buf += ser.read(256)
                data += bytes(buf)
                long_frame, _ = frames.next_frame(bytes(buf))
                frame = long_frame or frame
            yield label, data, frame
            time.sleep(1.0)

    def scan(self, addresses=range(0, 251), timeout: float = 0.4):
        """Scansione degli indirizzi primari; genera quelli che rispondono."""
        for address in addresses:
            if self.ping(address, timeout=timeout):
                yield address
