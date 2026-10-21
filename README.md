# LoudnessNorm

A local web application for professional loudness normalization of WAV audio files. Upload a file, pick a delivery standard preset (or set custom targets), choose an export mode, and download a normalized WAV — all powered by ffmpeg, running entirely on your machine with no cloud uploads and no Python packages beyond the standard library.

---

## Features

- **Drag-and-drop analysis** — drop any WAV file to instantly measure Integrated LUFS, LU Range, and True Peak
- **Per-channel scope** — analyze and normalize the full mix or a single channel (L, R, C, LFE, Ls, Rs, …)
- **Platform presets** — one-click targets for Spotify, Apple Music, Netflix, EBU R128, CALM Act, and dialogue standards
- **Custom targets** — enter any Integrated LUFS (−70 to 0) and True Peak (−30 to 0 dBTP)
- **Two export modes** — interleaved multi-channel WAV or per-channel mono WAVs in a ZIP
- **Two-pass render** — measurement pass via loudnorm, gain pass via linear volume + alimiter safety net
- **Real-time progress bar** — rendered in a background thread; the UI polls and auto-downloads when done
- **Bit-depth and sample-rate preservation** — output codec matches the source (16/24/32-bit PCM)
- **Zero Python dependencies** — backend runs on the standard library only

---

## Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| Python | 3.8+ | Standard library only — no pip installs required |
| ffmpeg + ffprobe | Any recent build | Must be on `$PATH` or in `/opt/homebrew/bin` / `/usr/local/bin` |
| Node.js | 18+ | Only required to run the Playwright test suite |

**Install ffmpeg on macOS:**

```bash
brew install ffmpeg
```

**Install ffmpeg on Ubuntu/Debian:**

```bash
sudo apt install ffmpeg
```

---

## Installation

```bash
git clone https://github.com/DirtyProds/loudness-tool.git
cd loudness-tool
```

No Python packages to install. The backend uses only stdlib modules (`http.server`, `subprocess`, `threading`, `zipfile`, etc.).

To run the Playwright tests, install the Node dependencies and the Chromium browser used by Playwright:

```bash
npm install
npx playwright install chromium
```

---

## Usage

### Start the app

```bash
./run.sh
```

Or directly:

```bash
python3 server.py
```

The server starts at `http://127.0.0.1:8765` and opens the UI in your default browser automatically. If port 8765 is busy, it tries the next free port (8766–8774) and prints the URL it ends up using. Keep the terminal window open while using the app.

### Workflow

1. **Drop a WAV file** onto the upload zone, or click to browse.
2. **Review the analysis** — Integrated LUFS, LU Range, and True Peak are measured automatically.
3. *(Optional)* **Change the analysis scope** — select a specific channel from the dropdown to measure and target its loudness independently (useful for dialogue normalization in surround files).
4. **Pick a preset** or enter custom LUFS and True Peak values.
5. **Choose an export mode** (Interleaved or Multi-mono).
6. **Click RENDER** — a progress bar tracks the job and the file downloads automatically when done.

---

## Loudness Presets

### Program (full mix)

| Preset | Integrated LUFS | True Peak |
|---|---|---|
| Spotify | −14 LUFS | −1 dBTP |
| Apple Music | −16 LUFS | −1 dBTP |
| Netflix | −27 LUFS | −2 dBTP |
| EBU R128 | −23 LUFS | −1 dBTP |
| CALM Act | −24 LUFS | −2 dBTP |

### Dialogue (LKFS — single-channel reference)

| Preset | Integrated LKFS | True Peak |
|---|---|---|
| Netflix | −27 LKFS | −2 dBTP |
| ATSC A/85 | −24 LKFS | −2 dBTP |
| EBU R128 | −23 LKFS | −1 dBTP |
| AMC TV | −24 LKFS | −2 dBTP |
| Podcast | −16 LKFS | −1 dBTP |

All preset values can be overridden with the custom target fields.

---

## Export Modes

### Interleaved

The default. Outputs a single multi-channel WAV file with all channels interleaved — the same layout as the source. Compatible with every DAW and player.

### Multi-mono

Splits each channel into its own mono WAV file and packages them in a ZIP archive. File names include the channel label (e.g. `track_-14lufs_-1tp_L.wav`, `…_R.wav`, `…_C.wav`). Use this when your delivery spec requires discrete mono files — common in post-production, broadcast, and some streaming deliverables.

---

## Technical Details

### Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, stdlib `http.server` (ThreadingHTTPServer) |
| Frontend | Vanilla HTML/CSS/JS, single file (`index.html`) |
| Audio engine | ffmpeg + ffprobe |
| Tests | Playwright (Node.js) |

### Render pipeline

Rendering uses a **two-pass approach** to achieve a deterministic, LRA-independent gain:

1. **Pass 1 — measurement**: runs ffmpeg's `loudnorm` filter in measurement-only mode (`print_format=json`) to obtain the source's integrated loudness (`input_i`).
2. **Pass 2 — gain**: applies a plain `volume` filter (`gain = target_lufs − input_i`) followed by an `alimiter` safety net set 0.3 dB below the True Peak ceiling. No `loudnorm` in pass 2 — this avoids the unpredictable `target_offset` that loudnorm introduces when the source LRA exceeds the filter's LRA target.

When a single channel is selected as the analysis scope, the gain is clamped so the full-mix True Peak never exceeds the target ceiling, regardless of the per-channel loudness target.

### Channel layout support

The app recognises all standard ffmpeg layouts: mono, stereo, 2.1, 3.0, 4.0, quad, 5.0, 5.1, 5.1(side), 6.1, 7.1, 7.1(wide). Unknown or mismatched layouts fall back to generic channel numbering.

### API endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/analyze` | Upload WAV body; returns LUFS measurements and file metadata |
| `POST` | `/api/reanalyze` | Re-measure an already-uploaded file on a different channel scope |
| `POST` | `/api/render` | Start a background render job |
| `GET` | `/api/progress` | Poll render progress `{status, progress, ready}` |
| `GET` | `/api/download` | Download the normalized file |

---

## Known Limitations

- **WAV only** — MP3, FLAC, AIFF, and other formats are not accepted. Convert to WAV first.
- **Single-user, local tool** — the server is bound to `127.0.0.1` and keeps sessions in memory; restarting the server clears all sessions.
- **Temporary files** — rendered files are stored in a system temp directory and deleted when the server shuts down. Download before closing the terminal.
- **No loudness upward limiting** — when a file is already louder than the target, gain is negative (attenuation). The alimiter only catches True Peak overages; it does not perform dynamic range compression.
- **Surround files and channel-scope mode** — when targeting the loudness of a single channel, the gain applied to the full mix is clamped to keep the mix True Peak within the ceiling. The dialogue channel will reach its target only if headroom allows.

---

## Running the Tests

```bash
# Start the server first (in a separate terminal)
python3 server.py

# Run the Playwright suite
npm test
```

The tests expect the app at `http://localhost:8765`, so make sure nothing else is using that port before starting the server.

Eight tests cover page load, all five program presets, the export mode selector, and the initial render button state.

---

## License

[MIT](LICENSE) © 2026 Daniel Candel

---

## Author

**Daniel Candel** — [github.com/DirtyProds](https://github.com/DirtyProds)
