# Speech Recorder

A lightweight, clean, **100% offline in-browser speech recording tool** designed for field speech data collection, volunteer prompt reading, and speech dataset creation.

No accounts, no volunteer codes, and no server or cloud setup required. Runs completely client-side in any browser.

---

## Key Features

- **100% Offline**: Zero external server calls or cloud requirements during recording. Can run completely offline or from local file storage (`file:///...`).
- **Simple Prompter View**: Large, clear sentence display for comfortable volunteer reading.
- **Custom CSV Loader**: Load any `.csv` file containing sentence prompts (auto-detects `sentence` or `text` column).
- **Auto-Persistent Storage**: Audio clips are saved automatically to browser `IndexedDB`. Never lose progress if the browser is closed or refreshed.
- **One-Click Batch ZIP Export**: Download all recorded `.wav` files and a clean `metadata.csv` manifest at any time with one click.
- **Pure 16-bit PCM WAV**: Direct uncompressed WAV encoding matching automatic speech recognition (ASR) and text-to-speech (TTS) training requirements.
- **Keyboard Shortcuts**:
  - `Spacebar`: Toggle Record / Stop
  - `Right Arrow (→)`: Next sentence
  - `Left Arrow (←)`: Previous sentence
  - `R`: Re-record current prompt

---

## How to Use

1. **Open the App**: Simply open `index.html` in Chrome, Firefox, Safari, or Edge (or visit via GitHub Pages).
2. **Load Prompts**: Drag and drop your prompt CSV file (e.g., `sample_prompts.csv` or `lein_recording_prompts_200h.csv`), or click *Use Built-in Sample Prompts*.
3. **Record Prompts**:
   - Align microphone on stand 15–20 cm from mouth.
   - Press **Spacebar** (or tap **REC**) to start.
   - Read the sentence clearly.
   - Press **Spacebar** to stop.
   - Tap **Next →** (or press `→`) to advance.
4. **Export Batch**: Click **📦 Export Batch (.ZIP)** at any time. The downloaded ZIP archive contains:
   - `wavs/`: Folder with all `.wav` audio files (`LEIN_PR_000001.wav`, etc.).
   - `metadata.csv`: Maps `audio_filename`, `prompt_id`, `sentence`, `duration_seconds`, `timestamp`, and `volunteer_station`.
   - `session_summary.json`: High-level session statistics.

---

## License

MIT License. Developed for open speech data collection initiatives.
