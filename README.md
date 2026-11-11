# Speech Recorder (Python Desktop GUI)

A clean, native **Python Tkinter desktop application** for offline voice prompt recording and speech dataset creation.

Directly accesses OS audio hardware (ALSA, DirectSound, WASAPI, CoreAudio) to enforce studio recording standards, block internal laptop microphones, perform real-time acoustic quality checks, and auto-save pristine 16-bit PCM WAV audio directly to disk.

---

## Quick Start

### 1. Requirements
Make sure Python 3 is installed along with the required audio packages:
```bash
pip install sounddevice soundfile numpy
```

### 2. Launch the App
- **Windows**: Double-click `run.bat` (or run `python recorder_gui.py`)
- **Linux / Mac**: Double-click `run.sh` (or run `python3 recorder_gui.py`)

---

## Features

- **Direct Hardware Control**: Automatically lists all audio input devices and enforces external USB microphone / audio interface usage. **Blocks internal laptop mics** to eliminate handling noise and aggressive laptop dynamic compression.
- **Acoustic Quality Guards**:
  - Sample rate check: Enforces $\ge 24\text{ kHz}$ (defaults to native 44.1/48 kHz 16-bit PCM WAV).
  - Digital clipping detector: Flags distorted audio peaks ($\ge 0.985$) and prompts volunteer to adjust distance (15–20 cm) or lower mixer gain.
  - Voice Activity Detection (VAD): Harmonic pitch autocorrelation ($75 - 350\text{ Hz}$) detects if no human vocals were present (silent or dead mic).
  - Background noise floor (SNR) analysis.
  - Duration check: Flags takes that are too short ($< 2.5\text{s}$) or too long ($> 15.0\text{s}$) with a *"Keep & Mark for Review"* override option.
- **Direct Filesystem Storage**: Automatically writes `.wav` audio files to `recordings/wavs/` and metadata to `recordings/metadata.csv`.
- **One-Click Batch ZIP Export**: Packages recorded audio and the metadata manifest into a timestamped `.zip` archive ready for upload.
- **Keyboard Shortcuts**:
  - `Spacebar`: Toggle Record / Stop
  - `→` / `←`: Next / Previous prompt
  - `R`: Re-record current prompt
  - `P`: Play recorded take

---

## License
MIT License.
