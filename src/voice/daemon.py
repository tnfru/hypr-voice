"""Unix-socket daemon for voice recording, transcription, and text injection."""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

from voice.audio import AudioRecorder
from voice.config import (
    PID_PATH,
    SOCKET_PATH,
    SUBMIT_SILENCE,
    VOICE_COMMANDS,
    VOICE_COMMANDS_ENABLED,
)
from voice.transcribe import Transcriber

log = logging.getLogger(__name__)

# Poll interval in listening mode — controls responsiveness of utterance detection.
_POLL_INTERVAL = 0.2


class VoiceDaemon:
    """Manages the voice input lifecycle over a Unix domain socket."""

    def __init__(self) -> None:
        """Initialize recorder, transcriber, and daemon state."""
        self._recorder = AudioRecorder()
        self._transcriber = Transcriber()
        self._state = "idle"  # idle | listening
        self._sock: socket.socket | None = None
        self._pending_submit = False
        self._buffer: list[str] = []

    def run(self) -> None:
        """Run the main daemon event loop."""
        self._check_stale_socket()
        self._write_pid()
        atexit.register(self._cleanup)
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(SOCKET_PATH)
        self._sock.listen(2)
        self._sock.settimeout(_POLL_INTERVAL)

        log.info("Daemon ready, listening on %s", SOCKET_PATH)

        while True:
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                if self._state == "listening":
                    self._process_voice()
                continue
            except OSError:
                break

            try:
                self._handle_client(conn)
            except Exception:
                log.exception("Error handling client")
            finally:
                conn.close()

    def _handle_client(self, conn: socket.socket) -> None:
        """Dispatch a single client command and send the response."""
        conn.settimeout(5.0)
        data = conn.recv(1024).decode().strip()
        if not data:
            return

        match data:
            case "toggle":
                resp = self._toggle()
            case "status":
                resp = self._state
            case "quit":
                conn.sendall(b"ok\n")
                self._cleanup()
                sys.exit(0)
            case _:
                resp = f"error unknown command: {data}"

        conn.sendall(resp.encode() + b"\n")

    def _toggle(self) -> str:
        """Toggle between idle and listening states."""
        match self._state:
            case "idle":
                return self._start_listening()
            case "listening":
                return self._stop_listening()
            case _:
                return f"error bad state: {self._state}"

    def _start_listening(self) -> str:
        """Load the model, start recording, and enter listening state."""
        self._notify(
            "Voice", "Loading model...", icon="audio-input-microphone", timeout=3000
        )
        self._transcriber.load()

        try:
            self._recorder.start()
        except Exception:
            log.exception("Failed to start recording")
            self._transcriber.unload()
            return "error recording failed"

        self._state = "listening"
        self._pending_submit = False
        self._buffer.clear()
        self._notify(
            "Voice", "Listening...", icon="audio-input-microphone", timeout=1500
        )
        return "ok listening"

    def _stop_listening(self) -> str:
        """Stop recording, unload the model, and return to idle."""
        self._recorder.stop()
        self._transcriber.unload()
        self._state = "idle"
        self._pending_submit = False
        if self._buffer:
            log.info("Discarded buffer: %s", " ".join(self._buffer))
        self._buffer.clear()
        self._notify("Voice", "Stopped", icon="audio-input-microphone", timeout=1500)
        return "ok stopped"

    def _process_voice(self) -> None:
        """Called periodically while in listening mode."""
        audio = self._recorder.get_utterance()
        if audio is not None:
            text = self._transcriber.transcribe(audio)
            if text:
                if VOICE_COMMANDS_ENABLED:
                    # Buffer mode: check for command, otherwise buffer
                    command = self._match_voice_command(text)
                    if command:
                        self._exec_voice_command(command, text)
                        return
                    self._buffer.append(text)
                    log.info("Buffered: %s", text)
                    self._notify(
                        "Voice",
                        " ".join(self._buffer),
                        icon="dialog-information",
                        timeout=0,
                    )
                else:
                    # Direct mode: type immediately
                    self._inject_text(text)
                    self._pending_submit = True
                    log.info("Typed: %s", text)

        # Auto-Enter after extended silence (direct mode only)
        if not VOICE_COMMANDS_ENABLED and self._pending_submit:
            silence = self._recorder.seconds_since_last_speech()
            if silence >= SUBMIT_SILENCE:
                self._inject_key("Return")
                self._pending_submit = False
                log.info("Auto-submitted (%.1fs silence)", silence)

    @staticmethod
    def _match_voice_command(text: str) -> str | None:
        """Match if the entire utterance is a voice command."""
        normalized = text.strip().lower().rstrip(".,!?")
        return VOICE_COMMANDS.get(normalized)

    def _exec_voice_command(self, command: str, raw: str) -> None:
        """Execute a matched voice command."""
        log.info("Voice command: %r → %s", raw, command)
        match command:
            case "submit":
                if self._buffer:
                    text = " ".join(self._buffer)
                    self._inject_text(text)
                    self._buffer.clear()
                    log.info("Submitted buffer: %s", text)
                self._inject_key("Return")
            case "newline":
                self._inject_key("Return")  # in most contexts newline = Return
            case "clear":
                self._buffer.clear()
                log.info("Buffer cleared")
            case _:
                log.warning("Unknown voice command: %s", command)

    def _inject_text(self, text: str) -> None:
        """Type text into the focused window via wtype."""
        try:
            subprocess.run(  # noqa: S603
                ["wtype", "--", text],  # noqa: S607
                timeout=10,
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            log.warning("wtype not found, falling back to wl-copy")
            subprocess.run(  # noqa: S603
                ["wl-copy", "--", text],  # noqa: S607
                check=False,
            )
        except subprocess.SubprocessError:
            log.exception("wtype failed, falling back to wl-copy")
            subprocess.run(  # noqa: S603
                ["wl-copy", "--", text],  # noqa: S607
                check=False,
            )

    def _inject_key(self, key: str) -> None:
        """Send a single keypress via wtype."""
        try:
            subprocess.run(  # noqa: S603
                ["wtype", "-k", key],  # noqa: S607
                timeout=5,
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            log.warning("wtype not found, cannot send key %s", key)
        except subprocess.SubprocessError:
            log.exception("wtype failed to send key %s", key)

    def _notify(self, title: str, body: str, *, icon: str, timeout: int) -> None:
        """Send a desktop notification via notify-send."""
        with contextlib.suppress(FileNotFoundError):
            subprocess.Popen(  # noqa: S603
                ["notify-send", "-t", str(timeout), "-i", icon, title, body],  # noqa: S607
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _check_stale_socket(self) -> None:
        """Remove a stale socket file, or exit if another daemon is running."""
        if not Path(SOCKET_PATH).exists():
            return
        try:
            test = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            test.connect(SOCKET_PATH)
            test.close()
            log.error("Another daemon is already running on %s", SOCKET_PATH)
            sys.exit(1)
        except ConnectionRefusedError:
            log.info("Removing stale socket %s", SOCKET_PATH)
            Path(SOCKET_PATH).unlink()

    def _write_pid(self) -> None:
        """Write the current PID to the pid file."""
        with Path(PID_PATH).open("w") as f:
            f.write(str(os.getpid()))

    def _cleanup(self) -> None:
        """Tear down recorder, socket, and pid file."""
        log.info("Daemon shutting down")
        if self._recorder.is_recording:
            self._recorder.stop()
        for path in (SOCKET_PATH, PID_PATH):
            with contextlib.suppress(OSError):
                Path(path).unlink()
        if self._sock:
            with contextlib.suppress(OSError):
                self._sock.close()

    def _signal_handler(self, signum: int, frame: object) -> None:  # noqa: ARG002
        """Handle SIGTERM/SIGINT by cleaning up and exiting."""
        log.info("Received signal %d", signum)
        self._cleanup()
        sys.exit(0)
