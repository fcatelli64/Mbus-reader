"""Interfaccia a riga di comando: mbus-reader scan | read | decode | run."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import __version__, frames
from .client import MBusClient, MBusError
from .config import load_config
from .decoder import DecodeError, Telegram, decode_telegram


def _print_telegram(t: Telegram) -> None:
    print(f"Contatore {t.meter_id}  costruttore {t.manufacturer}  versione {t.version}  "
          f"mezzo: {t.medium}")
    print(f"Accesso n. {t.access_number}  stato 0x{t.status:02X}"
          f"{'  BATTERIA SCARICA' if t.battery_low else ''}"
          f"{'  ERRORE PERMANENTE' if t.permanent_error else ''}"
          f"{'  ERRORE TEMPORANEO' if t.temporary_error else ''}")
    print(f"{'chiave':<34} {'valore':>22} {'unità':<6} DIF/VIF")
    for r in t.records:
        value = "-" if r.value is None else str(r.json_value)
        print(f"{r.key:<34} {value:>22} {r.unit or '':<6} {r.header}")
    if t.manufacturer_data:
        print(f"dati specifici del costruttore: {t.manufacturer_data.hex(' ')}")


def _output(telegrams: list[Telegram], args) -> None:
    if args.json:
        merged: dict = {"meter_id": telegrams[0].meter_id}
        for t in telegrams:
            merged.update(t.as_dict())
        print(json.dumps(merged, indent=2, ensure_ascii=False))
        return
    for t in telegrams:
        raw = getattr(t, "raw", None)
        if args.raw and raw:
            print(f"RAW: {raw.hex(' ')}")
        _print_telegram(t)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mbus-reader", description="Lettore M-Bus per Home Assistant")
    p.add_argument("-c", "--config", help="file di configurazione YAML")
    p.add_argument("-v", "--verbose", action="store_true", help="mostra i byte scambiati")
    p.add_argument("--baudrate", type=int, help="velocità seriale (sostituisce la configurazione)")
    p.add_argument("--wakeup", type=float, help="secondi di risveglio ottico (0 = nessuno)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="cerca i contatori sul bus (indirizzi primari 0-250)")

    r = sub.add_parser("read", help="legge il contatore e stampa i valori")
    r.add_argument("--raw", action="store_true", help="stampa anche il telegramma grezzo")
    r.add_argument("--json", action="store_true", help="stampa in formato JSON")

    d = sub.add_parser("decode", help="decodifica un telegramma in esadecimale")
    d.add_argument("hex", nargs="+")
    d.add_argument("--json", action="store_true")

    run_p = sub.add_parser("run", help="lettura periodica e pubblicazione MQTT")
    run_p.add_argument("--once", action="store_true", help="una sola lettura, poi esce")

    sim = sub.add_parser("simulate", help="pubblica dati finti su MQTT (senza contatori)")
    sim.add_argument("--once", action="store_true", help="una sola pubblicazione, poi esce")
    sim.add_argument("--interval", type=int, default=60, help="secondi tra gli invii (60)")

    sub.add_parser("dashboard", help="stampa la dashboard YAML per Home Assistant")
    sub.add_parser("probe", help="testina ottica: prova varie sequenze di risveglio")
    sub.add_parser("panel", help="stampa la configurazione del pannello per smartphone")

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        if args.command == "decode":
            data = bytes.fromhex("".join(args.hex))
            frame, _ = frames.next_frame(data)
            if frame is None:
                print("nessun frame M-Bus valido (checksum o lunghezza errati)", file=sys.stderr)
                return 1
            args.raw = False
            _output([decode_telegram(frame)], args)
            return 0

        cfg = load_config(args.config)
        if args.baudrate:
            cfg.serial.baudrate = args.baudrate
        if args.wakeup is not None:
            cfg.serial.wakeup = args.wakeup
        if args.command == "run":
            from .ha import run

            run(cfg, once=args.once)
            return 0
        if args.command == "simulate":
            from .ha import run, simulate_all

            # nome diverso dal servizio vero: due client con lo stesso id si
            # scollegano a vicenda in continuazione
            cfg.mqtt.client_id += "-sim"
            run(cfg, once=args.once, source=simulate_all, interval=args.interval)
            return 0
        if args.command == "panel":
            import yaml

            from .ha import panel_config

            print(yaml.safe_dump(panel_config(cfg), allow_unicode=True, sort_keys=False), end="")
            return 0
        if args.command == "dashboard":
            import yaml

            from .ha import dashboard

            print(yaml.safe_dump(dashboard(cfg), allow_unicode=True, sort_keys=False), end="")
            return 0

        with MBusClient(cfg.serial.port, cfg.serial.baudrate, cfg.serial.timeout,
                        cfg.serial.retries, wakeup=cfg.serial.wakeup) as bus:
            if args.command == "probe":
                print("Provo le sequenze di risveglio (circa un minuto). Tieni ferma la testina.")
                for label, data, frame in bus.probe_optical():
                    print(f"- {label}: ", end="")
                    if not data:
                        print("nessuna risposta")
                        continue
                    print(f"{len(data)} byte ricevuti\n  {data.hex(' ')}")
                    if frame is not None and frame.kind == "long":
                        print("\nRISPOSTA VALIDA con questa sequenza:\n")
                        args.raw, args.json = False, False
                        _output([decode_telegram(frame)], args)
                        return 0
                    if frame is not None:
                        print("  (il contatore ha risposto con una conferma)")
                print("\nNessuna sequenza ha ottenuto un telegramma completo.")
                return 1
            if args.command == "scan":
                print(f"Scansione su {cfg.serial.port} a {cfg.serial.baudrate} baud "
                      "(circa 2 minuti)...")
                found = list(bus.scan())
                for address in found:
                    print(f"  contatore trovato all'indirizzo primario {address}")
                if not found:
                    print("  nessun contatore trovato: controlla cablaggio e baudrate "
                          "(prova 300 o 9600)")
                return 0 if found else 1
            failed = 0
            for meter in cfg.meters:
                print(f"== {meter.name} ==")
                try:
                    _output(bus.read(meter.primary_address, meter.secondary_address), args)
                except (MBusError, DecodeError) as exc:
                    failed += 1
                    print(f"errore: {exc}", file=sys.stderr)
            if failed:
                return 1
        return 0
    except KeyboardInterrupt:
        print("\ninterrotto")
        return 130
    except (MBusError, DecodeError, OSError, ValueError) as exc:
        print(f"errore: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
