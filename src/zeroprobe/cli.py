from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from .i2c import I2cScanner, SimulatedI2cScanner, format_i2c_scan
from .profile import CARDPUTER_ZERO, CaptureRequest
from .runtime import select_backend
from .uart import (
    STANDARD_BAUDS,
    SimulatedUartMonitor,
    SimulatedUartTerminal,
    UartMonitor,
    UartTerminal,
    format_uart_capture,
    parse_hex_bytes,
)
from .ui import AppController, run_gui
from .vcd import encode_vcd
from .web import DEFAULT_SETTINGS_PATH, list_ipv4_interfaces, load_web_settings, save_web_settings


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="zeroprobe", description="Safe CardputerZero interface explorer")
    sub = root.add_subparsers(dest="command", required=True)
    gui = sub.add_parser("gui", help="start the 320x170 graphical application")
    gui.add_argument("--screenshot", help="render one frame to PNG and exit")
    gui.add_argument("--backend", choices=("auto", "gpio", "sim"), default="auto")
    capture = sub.add_parser("capture", help="capture digital samples to VCD")
    capture.add_argument("--simulate", action="store_true", help="use deterministic simulated inputs")
    capture.add_argument("--backend", choices=("auto", "gpio", "sim"), default="auto")
    capture.add_argument("--pins", required=True, help="comma-separated exposed GPIO numbers or aliases")
    capture.add_argument("--duration-ms", type=int, default=1000)
    capture.add_argument("--sample-period-us", type=int, default=1000)
    capture.add_argument("--allow-shared", action="store_true")
    capture.add_argument("--output", required=True)
    uart = sub.add_parser("uart", help="receive and decode 3.3V UART on Grove RX/GPIO15")
    uart.add_argument("--simulate", action="store_true", help="use deterministic simulated UART data")
    uart.add_argument("--device", default="/dev/serial0")
    uart.add_argument("--baud", type=int, choices=STANDARD_BAUDS, default=115200)
    uart.add_argument("--duration-ms", type=int, default=2000)
    uart.add_argument("--max-bytes", type=int, default=65536)
    send = uart.add_mutually_exclusive_group()
    send.add_argument("--send-text", help="transmit UTF-8 text before receiving")
    send.add_argument("--send-hex", help="transmit hexadecimal bytes before receiving")
    uart.add_argument("--append", choices=("none", "cr", "lf", "crlf"), default="none")
    uart.add_argument(
        "--allow-grove-uart",
        action="store_true",
        help="acknowledge GPIO15/Grove use; connect target TX and GND only",
    )
    uart.add_argument("--output", help="write decoded report instead of stdout")
    uart.add_argument(
        "--allow-uart-tx",
        action="store_true",
        help="explicitly arm 3.3V UART transmission on GPIO14",
    )
    i2c = sub.add_parser("i2c", help="scan external 3.3V I2C devices on GPIO2/GPIO3")
    i2c.add_argument("--simulate", action="store_true", help="use deterministic simulated devices")
    i2c.add_argument("--device", default="/dev/i2c-1")
    i2c.add_argument("--allow-shared-i2c", action="store_true")
    i2c.add_argument("--include-internal", action="store_true")
    i2c.add_argument("--allow-internal-i2c", action="store_true")
    i2c.add_argument("--output", help="write scan report instead of stdout")
    return root


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "i2c":
        if not args.simulate and not args.allow_shared_i2c:
            raise ValueError(
                "I2C1 is shared with the keyboard and internal devices; repeat with "
                "--allow-shared-i2c after connecting only a 3.3V target"
            )
        if args.include_internal and not args.simulate and not args.allow_internal_i2c:
            raise ValueError(
                "probing internal I2C devices can alter live device state; repeat with "
                "--allow-internal-i2c only for deliberate diagnostics"
            )
        scanner = SimulatedI2cScanner() if args.simulate else I2cScanner()
        device = "sim://i2c" if args.simulate else args.device
        report = format_i2c_scan(scanner.scan(device, args.include_internal))
        if args.output:
            Path(args.output).write_text(report, encoding="utf-8")
        else:
            print(report, end="")
        return 0
    if args.command == "uart":
        if not args.simulate and not args.allow_grove_uart:
            raise ValueError(
                "hardware UART is on shared Grove GPIO15; repeat with --allow-grove-uart "
                "after connecting target TX and GND only"
            )
        tx_requested = args.send_text is not None or args.send_hex is not None
        if tx_requested and not args.simulate and not args.allow_uart_tx:
            raise ValueError(
                "UART transmission drives shared Grove GPIO14; repeat with --allow-uart-tx "
                "only after verifying 3.3V TTL wiring"
            )
        device = "sim://uart" if args.simulate else args.device
        if tx_requested:
            payload = (
                args.send_text.encode("utf-8")
                if args.send_text is not None
                else parse_hex_bytes(args.send_hex)
            )
            payload += {"none": b"", "cr": b"\r", "lf": b"\n", "crlf": b"\r\n"}[args.append]
            terminal = SimulatedUartTerminal() if args.simulate else UartTerminal()
            capture = terminal.exchange(
                device, args.baud, payload, args.duration_ms, args.max_bytes
            )
        else:
            monitor = SimulatedUartMonitor() if args.simulate else UartMonitor()
            capture = monitor.capture(device, args.baud, args.duration_ms, args.max_bytes)
        report = format_uart_capture(capture)
        if args.output:
            Path(args.output).write_text(report, encoding="utf-8")
        else:
            print(report, end="")
        return 0
    backend_name = "sim" if getattr(args, "simulate", False) else args.backend
    backend = select_backend(backend_name)
    if args.command == "gui":
        settings = load_web_settings()
        interfaces = list_ipv4_interfaces() or (("lo", "127.0.0.1"),)
        app = AppController(
            backend,
            web_settings=settings,
            web_interfaces=interfaces,
            web_settings_saver=lambda value: save_web_settings(DEFAULT_SETTINGS_PATH, value),
        )
        return run_gui(app, screenshot=args.screenshot)
    request = CaptureRequest.from_csv(args.pins, allow_shared=args.allow_shared)
    gpios = CARDPUTER_ZERO.validate_capture(request).gpios
    capture = backend.capture(gpios, args.duration_ms, args.sample_period_us)
    Path(args.output).write_text(encode_vcd(capture, source=backend.name), encoding="utf-8")
    return 0
