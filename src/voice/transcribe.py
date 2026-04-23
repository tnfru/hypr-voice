"""Speech-to-text transcription using faster-whisper."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voice.config as cfg

if TYPE_CHECKING:
    import numpy as np
    from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

# Minimum audio duration worth transcribing (seconds)
MIN_DURATION = 0.3


class Transcriber:
    """Manages a faster-whisper model for speech-to-text transcription."""

    def __init__(self) -> None:
        """Initialize the transcriber with no model loaded."""
        self._model: WhisperModel | None = None

    def load(self) -> None:
        """Load the whisper model, falling back to CPU on GPU failure."""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel  # noqa: PLC0415

        log.info(
            "Loading model '%s' on %s (%s)...",
            cfg.MODEL_NAME,
            cfg.DEVICE,
            cfg.COMPUTE_TYPE,
        )
        try:
            self._model = WhisperModel(
                cfg.MODEL_NAME, device=cfg.DEVICE, compute_type=cfg.COMPUTE_TYPE
            )
        except Exception:  # noqa: BLE001
            log.warning(
                "Failed to load model on %s, falling back to cpu/int8", cfg.DEVICE
            )
            self._model = WhisperModel(
                cfg.MODEL_NAME, device="cpu", compute_type="int8"
            )
        log.info("Model loaded")

    def unload(self) -> None:
        """Unload the model and free resources."""
        if self._model is None:
            return
        del self._model
        self._model = None
        log.info("Model unloaded")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe an audio array to text.

        Args:
            audio: PCM audio samples as a numpy array.

        Returns:
            Transcribed text, or empty string if audio is too short or
            the model is not loaded.
        """
        if self._model is None:
            log.error("transcribe() called but model not loaded")
            return ""
        if audio.size < cfg.SAMPLE_RATE * MIN_DURATION:
            log.info("Audio too short (%.2fs), skipping", audio.size / cfg.SAMPLE_RATE)
            return ""

        segments, info = self._model.transcribe(
            audio,
            language=cfg.LANGUAGE,
            vad_filter=cfg.VAD_FILTER,
            initial_prompt=cfg.INITIAL_PROMPT,
            hotwords=cfg.HOTWORDS,
            beam_size=cfg.BEAM_SIZE,
        )

        text = " ".join(seg.text for seg in segments).strip()
        log.info(
            "Transcribed [%s %.0f%%] %d chars",
            info.language,
            info.language_probability * 100,
            len(text),
        )
        return text
