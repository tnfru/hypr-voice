# hypr-voice

> Speak, don't type. Local voice dictation for Hyprland and Wayland.

<br>

**hypr-voice** is a dictation daemon built for the Wayland ecosystem. It runs [faster-whisper](https://github.com/SYSTRAN/faster-whisper) locally on your GPU — no cloud, no latency, no subscription. Bind a key, toggle voice mode, and your words are typed into the focused window.

Designed for Hyprland users and developers who live in the terminal, mix languages, and want to keep their hands off the keyboard.

```
+-----------+      +----------------------------------------+
|  Keybind  |----->|  voice daemon                          |
+-----------+      |                                        |
                   |  Record (sounddevice, 48kHz)           |
                   |      |                                 |
                   |      v  energy-based VAD               |
                   |  2s silence -- utterance complete      |
                   |      |                                 |
                   |      v  resample to 16kHz              |
                   |  Transcribe (faster-whisper, GPU)      |
                   |      |                                 |
                   |      v                                 |
                   |  wtype --> focused window              |
                   +----------------------------------------+
```

## Features

- **One keybind** — toggle voice mode on/off, no modifier gymnastics
- **Continuous dictation** — speak naturally, each pause triggers transcription
- **Auto-submit** — Enter is pressed after extended silence
- **Fully local** — Whisper runs on your GPU, nothing leaves your machine
- **Multilingual** — auto-detects language, handles code-switching (e.g. German + English dev terms)
- **Custom vocabulary** — teach it your project names and jargon
- **VRAM-friendly** — model loads on toggle, unloads when you're done
- **Voice commands** (optional) — buffer text and submit by saying "Over"
- **Wayland-native** — text injection via [wtype](https://github.com/atx/wtype), works in any Wayland app

<br>

## Quick start

```bash
# 1. Install wtype
sudo dnf install wtype          # Fedora
# sudo pacman -S wtype          # Arch

# 2. Clone and install
git clone <repo-url> && cd hypr-voice
uv sync

# 3. Find and set your microphone (see "Finding your microphone" below)
#    Edit src/voice/config.py → INPUT_DEVICE = "fifine"  (any substring works)

# 4. Start the daemon
voice daemon

# 5. In another terminal — toggle voice mode
voice toggle
# Speak → text appears after 2s pause → Enter after 6s silence
# Run 'voice toggle' again to stop
```

<br>

## Hyprland setup

Add a keybind to `~/.config/hypr/UserConfigs/UserKeybinds.conf`:

```hyprlang
# Voice dictation toggle
bind = $mainMod, F, exec, /path/to/hypr-voice/.venv/bin/voice toggle
```

Auto-start the daemon on login in `~/.config/hypr/UserConfigs/Startup_Apps.conf`:

```hyprlang
exec-once = /path/to/hypr-voice/.venv/bin/voice daemon &
```

Then reload: `hyprctl reload`

> Works with any Wayland compositor that supports keybind exec — Hyprland, Sway, river, etc.

<br>

## How it works

1. **Toggle keybind** — voice mode on, Whisper model loads into VRAM
2. **Speak** — audio is captured and monitored for speech/silence transitions
3. **2s silence** — utterance is transcribed on GPU and typed into the focused window
4. **6s silence** — Enter is pressed automatically
5. **Toggle keybind** — voice mode off, model unloaded from VRAM

<br>

## Personalizing recognition

hypr-voice uses two mechanisms to improve accuracy for your vocabulary:

### Initial prompt

The `INITIAL_PROMPT` in [`src/voice/config.py`](src/voice/config.py) tells Whisper "this is what was said before." It's not an instruction — it's example text that conditions the model's style, language, and vocabulary.

**Write it as natural sentences in the way you actually speak:**

```python
INITIAL_PROMPT = (
    "Okay, I'm going to do a git commit and push that to the PR. "
    "I've already merged the branch, the rebase worked fine. "
    "I'm refactoring the API endpoints in the backend with Python and FastAPI. "
    "The deploy runs through the CI/CD pipeline on Kubernetes. "
    "When I'm done, I just say Over."
)
```

> **Why sentences?** Whisper is a language model. A keyword list signals "the output should be a keyword list." Natural sentences teach it your speaking rhythm, your language mix, and your terminology all at once. Max 224 tokens (~150 words).

### Hotwords

The `HOTWORDS` string biases faster-whisper toward specific terms per segment. Good for project names, tools, or anything Whisper tends to get wrong:

```python
HOTWORDS = "Hyprland, Neovim, Claude Code, MyProjectName, Over"
```

<br>

## Finding your microphone

Run this to see all audio devices:

```bash
uv run python -c "import sounddevice as sd; print(sd.query_devices())"
```

Output looks like:

```
   0 fifine Microphone: USB Audio (hw:0,0), ALSA (2 in, 2 out)
   1 HDA NVidia: HDMI (hw:1,3), ALSA (0 in, 2 out)
   ...
  16 default, ALSA (64 in, 64 out)
```

Pick your mic's name and set a substring in `src/voice/config.py`:

```python
INPUT_DEVICE = "fifine"       # matches "fifine Microphone: USB Audio"
# INPUT_DEVICE = "Blue Yeti"  # matches "Blue Yeti: USB Audio"
# INPUT_DEVICE = ""           # use system default
```

<br>

## CLI reference

```bash
voice daemon          # start daemon (foreground)
voice daemon -v       # start with debug logging
voice toggle          # toggle voice mode on/off
voice status          # print current state (idle/listening)
voice stop            # stop the daemon
```

<br>

## Configuration reference

All settings live in [`src/voice/config.py`](src/voice/config.py):

### Model

| Setting | Default | Description |
|---|---|---|
| `MODEL_NAME` | `large-v3-turbo` | Whisper model. Options: `tiny`, `small`, `medium`, `large-v3`, `large-v3-turbo` |
| `DEVICE` | `cuda` | Compute device: `cuda` or `cpu` |
| `COMPUTE_TYPE` | `float16` | Model precision: `float16`, `int8`, `float32` |

### Audio

| Setting | Default | Description |
|---|---|---|
| `INPUT_DEVICE` | `fifine` | Substring match against audio device names |
| `SILENCE_THRESHOLD` | `0.01` | RMS level below which audio is silence. Tune for your mic/room |
| `UTTERANCE_SILENCE` | `2.0` | Seconds of silence to trigger transcription |
| `SUBMIT_SILENCE` | `6.0` | Seconds of silence to auto-press Enter |

### Language

| Setting | Default | Description |
|---|---|---|
| `LANGUAGE` | `None` | Force a language (`"de"`, `"en"`) or `None` for auto-detect |
| `INITIAL_PROMPT` | *(see above)* | Conditions Whisper's style and vocabulary |
| `HOTWORDS` | *(see above)* | Terms faster-whisper should prefer per segment |

### Voice command mode (optional)

Set `VOICE_COMMANDS_ENABLED = True` for a buffered workflow — text is held until you say a command:

| Command | Action |
|---|---|
| **"Over"** | Type the entire buffer + press Enter |
| **"Löschen"** | Clear the buffer |
| **"Neue Zeile"** | Insert a newline |

In this mode, nothing is typed until you speak a command. A notification shows the accumulated text. Use your toggle keybind to discard and exit.

<br>

## Architecture

```
src/voice/
├── cli.py          CLI entry point. Lazy imports — toggle/status use
│                   only stdlib for <50ms keybind response.
├── daemon.py       Unix socket server, state machine (idle → listening),
│                   orchestrates recording → transcription → injection.
├── audio.py        Continuous recording via sounddevice with real-time
│                   energy-based VAD. Detects utterance boundaries and
│                   resamples 48kHz → 16kHz for Whisper.
├── transcribe.py   faster-whisper wrapper with lazy model load/unload.
│                   Falls back from GPU to CPU automatically.
└── config.py       All tunable parameters. Preloads NVIDIA shared
                    libraries via ctypes for CUDA support.
```

Communication: Unix socket at `$XDG_RUNTIME_DIR/voice.sock`, single-line text protocol (`toggle`, `status`, `quit`).

<br>

## Requirements

- Linux with Wayland (tested on Hyprland 0.51+, should work on Sway, river, etc.)
- NVIDIA GPU with CUDA support (CPU fallback available)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [wtype](https://github.com/atx/wtype)

<br>

## Troubleshooting

| Problem | Fix |
|---|---|
| "Daemon not running" | Start with `voice daemon &` or check logs |
| No text appears | Verify `wtype` is installed and `WAYLAND_DISPLAY` is set |
| Wrong microphone | Run `voice daemon -v`, check log output, adjust `INPUT_DEVICE` |
| Poor transcription | Try `large-v3`, adjust `INITIAL_PROMPT` to your style, add `HOTWORDS` |
| CUDA errors | Daemon falls back to CPU automatically. Check `nvidia-smi` |
| High GPU fan noise | Try `large-v3-turbo` (default) or `medium` for less GPU load |

Logs: `tail -f /tmp/voice-daemon.log`

<br>

## License

MIT
