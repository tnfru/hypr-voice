"""Continuous audio recording with energy-based voice activity detection."""

from __future__ import annotations

import logging
import threading
import time

import numpy as np
import sounddevice as sd

from voice.config import (
    CHANNELS,
    DTYPE,
    INPUT_DEVICE,
    SAMPLE_RATE,
    SILENCE_THRESHOLD,
    UTTERANCE_SILENCE,
)

log = logging.getLogger(__name__)

# Record at device's native rate, resample to SAMPLE_RATE for Whisper.
NATIVE_RATE = 48000


def _find_input_device(name: str) -> int | None:
    """Find a sounddevice input device by substring match."""
    for i, dev in enumerate(sd.query_devices()):
        if name.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
            return i
    return None


def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample audio via linear interpolation. Good enough for speech-to-text."""
    if orig_sr == target_sr:
        return audio
    n_out = int(len(audio) * target_sr / orig_sr)
    indices = np.linspace(0, len(audio) - 1, n_out)
    return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)


class AudioRecorder:
    """Continuous recorder with real-time energy-based VAD.

    Runs in listening mode: audio callback detects speech/silence transitions
    and packages completed utterances for pickup by the main loop.
    """

    def __init__(self) -> None:
        """Initialize the recorder and resolve the input device."""
        self._stream: sd.InputStream | None = None
        self._device = _find_input_device(INPUT_DEVICE) if INPUT_DEVICE else None
        if self._device is not None:
            dev_name = sd.query_devices(self._device)["name"]
            log.info("Using input device %d: %s", self._device, dev_name)
        else:
            log.warning(
                "Input device '%s' not found, using system default", INPUT_DEVICE
            )

        self._lock = threading.Lock()
        self._utterance_chunks: list[np.ndarray] = []
        self._in_speech = False
        self._speech_in_utterance = False
        self._last_speech_time = 0.0
        # Completed utterance waiting for pickup (at native rate)
        self._ready_audio: np.ndarray | None = None

    @property
    def is_recording(self) -> bool:
        """Whether the audio stream is currently active."""
        return self._stream is not None and self._stream.active

    def start(self) -> None:
        """Open the input stream and begin listening for speech."""
        if self.is_recording:
            return

        with self._lock:
            self._utterance_chunks.clear()
            self._in_speech = False
            self._speech_in_utterance = False
            self._last_speech_time = 0.0
            self._ready_audio = None

        def callback(
            indata: np.ndarray,
            frames: int,  # noqa: ARG001
            time_info: object,  # noqa: ARG001
            status: sd.CallbackFlags,
        ) -> None:
            if status:
                log.warning("Audio callback status: %s", status)

            chunk = indata.copy().flatten()
            rms = np.sqrt(np.mean(chunk**2))
            now = time.monotonic()
            is_speech = rms > SILENCE_THRESHOLD

            with self._lock:
                # Don't accumulate if a previous utterance hasn't been picked up
                if self._ready_audio is not None:
                    if is_speech:
                        self._last_speech_time = now
                    return

                if is_speech:
                    self._in_speech = True
                    self._speech_in_utterance = True
                    self._last_speech_time = now
                    self._utterance_chunks.append(chunk)
                elif self._in_speech:
                    # Silence after speech — keep buffering (could be a natural pause)
                    self._utterance_chunks.append(chunk)

                    silence_duration = now - self._last_speech_time
                    if silence_duration >= UTTERANCE_SILENCE:
                        # Utterance complete — package it
                        audio = np.concatenate(self._utterance_chunks)
                        self._ready_audio = audio
                        self._utterance_chunks.clear()
                        self._in_speech = False
                        self._speech_in_utterance = False
                        log.info(
                            "Utterance detected: %.1fs audio",
                            len(audio) / NATIVE_RATE,
                        )
                # else: silence before any speech — ignore

        self._stream = sd.InputStream(
            device=self._device,
            samplerate=NATIVE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=callback,
        )
        self._stream.start()
        log.info("Listening started (%d Hz)", NATIVE_RATE)

    def stop(self) -> None:
        """Stop and close the audio stream."""
        if not self.is_recording:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            self._utterance_chunks.clear()
            self._ready_audio = None
        log.info("Listening stopped")

    def get_utterance(self) -> np.ndarray | None:
        """Return a completed utterance resampled to SAMPLE_RATE, or None."""
        with self._lock:
            audio = self._ready_audio
            self._ready_audio = None
        if audio is None:
            return None
        return _resample(audio, NATIVE_RATE, SAMPLE_RATE)

    def seconds_since_last_speech(self) -> float:
        """Return seconds elapsed since the last detected speech, or 0.0 if none."""
        with self._lock:
            if self._last_speech_time == 0.0:
                return 0.0
            return time.monotonic() - self._last_speech_time
