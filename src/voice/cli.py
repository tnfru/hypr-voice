"""CLI entry point for the voice dictation daemon."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
from pathlib import Path

from voice.config import PID_PATH, SOCKET_PATH


def _send_command(cmd: str) -> str:
    """Send a command to the daemon and return the response.

    Args:
        cmd: The command string to send over the Unix socket.

    Returns:
        The decoded response from the daemon.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(SOCKET_PATH)
        sock.sendall(cmd.encode() + b"\n")
        sock.settimeout(30.0)
        return sock.recv(4096).decode().strip()
    except (ConnectionRefusedError, FileNotFoundError):
        print("Daemon not running", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    finally:
        sock.close()


def _cmd_daemon(args: argparse.Namespace) -> None:
    """Start the voice daemon in the foreground.

    Args:
        args: Parsed CLI arguments (uses ``args.verbose``).
    """
    from voice.daemon import VoiceDaemon  # noqa: PLC0415

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    VoiceDaemon().run()


def _cmd_toggle(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Toggle recording on or off via the daemon.

    Args:
        args: Parsed CLI arguments (unused).
    """
    resp = _send_command("toggle")
    print(resp)  # noqa: T201


def _cmd_status(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Query and display the current daemon state.

    Args:
        args: Parsed CLI arguments (unused).
    """
    resp = _send_command("status")
    print(resp)  # noqa: T201


def _cmd_stop(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Stop a running daemon by sending SIGTERM.

    Args:
        args: Parsed CLI arguments (unused).
    """
    try:
        with Path(PID_PATH).open() as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to {pid}")  # noqa: T201
    except FileNotFoundError:
        print("PID file not found — daemon not running?", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    except ProcessLookupError:
        print("Process not found — cleaning up stale PID file", file=sys.stderr)  # noqa: T201
        Path(PID_PATH).unlink()
        sys.exit(1)


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate subcommand."""
    parser = argparse.ArgumentParser(prog="voice", description="Voice dictation daemon")
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    p_daemon = sub.add_parser("daemon", help="Start the daemon (foreground)")
    p_daemon.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    p_daemon.set_defaults(func=_cmd_daemon)

    p_toggle = sub.add_parser("toggle", help="Toggle recording")
    p_toggle.set_defaults(func=_cmd_toggle)

    p_status = sub.add_parser("status", help="Query daemon state")
    p_status.set_defaults(func=_cmd_status)

    p_stop = sub.add_parser("stop", help="Stop the daemon")
    p_stop.set_defaults(func=_cmd_stop)

    args = parser.parse_args()
    args.func(args)
