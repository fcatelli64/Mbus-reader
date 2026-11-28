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

    opt = sub.add_parser(
        "optical", help="testina ottica: legge il contatore su cui è appoggiata e lo pubblica")
    opt.add_argument("--seconds", type=int, default=120, help="durata massima della ricerca (120)")
    opt.add_argument("--no-publish", action="store_true", help="mostra i valori senza pubblicarli")

    sim = sub.add_parser("simulate", help="pubblica dati finti su MQTT (senza contatori)")
    sim.add_argument("--once", action="store_true", help="una sola pubblicazione, poi esce")
    sim.add_argument("--interval", type=int, default=60, help="secondi tra gli invii (60)")

    sub.add_parser("dashboard", help="stampa la dashboard YAML per Home Assistant")
    sub.add_parser("probe", help="testina ottica: prova varie sequenze di risveglio")
    aim = sub.add_parser("aim", help="testina ottica: richieste continue per trovare la posizione")
    aim.add_argument("--seconds", type=int, default=120, help="durata della prova (120)")
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
        if args.command == "optical":
            from .config import MeterConfig

            print("Premi il tasto del contatore e appoggia la testina (LED in verticale). "
                  "Ctrl+C per fermare.")
            telegram = None
            with MBusClient(cfg.serial.port, cfg.serial.baudrate, cfg.serial.timeout,
                            cfg.serial.retries, wakeup=cfg.serial.wakeup) as bus:
                for n, data, frame in bus.aim(args.seconds):
                    if frame is not None and frame.kind == "long":
                        telegram = decode_telegram(frame)
                        telegram.raw = frame.raw  # type: ignore[attr-defined]
                        break
                    print(f"{n:3d}: " + (f"{len(data)} byte non validi" if data else "nessuna risposta"))
            if telegram is None:
                print("Nessuna risposta valida dal contatore.", file=sys.stderr)
                return 1
            # il contatore si riconosce dal numero di serie, non dalla posizione
            meter = next((m for m in cfg.meters if m.secondary_address == telegram.meter_id), None)
            if meter is None and len(cfg.meters) == 1 and not cfg.meters[0].secondary_address:
                meter = cfg.meters[0]
            if meter is None:
                meter = MeterConfig(name=f"Contatore {telegram.meter_id}")
                print(f"ATTENZIONE: il numero di serie {telegram.meter_id} non è nella "
                      "configurazione; uso un nome provvisorio.", file=sys.stderr)
            print(f"\n== {meter.name} ==")
            args.raw, args.json = True, False
            _output([telegram], args)
            if not args.no_publish:
                from .ha import run

                # nome diverso dal servizio continuo: due client con lo stesso id
                # si scollegano a vicenda e la pubblicazione può andare persa
                cfg.mqtt.client_id += "-optical"
                run(cfg, once=True, source=lambda _cfg, _meters=None: iter([(meter, [telegram])]))
            return 0
        if args.command == "run":
            from .ha import run

            if args.once:
                cfg.mqtt.client_id += "-once"
            run(cfg, once=args.once)
            return 0
        if args.command == "simulate":
            from .ha import run, simulate_all

            # nome diverso dal servizio vero: due client con lo stesso id si
            # scollegano a vicenda in continuazione
            cfg.mqtt.client_id += "-sim"
            run(cfg, once=args.once, source=simulate_all, interval=args.interval, simulated=True)
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
            if args.command == "aim":
                print(f"Richieste continue per {args.seconds} s a {cfg.serial.baudrate} baud"
                      f"{', con risveglio' if cfg.serial.wakeup > 0 else ''}. "
                      "Muovi lentamente la testina; Ctrl+C per fermare.")
                for n, data, frame in bus.aim(args.seconds):
                    if not data:
                        print(f"{n:3d}: nessuna risposta")
                    elif frame is not None and frame.kind == "long":
                        print(f"{n:3d}: RISPOSTA VALIDA ({len(data)} byte)\nRAW: {frame.raw.hex(' ')}\n")
                        args.raw, args.json = False, False
                        _output([decode_telegram(frame)], args)
                        return 0
                    else:
                        print(f"{n:3d}: {len(data)} byte ricevuti ma non validi\n     {data.hex(' ')}")
                return 1
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
