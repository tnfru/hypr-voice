"""Configuration constants for the voice dictation daemon."""

import contextlib
import ctypes
import os
import sys
from pathlib import Path

# Preload pip-installed NVIDIA shared libraries so ctranslate2 can find them.
# os.environ["LD_LIBRARY_PATH"] doesn't work — the dynamic linker only reads it
# at process startup. Instead, load the .so files directly via ctypes.
_site_packages = (
    Path(sys.prefix)
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
for _lib in sorted(_site_packages.glob("nvidia/*/lib/*.so.*")):
    with contextlib.suppress(OSError):
        ctypes.CDLL(str(_lib), mode=ctypes.RTLD_GLOBAL)

_runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

SOCKET_PATH = str(Path(_runtime_dir) / "voice.sock")
PID_PATH = str(Path(_runtime_dir) / "voice.pid")

MODEL_NAME = "large-v3-turbo"
DEVICE = "cuda"
COMPUTE_TYPE = "float16"

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"
INPUT_DEVICE = "fifine"  # substring match against sounddevice device names

# Whisper treats initial_prompt as prior transcript — natural sentences that reflect
# the speaker's style work better than word lists. Language auto-detected so both
# full-German and full-English input work; the initial_prompt biases toward your
# dominant language while still allowing the other when spoken.
LANGUAGE = None

# Customize this to match how you actually speak. Include project names, tech terms,
# and any vocabulary Whisper might struggle with. Sentences work better than word lists.
INITIAL_PROMPT = (
    "Okay, I'm going to do a git commit and push that to the PR. "
    "I've already merged the branch, the rebase worked fine. "
    "I'm refactoring the API endpoints in the backend with Python and FastAPI. "
    "The deploy runs through the CI/CD pipeline on Kubernetes. "
    "In Claude Code I can run that with a subagent in parallel. "
    "The frontend is TypeScript, the backend stays Python. "
    "I'm starting the Docker container and checking the logs in Kitty with tmux. "
    "When I'm done, I just say Over."
)

# Project-specific terms that faster-whisper should prefer (applied per-segment).
# Add your own names, tools, and domain terms here.
HOTWORDS = (
    "Hyprland, Neovim, Claude, Claude Code, Anthropic, "
    "Waybar, Kitty, tmux, ripgrep, Over"
)

VAD_FILTER = True
BEAM_SIZE = 5

# Continuous voice mode — real-time VAD thresholds
SILENCE_THRESHOLD = 0.01  # RMS below this = silence (tune per mic/environment)
UTTERANCE_SILENCE = 2.0  # seconds of silence after speech → transcribe
SUBMIT_SILENCE = 6.0  # seconds of silence after last typed text → send Enter

# Voice commands — if an entire utterance matches one of these (after stripping
# punctuation and lowercasing), it's treated as a command instead of text.
# Set to False to disable and type everything as text.
VOICE_COMMANDS_ENABLED = False
VOICE_COMMANDS: dict[str, str] = {
    "over": "submit",
    "senden": "submit",
    "enter": "submit",
    "abschicken": "submit",
    "submit": "submit",
    "neue zeile": "newline",
    "new line": "newline",
    "löschen": "clear",
}
