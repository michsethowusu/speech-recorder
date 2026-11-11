#!/usr/bin/env python3
"""LEIN Offline Speech Recorder — Tkinter Desktop GUI.

A lightweight, robust desktop application for volunteer voice prompt recording.
Runs 100% offline, connects directly to USB microphones/audio interfaces,
enforces acoustic quality standards (blocks internal laptop mics, clipping, high noise),
and saves 16-bit PCM WAV audio and metadata directly to local disk with one-click ZIP export.
"""

import os
import sys
import time
import math
import queue
import threading
import zipfile
import re
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
import sounddevice as sd
import soundfile as sf

# Quality Thresholds
MIN_SAMPLE_RATE = 24000
MAX_PEAK_THRESHOLD = 0.985   # Digital clipping threshold
MIN_PEAK_THRESHOLD = 0.080   # Inaudible / too quiet threshold (-22 dBFS)
MIN_DURATION_SEC = 2.5       # Short take threshold
MAX_DURATION_SEC = 15.0      # Long take threshold

INTERNAL_PATTERNS = re.compile(r'(internal|built-?in|integrated|default|array|conexant|realtek|macbook|laptop|system|high definition audio|analog stereo)', re.IGNORECASE)
EXTERNAL_PATTERNS = re.compile(r'(usb|external|scarlett|focusrite|behringer|samson|shure|rode|audiobox|presonus|yeti|blue|hyperx|headset|line\s*in|interface|mic\s*in|streamer|broadcast)', re.IGNORECASE)


class SpeechRecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LEIN Speech Recorder — Offline Voice Collection")
        self.root.geometry("860x720")
        self.root.minsize(780, 640)

        # State
        self.prompts = []
        self.current_index = 0
        self.recordings_map = {}  # prompt_id -> dict
        self.is_recording = False
        self.audio_queue = queue.Queue()
        self.recorded_chunks = []
        self.stream = None
        self.rec_start_time = 0
        self.selected_device_id = None
        self.sample_rate = 44100
        self.is_external_mic = False
        self.pending_take = None
        self.current_clip_clipped = False

        # Output Directories
        self.output_dir = Path("recordings")
        self.wavs_dir = self.output_dir / "wavs"
        self.metadata_file = self.output_dir / "metadata.csv"
        self.wavs_dir.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self._load_existing_metadata()
        self.refresh_audio_devices()
        self._auto_load_default_csv()

    def _build_ui(self):
        # Palette: Clean Executive Slate / Monochrome
        self.bg_color = "#F8FAFC"
        self.card_bg = "#FFFFFF"
        self.root.configure(bg=self.bg_color)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TLabel", background=self.card_bg, font=("Arial", 11))
        style.configure("TButton", font=("Arial", 10, "bold"), padding=6)
        style.configure("TCombobox", font=("Arial", 10))

        # Top Control Header Bar
        top_frame = tk.Frame(self.root, bg=self.card_bg, padx=16, pady=10, relief=tk.SOLID, bd=1)
        top_frame.pack(fill=tk.X, side=tk.TOP)

        brand_lbl = tk.Label(top_frame, text="LEIN Speech Recorder", font=("Arial", 13, "bold"), bg=self.card_bg)
        brand_lbl.pack(side=tk.LEFT, padx=(0, 12))

        # Station / Volunteer input
        tk.Label(top_frame, text="Volunteer / Station:", font=("Arial", 10, "bold"), bg=self.card_bg).pack(side=tk.LEFT, padx=(0, 4))
        self.station_entry = tk.Entry(top_frame, font=("Arial", 10), width=16)
        self.station_entry.insert(0, "Station_1")
        self.station_entry.pack(side=tk.LEFT, padx=(0, 16))

        # Export Button
        self.export_btn = tk.Button(top_frame, text="Export Batch (.ZIP)", font=("Arial", 10, "bold"),
                                    bg="#0F172A", fg="#FFFFFF", activebackground="#1E293B", activeforeground="#FFF",
                                    padx=12, pady=4, cursor="hand2", command=self.export_zip)
        self.export_btn.pack(side=tk.RIGHT)

        self.load_csv_btn = tk.Button(top_frame, text="Load Prompts CSV", font=("Arial", 10),
                                      bg="#F1F5F9", relief=tk.GROOVE, padx=10, pady=3,
                                      command=self.load_csv_dialog)
        self.load_csv_btn.pack(side=tk.RIGHT, padx=8)

        # Hardware Bar (Microphone Enforcer)
        hw_frame = tk.Frame(self.root, bg="#FFFFFF", padx=16, pady=8, relief=tk.SOLID, bd=1)
        hw_frame.pack(fill=tk.X, side=tk.TOP)

        tk.Label(hw_frame, text="Input Microphone:", font=("Arial", 10, "bold"), bg="#FFFFFF").pack(side=tk.LEFT, padx=(0, 6))

        self.mic_combo = ttk.Combobox(hw_frame, state="readonly", width=42)
        self.mic_combo.bind("<<ComboboxSelected>>", self.on_mic_selected)
        self.mic_combo.pack(side=tk.LEFT, padx=(0, 8))

        rescan_btn = tk.Button(hw_frame, text="Rescan", font=("Arial", 9), padx=6, pady=2, command=self.refresh_audio_devices)
        rescan_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.mic_badge = tk.Label(hw_frame, text="Checking Mic...", font=("Arial", 10, "bold"), bg="#FEE2E2", fg="#991B1B", padx=8, pady=2)
        self.mic_badge.pack(side=tk.LEFT, padx=4)

        self.rate_badge = tk.Label(hw_frame, text="44.1 kHz", font=("Arial", 10), bg="#F1F5F9", padx=8, pady=2)
        self.rate_badge.pack(side=tk.RIGHT)

        # Warning / Quality Alert Banner Frame
        self.banner_frame = tk.Frame(self.root, bg="#FEE2E2", padx=16, pady=10, relief=tk.SOLID, bd=1)
        self.banner_lbl = tk.Label(self.banner_frame, text="", font=("Arial", 10, "bold"), bg="#FEE2E2", fg="#7F1D1D", justify=tk.LEFT, wraplength=760)
        self.banner_lbl.pack(fill=tk.X)

        # Main Workspace Container
        main_frame = tk.Frame(self.root, bg=self.bg_color, padx=20, pady=14)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Prompter Card
        self.prompter_card = tk.Frame(main_frame, bg=self.card_bg, relief=tk.SOLID, bd=1, padx=24, pady=20)
        self.prompter_card.pack(fill=tk.BOTH, expand=True)

        # Prompt Header Stats
        meta_row = tk.Frame(self.prompter_card, bg=self.card_bg)
        meta_row.pack(fill=tk.X, pady=(0, 14))

        self.prompt_id_lbl = tk.Label(meta_row, text="ID: -", font=("Courier", 12, "bold"), bg="#EFF6FF", fg="#1D4ED8", padx=8, pady=2)
        self.prompt_id_lbl.pack(side=tk.LEFT)

        self.status_tag_lbl = tk.Label(meta_row, text="", font=("Arial", 10, "bold"), bg=self.card_bg)
        self.status_tag_lbl.pack(side=tk.LEFT, padx=12)

        self.progress_lbl = tk.Label(meta_row, text="Prompt 0 of 0 | 0 Recorded", font=("Arial", 10, "bold"), fg="#64748B", bg=self.card_bg)
        self.progress_lbl.pack(side=tk.RIGHT)

        # Big Prompter Display
        prompter_box = tk.Frame(self.prompter_card, bg="#F8FAFC", relief=tk.SOLID, bd=1, padx=20, pady=30)
        prompter_box.pack(fill=tk.BOTH, expand=True, pady=(0, 16))

        self.prompt_text_lbl = tk.Label(
            prompter_box,
            text="Load a prompt CSV file (or lein_recording_prompts_200h.csv) to begin.",
            font=("Arial", 18, "bold"),
            bg="#F8FAFC",
            fg="#0F172A",
            wraplength=720,
            justify=tk.CENTER
        )
        self.prompt_text_lbl.pack(expand=True)

        # VU Level Visualizer Meter Bar & Timer
        meter_row = tk.Frame(self.prompter_card, bg="#F1F5F9", padx=12, pady=6, relief=tk.GROOVE)
        meter_row.pack(fill=tk.X, pady=(0, 18))

        tk.Label(meter_row, text="Mic Level:", font=("Arial", 9, "bold"), bg="#F1F5F9").pack(side=tk.LEFT, padx=(0, 8))
        self.meter_canvas = tk.Canvas(meter_row, height=14, bg="#E2E8F0", highlightthickness=0)
        self.meter_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self.timer_lbl = tk.Label(meter_row, text="00:00", font=("Courier", 12, "bold"), bg="#F1F5F9", width=6)
        self.timer_lbl.pack(side=tk.RIGHT, padx=(8, 0))

        # Controls Row (Previous, Big REC, Next)
        ctrl_row = tk.Frame(self.prompter_card, bg=self.card_bg)
        ctrl_row.pack(pady=(0, 14))

        self.prev_btn = tk.Button(ctrl_row, text="← Prev", font=("Arial", 11, "bold"), padx=16, pady=8, command=self.prev_prompt)
        self.prev_btn.pack(side=tk.LEFT, padx=12)

        self.rec_btn = tk.Button(ctrl_row, text="● REC", font=("Arial", 13, "bold"),
                                 bg="#DC2626", fg="#FFFFFF", activebackground="#B91C1C", activeforeground="#FFF",
                                 width=12, pady=10, cursor="hand2", command=self.toggle_record)
        self.rec_btn.pack(side=tk.LEFT, padx=12)

        self.next_btn = tk.Button(ctrl_row, text="Next →", font=("Arial", 11, "bold"), bg="#0F172A", fg="#FFF",
                                  activebackground="#1E293B", activeforeground="#FFF", padx=16, pady=8, command=self.next_prompt)
        self.next_btn.pack(side=tk.LEFT, padx=12)

        # Review & Override Row
        self.review_frame = tk.Frame(self.prompter_card, bg="#F0FDF4", padx=12, pady=8, relief=tk.SOLID, bd=1)
        self.review_lbl = tk.Label(self.review_frame, text="Take Verified", font=("Arial", 10, "bold"), bg="#F0FDF4", fg="#166534")
        self.review_lbl.pack(side=tk.LEFT, padx=8)

        self.play_btn = tk.Button(self.review_frame, text="▶ Play Take", font=("Arial", 9, "bold"), command=self.play_current_take)
        self.play_btn.pack(side=tk.LEFT, padx=6)

        self.re_record_btn = tk.Button(self.review_frame, text="Re-record", font=("Arial", 9), command=self.re_record_prompt)
        self.re_record_btn.pack(side=tk.LEFT, padx=6)

        self.override_btn = tk.Button(self.review_frame, text="Keep & Mark for Review", font=("Arial", 9, "bold"),
                                      bg="#FEF3C7", fg="#92400E", command=self.confirm_override_take)

        # Shortcuts Legend Footer
        legend_row = tk.Frame(self.prompter_card, bg=self.card_bg)
        legend_row.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))

        shortcut_text = "Shortcuts: Space = Record/Stop  |  → = Next  |  ← = Prev  |  R = Re-record  |  P = Play Take"
        tk.Label(legend_row, text=shortcut_text, font=("Arial", 9), fg="#64748B", bg=self.card_bg).pack(side=tk.LEFT)

        # Global Keyboard Bindings
        self.root.bind("<space>", lambda e: self._on_spacebar(e))
        self.root.bind("<Right>", lambda e: self.next_prompt())
        self.root.bind("<Left>", lambda e: self.prev_prompt())
        self.root.bind("r", lambda e: self.re_record_prompt())
        self.root.bind("p", lambda e: self.play_current_take())

    # -------------------------------------------------------------
    # HARDWARE & MICROPHONE ENFORCEMENT
    # -------------------------------------------------------------

    def refresh_audio_devices(self):
        try:
            devices = sd.query_devices()
            input_devices = []
            external_device_idx = None

            for idx, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0:
                    name = dev.get("name", f"Device {idx}")
                    is_ext = bool(EXTERNAL_PATTERNS.search(name))
                    is_int = bool(INTERNAL_PATTERNS.search(name)) and not is_ext
                    input_devices.append((idx, name, is_ext, is_int))

            if not input_devices:
                self.mic_combo["values"] = ["No microphones detected"]
                self.set_mic_blocked(True, "No audio input devices detected on your computer.")
                return

            combo_values = []
            default_selection = 0

            for i, (idx, name, is_ext, is_int) in enumerate(input_devices):
                if is_ext:
                    label = f"[{idx}] 🎙️ {name} (External - Ready)"
                    if external_device_idx is None:
                        external_device_idx = i
                elif is_int:
                    label = f"[{idx}] 🚫 {name} (Internal - Blocked)"
                else:
                    label = f"[{idx}] 🎙️ {name}"
                    if external_device_idx is None:
                        external_device_idx = i
                combo_values.append(label)

            self.mic_combo["values"] = combo_values
            self.input_devices_list = input_devices

            # Select external device if available
            sel_idx = external_device_idx if external_device_idx is not None else 0
            self.mic_combo.current(sel_idx)
            self._apply_device_selection(input_devices[sel_idx])

        except Exception as e:
            self.set_mic_blocked(True, f"Error querying audio hardware: {e}")

    def on_mic_selected(self, event=None):
        sel_idx = self.mic_combo.current()
        if 0 <= sel_idx < len(self.input_devices_list):
            self._apply_device_selection(self.input_devices_list[sel_idx])

    def _apply_device_selection(self, dev_tuple):
        idx, name, is_ext, is_int = dev_tuple
        self.selected_device_id = idx

        try:
            dev_info = sd.query_devices(idx)
            sr = int(dev_info.get("default_samplerate", 44100))
            self.sample_rate = sr if sr >= MIN_SAMPLE_RATE else 44100
            self.rate_badge.configure(text=f"{self.sample_rate / 1000:.1f} kHz PCM")
        except Exception:
            self.sample_rate = 44100

        if is_int and not is_ext:
            self.set_mic_blocked(True, f"Internal Laptop Microphone Blocked ('{name}'). Built-in microphones cause heavy audio compression and distortion. Please plug in an external USB microphone or audio interface and select it from the dropdown.")
        else:
            self.set_mic_blocked(False)

    def set_mic_blocked(self, blocked, message=""):
        if blocked:
            self.is_external_mic = False
            self.mic_badge.configure(text="🚫 Internal Mic (Blocked)", bg="#FEE2E2", fg="#991B1B")
            self.rec_btn.configure(state=tk.DISABLED, bg="#94A3B8")
            self.banner_lbl.configure(text=message)
            self.banner_frame.pack(fill=tk.X, side=tk.TOP, before=self.root.winfo_children()[2])
        else:
            self.is_external_mic = True
            self.mic_badge.configure(text="✓ External Mic Active", bg="#DCFCE7", fg="#166534")
            self.rec_btn.configure(state=tk.NORMAL, bg="#DC2626")
            self.banner_frame.pack_forget()

    # -------------------------------------------------------------
    # CSV LOADING & SESSION RESUME
    # -------------------------------------------------------------

    def _auto_load_default_csv(self):
        default_csv = Path("lein_recording_prompts_200h.csv")
        if default_csv.exists():
            self._load_csv_file(default_csv)

    def load_csv_dialog(self):
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
        if path:
            self._load_csv_file(Path(path))

    def _load_csv_file(self, csv_path):
        import csv
        parsed = []
        try:
            with open(csv_path, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                headers = [h.strip().lower() for h in reader.fieldnames or []]
                text_col = next((h for h in headers if h in ["sentence", "text", "prompt", "content"]), reader.fieldnames[0] if reader.fieldnames else None)
                id_col = next((h for h in headers if h in ["prompt_id", "id", "index", "clip_id"]), None)

                for idx, row in enumerate(reader):
                    sentence = row.get(text_col, "").strip() if text_col else ""
                    pid = row.get(id_col, "").strip() if id_col else f"PROMPT_{idx+1:06d}"
                    if sentence:
                        parsed.append({"prompt_id": pid, "sentence": sentence})

            if not parsed:
                messagebox.showerror("CSV Error", "No prompt sentences found in the selected CSV.")
                return

            self.prompts = parsed
            self.current_index = 0
            self._show_current_prompt()
            self._update_stats()

        except Exception as e:
            messagebox.showerror("Error Reading CSV", str(e))

    def _load_existing_metadata(self):
        import csv
        if not self.metadata_file.exists():
            return
        try:
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = row.get("prompt_id")
                    if pid:
                        self.recordings_map[pid] = row
            self._update_stats()
        except Exception as e:
            print(f"Metadata load warning: {e}")

    # -------------------------------------------------------------
    # PROMPT NAVIGATION & DISPLAY
    # -------------------------------------------------------------

    def _show_current_prompt(self):
        if not self.prompts:
            return
        cur = self.prompts[self.current_index]
        self.prompt_id_lbl.configure(text=f"ID: {cur['prompt_id']}")
        self.prompt_text_lbl.configure(text=cur["sentence"])
        self.progress_lbl.configure(text=f"Prompt {self.current_index + 1} of {len(self.prompts)} | {len(self.recordings_map)} Recorded")

        self.review_frame.pack_forget()
        self.override_btn.pack_forget()

        rec = self.recordings_map.get(cur["prompt_id"])
        if rec:
            q_flag = rec.get("quality_flag", "pass")
            if q_flag != "pass":
                self.status_tag_lbl.configure(text=f"⚠️ Flagged: {q_flag}", fg="#92400E")
            else:
                self.status_tag_lbl.configure(text="✓ Recorded (Pass)", fg="#166534")
            self.review_lbl.configure(text=f"✓ Recorded Take ({rec.get('duration_seconds', '-')}s)")
            self.review_frame.pack(fill=tk.X, pady=(0, 10))
        else:
            self.status_tag_lbl.configure(text="")

    def _update_stats(self):
        count = len(self.recordings_map)
        total = len(self.prompts)
        self.progress_lbl.configure(text=f"Prompt {self.current_index + 1} of {total} | {count} Recorded")
        self.export_btn.configure(state=tk.NORMAL if count > 0 else tk.DISABLED)

    def next_prompt(self):
        if self.is_recording:
            self.stop_recording()
        if self.current_index < len(self.prompts) - 1:
            self.current_index += 1
            self._show_current_prompt()

    def prev_prompt(self):
        if self.is_recording:
            self.stop_recording()
        if self.current_index > 0:
            self.current_index -= 1
            self._show_current_prompt()

    def _on_spacebar(self, event):
        if not self.is_external_mic:
            messagebox.showwarning("Microphone Blocked", "Recording is disabled because an internal laptop microphone is active. Please connect an external USB mic.")
            return
        self.toggle_record()

    # -------------------------------------------------------------
    # AUDIO RECORDING ENGINE
    # -------------------------------------------------------------

    def toggle_record(self):
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if not self.is_external_mic:
            messagebox.showwarning("External Microphone Required", "Cannot record with internal microphone. Please connect a USB microphone.")
            return

        if not self.prompts:
            messagebox.showinfo("No Prompts", "Please load a CSV prompts file first.")
            return

        self.is_recording = True
        self.recorded_chunks = []
        self.current_clip_clipped = False
        self.rec_start_time = time.time()
        self.pending_take = None

        self.rec_btn.configure(text="■ STOP", bg="#0F172A")
        self.review_frame.pack_forget()

        def audio_callback(indata, frames, time_info, status):
            if not self.is_recording:
                return
            chunk = indata.copy()
            self.audio_queue.put(chunk)

        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                device=self.selected_device_id,
                callback=audio_callback
            )
            self.stream.start()
        except Exception as e:
            self.is_recording = False
            self.rec_btn.configure(text="● REC", bg="#DC2626")
            messagebox.showerror("Audio Hardware Error", f"Could not start microphone stream: {e}")
            return

        self._meter_loop()
        self._timer_loop()

    def _meter_loop(self):
        if not self.is_recording:
            self.meter_canvas.delete("all")
            return

        # Empty queue and process latest levels
        latest_peak = 0
        while not self.audio_queue.empty():
            chunk = self.audio_queue.get_nowait()
            self.recorded_chunks.append(chunk)
            peak = float(np.max(np.abs(chunk)))
            if peak > latest_peak:
                latest_peak = peak
            if peak >= MAX_PEAK_THRESHOLD:
                self.current_clip_clipped = True

        # Render meter
        self.meter_canvas.delete("all")
        width = self.meter_canvas.winfo_width()
        meter_w = int(min(1.0, latest_peak) * width)
        color = "#DC2626" if self.current_clip_clipped or latest_peak >= 0.9 else "#16A34A"
        self.meter_canvas.create_rectangle(0, 0, meter_w, 14, fill=color, outline="")

        self.root.after(40, self._meter_loop)

    def _timer_loop(self):
        if not self.is_recording:
            self.timer_lbl.configure(text="00:00")
            return
        elapsed = int(time.time() - self.rec_start_time)
        m = elapsed // 60
        s = elapsed % 60
        self.timer_lbl.configure(text=f"{m:02d}:{s:02d}")
        self.root.after(250, self._timer_loop)

    def stop_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        self.rec_btn.configure(text="● REC", bg="#DC2626")
        self.meter_canvas.delete("all")

        dur = time.time() - self.rec_start_time
        if dur < 0.8:
            messagebox.showinfo("Take Discarded", "Recording was too short (< 0.8s) and was discarded.")
            return

        if not self.recorded_chunks:
            return

        audio_data = np.concatenate(self.recorded_chunks, axis=0).flatten()

        # Quality Audit
        self._audit_and_save_take(audio_data, dur)

    # -------------------------------------------------------------
    # QUALITY AUDIT & USER OVERRIDE WORKFLOW
    # -------------------------------------------------------------

    def _audit_and_save_take(self, audio_data, duration_sec):
        # 1. Clipping Check
        peak = float(np.max(np.abs(audio_data)))
        if self.current_clip_clipped or peak >= MAX_PEAK_THRESHOLD:
            self._trigger_quality_warning(
                audio_data, duration_sec, peak, "needs_review_clipped",
                "Audio Too Loud / Clipped Distortion",
                f"The signal peaked too high ({peak:.2f}) and distorted.\n\nPlease step back to 15–20 cm or ask the sound technician to lower the mixer gain."
            )
            return

        # 2. Too Quiet / Whispering Check
        if peak < MIN_PEAK_THRESHOLD:
            messagebox.showwarning("Take Too Quiet", f"The recorded take was too quiet (peak: {peak:.2f}). Please speak with confident, natural projection at 15–20 cm from the microphone.")
            return

        # 3. Acoustic Vocal Activity & Noise Detection
        vad = self._detect_vocals_and_noise(audio_data, self.sample_rate)
        if vad["status"] == "NO_VOCALS":
            self._trigger_quality_warning(
                audio_data, duration_sec, peak, "needs_review_no_vocals",
                "No Human Voice Detected",
                f"No clear vocal speech was detected in this take ({vad['voiced_sec']}s voiced sound).\n\nDid you speak clearly into the microphone?"
            )
            return

        if vad["status"] == "NOISY":
            self._trigger_quality_warning(
                audio_data, duration_sec, peak, "needs_review_noisy",
                "High Background Noise Detected",
                f"Ambient room noise is high (Estimated SNR: {vad['snr']:.1f} dB).\n\nPlease check for loud room noise, traffic, or generator rumble."
            )
            return

        # 4. Duration Check
        if duration_sec < MIN_DURATION_SEC:
            self._trigger_quality_warning(
                audio_data, duration_sec, peak, "needs_review_too_short",
                "Take Unusually Short",
                f"This take is only {duration_sec:.1f} seconds. Did you finish reading the full prompt sentence?"
            )
            return

        if duration_sec > MAX_DURATION_SEC:
            self._trigger_quality_warning(
                audio_data, duration_sec, peak, "needs_review_too_long",
                "Take Unusually Long",
                f"This take is {duration_sec:.1f} seconds. Speech models perform best with concise takes under 15 seconds."
            )
            return

        # Passed all checks!
        self._commit_take(audio_data, duration_sec, "pass")

    def _trigger_quality_warning(self, audio_data, duration_sec, peak, flag, title, message):
        self.pending_take = {
            "audio": audio_data,
            "duration": duration_sec,
            "flag": flag,
            "title": title,
            "message": message
        }

        # Show review row with override button visible
        self.review_lbl.configure(text=f"⚠️ {title} ({duration_sec:.1f}s)")
        self.override_btn.pack(side=tk.RIGHT, padx=8)
        self.review_frame.pack(fill=tk.X, pady=(0, 10))

        # Play audio back so user hears the issue immediately
        sd.play(audio_data, self.sample_rate)

        messagebox.showwarning(f"Quality Alert: {title}", f"{message}\n\nYou can re-record, or click 'Keep & Mark for Review' to keep this take.")

    def confirm_override_take(self):
        if not self.pending_take:
            return
        take = self.pending_take
        self._commit_take(take["audio"], take["duration"], take["flag"])
        self.pending_take = None
        self.override_btn.pack_forget()

    def _commit_take(self, audio_data, duration_sec, quality_flag):
        cur = self.prompts[self.current_index]
        pid = cur["prompt_id"]
        filename = f"{pid}.wav"
        filepath = self.wavs_dir / filename

        # Write 16-bit PCM WAV to disk
        sf.write(str(filepath), audio_data, self.sample_rate, subtype="PCM_16")

        record = {
            "audio_filename": filename,
            "prompt_id": pid,
            "sentence": cur["sentence"],
            "duration_seconds": f"{duration_sec:.2f}",
            "sample_rate": str(self.sample_rate),
            "quality_flag": quality_flag,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "volunteer_station": self.station_entry.get().strip() or "station"
        }

        self.recordings_map[pid] = record
        self._append_metadata_record(record)
        self._show_current_prompt()
        self._update_stats()

    def _append_metadata_record(self, record):
        import csv
        file_exists = self.metadata_file.exists()
        fieldnames = ["audio_filename", "prompt_id", "sentence", "duration_seconds", "sample_rate", "quality_flag", "timestamp", "volunteer_station"]

        # Read existing to avoid duplicate lines for same prompt
        rows = {}
        if file_exists:
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    rows[r["prompt_id"]] = r

        rows[record["prompt_id"]] = record

        with open(self.metadata_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows.values():
                writer.writerow(r)

    def play_current_take(self):
        cur = self.prompts[self.current_index]
        pid = cur["prompt_id"]
        filepath = self.wavs_dir / f"{pid}.wav"
        if filepath.exists():
            data, sr = sf.read(str(filepath))
            sd.play(data, sr)
        elif self.pending_take:
            sd.play(self.pending_take["audio"], self.sample_rate)

    def re_record_prompt(self):
        try:
            sd.stop()
        except Exception:
            pass
        self.pending_take = None
        self.override_btn.pack_forget()
        self.review_frame.pack_forget()
        self.toggle_record()

    # -------------------------------------------------------------
    # ACOUSTIC VOCAL HARMONICITY & NOISE DETECTOR
    # -------------------------------------------------------------

    def _detect_vocals_and_noise(self, audio, sample_rate):
        frame_size = int(sample_rate * 0.030) # 30ms frame
        hop_size = int(sample_rate * 0.015)   # 15ms hop
        min_lag = int(sample_rate / 350)      # 350 Hz pitch ceiling
        max_lag = int(sample_rate / 75)       # 75 Hz pitch floor

        voiced_frames = 0
        total_frames = 0
        frame_rms_list = []

        for i in range(0, len(audio) - frame_size, hop_size):
            frame = audio[i:i + frame_size]
            total_frames += 1
            rms = np.sqrt(np.mean(frame ** 2))
            frame_rms_list.append(rms)

            if rms < 0.015:
                continue

            frame_centered = frame - np.mean(frame)
            norm = np.sum(frame_centered ** 2)
            if norm < 1e-6:
                continue

            corr = np.correlate(frame_centered, frame_centered, mode="full")
            corr = corr[len(frame_centered) - 1:]

            pitch_peak = np.max(corr[min_lag:max_lag]) / norm
            if pitch_peak > 0.42:
                voiced_frames += 1

        if not frame_rms_list:
            return {"status": "NO_VOCALS", "voiced_sec": 0, "snr": 0}

        frame_rms_sorted = sorted(frame_rms_list)
        noise_floor_rms = np.mean(frame_rms_sorted[:max(1, int(len(frame_rms_sorted) * 0.20))])
        speech_rms = np.mean(frame_rms_sorted[int(len(frame_rms_sorted) * 0.80):])

        snr = 20 * np.log10(max(speech_rms, 1e-5) / max(noise_floor_rms, 1e-5))
        voiced_sec = (voiced_frames * hop_size) / sample_rate

        if voiced_frames < 14 or voiced_sec < 0.40:
            return {"status": "NO_VOCALS", "voiced_sec": voiced_sec, "snr": snr}
        elif snr < 13.5 or noise_floor_rms > 0.038:
            return {"status": "NOISY", "voiced_sec": voiced_sec, "snr": snr}
        else:
            return {"status": "PASS", "voiced_sec": voiced_sec, "snr": snr}

    # -------------------------------------------------------------
    # ONE-CLICK ZIP EXPORT
    # -------------------------------------------------------------

    def export_zip(self):
        if not self.recordings_map:
            messagebox.showinfo("Export", "No recordings available to export yet.")
            return

        station = re.sub(r'[^a-zA-Z0-9_-]', '_', self.station_entry.get().strip() or "station")
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        default_name = f"speech_batch_{station}_{date_str}_{len(self.recordings_map)}clips.zip"

        save_path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("ZIP Archive", "*.zip")]
        )
        if not save_path:
            return

        try:
            with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Add metadata
                if self.metadata_file.exists():
                    zipf.write(str(self.metadata_file), arcname="metadata.csv")

                # Add all WAVs
                for rec in self.recordings_map.values():
                    wav_file = self.wavs_dir / rec["audio_filename"]
                    if wav_file.exists():
                        zipf.write(str(wav_file), arcname=f"wavs/{rec['audio_filename']}")

            messagebox.showinfo("Export Successful", f"Exported {len(self.recordings_map)} audio takes to:\n{save_path}")

        except Exception as e:
            messagebox.showerror("Export Failed", str(e))


if __name__ == "__main__":
    root = tk.Tk()
    app = SpeechRecorderApp(root)
    root.mainloop()
