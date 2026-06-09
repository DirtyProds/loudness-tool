#!/usr/bin/env python3
"""LoudnessNorm Web — stdlib-only backend wrapping ffmpeg/ffprobe.

No external Python dependencies (no Flask, no tkinter). Serves a single-page
web UI and exposes a small JSON API:

    POST /api/analyze   raw WAV body + X-Filename header  -> {id, info, measured}
    POST /api/render?id&lufs&tp                           -> starts background job
    GET  /api/progress?id                                 -> {status, progress}
    GET  /api/download?id                                 -> normalized .wav
"""

import json
import os
import re
import shutil
import sys
import subprocess
import tempfile
import threading
import urllib.parse
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
HERE = Path(__file__).resolve().parent


def _fmt_num(v: float) -> str:
    return f"{v:g}"


# ── ffmpeg helpers (ported from the tkinter app) ──────────────────────────────

def _find_bin(name: str) -> str:
    for d in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    try:
        r = subprocess.run(["which", name], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return name


FFMPEG = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")


def get_audio_info(path: Path) -> dict:
    cmd = [FFPROBE, "-v", "quiet", "-print_format", "json",
           "-show_streams", "-show_format", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(r.stdout)
    fmt = data.get("format", {})
    audio = next((s for s in data.get("streams", [])
                  if s.get("codec_type") == "audio"), {})
    bps = audio.get("bits_per_raw_sample") or audio.get("bits_per_coded_sample") or 24
    channels = int(audio.get("channels", 2))
    layout = audio.get("channel_layout", "")
    return {
        "duration":            float(fmt.get("duration", 0)),
        "channels":            channels,
        "channel_layout":      layout,
        "channels_list":       channel_labels(channels, layout),
        "sample_rate":         audio.get("sample_rate", "48000"),
        "codec_name":          audio.get("codec_name", "pcm_s24le"),
        "bits_per_raw_sample": int(bps),
    }


# ── Channel layout → friendly labels ──────────────────────────────────────────

# Canonical ffmpeg channel order for the common layouts.
_LAYOUT_TOKENS = {
    "mono":       ["FC"],
    "stereo":     ["FL", "FR"],
    "2.1":        ["FL", "FR", "LFE"],
    "3.0":        ["FL", "FR", "FC"],
    "3.0(back)":  ["FL", "FR", "BC"],
    "4.0":        ["FL", "FR", "FC", "BC"],
    "quad":       ["FL", "FR", "BL", "BR"],
    "quad(side)": ["FL", "FR", "SL", "SR"],
    "5.0":        ["FL", "FR", "FC", "BL", "BR"],
    "5.0(side)":  ["FL", "FR", "FC", "SL", "SR"],
    "5.1":        ["FL", "FR", "FC", "LFE", "BL", "BR"],
    "5.1(side)":  ["FL", "FR", "FC", "LFE", "SL", "SR"],
    "6.1":        ["FL", "FR", "FC", "LFE", "BC", "SL", "SR"],
    "7.1":        ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"],
    "7.1(wide)":  ["FL", "FR", "FC", "LFE", "BL", "BR", "FLC", "FRC"],
}

# ffmpeg channel token -> short label shown in the UI.
_TOKEN_LABEL = {
    "FL": "L", "FR": "R", "FC": "C", "LFE": "LFE",
    "BL": "Ls", "BR": "Rs", "SL": "Ls", "SR": "Rs",
    "BC": "Cs", "FLC": "Lc", "FRC": "Rc",
}


def channel_labels(channels: int, layout: str) -> list:
    """Return [{index, label, token}] for each channel of the file."""
    tokens = _LAYOUT_TOKENS.get(layout)
    if not tokens or len(tokens) != channels:
        if channels == 1:
            return [{"index": 0, "label": "Mono", "token": "c0"}]
        if channels == 2:
            return [{"index": 0, "label": "L", "token": "c0"},
                    {"index": 1, "label": "R", "token": "c1"}]
        # Unknown / mismatched layout — fall back to generic numbering.
        return [{"index": i, "label": f"Canal {i + 1}", "token": f"c{i}"}
                for i in range(channels)]
    labels = [_TOKEN_LABEL.get(t, t) for t in tokens]
    # Disambiguate any repeated short labels (e.g. 7.1 has BL/SL both -> Ls).
    seen = {}
    for i, lab in enumerate(labels):
        if labels.count(lab) > 1:
            seen[lab] = seen.get(lab, 0) + 1
            labels[i] = f"{lab}{seen[lab]}"
    return [{"index": i, "label": labels[i], "token": tokens[i]}
            for i in range(channels)]


def _wav_codec(bits: int) -> str:
    if bits >= 32:
        return "pcm_s32le"
    if bits >= 24:
        return "pcm_s24le"
    return "pcm_s16le"


def analyze_lufs(path: Path, channel: int = None) -> dict:
    # When a channel index is given, isolate it to mono before measuring so
    # loudnorm reports that single channel's loudness instead of the full mix.
    pre = f"pan=mono|c0=c{channel}," if channel is not None else ""
    cmd = [FFMPEG, "-i", str(path),
           "-filter:a", pre + "loudnorm=I=-23:TP=-1:LRA=11:print_format=json",
           "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r'\{\s*"input_i".*?\}', r.stderr, re.DOTALL)
    if not m:
        raise ValueError(
            "No se pudo parsear la salida de loudnorm. "
            "Verifica que el archivo sea un WAV válido.\n\n" + r.stderr[-1500:]
        )
    return json.loads(m.group())


def _run_ffmpeg(cmd: list, dur: float, progress_cb=None) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
    for line in proc.stdout:
        if progress_cb and dur > 0:
            m = time_re.search(line)
            if m:
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                progress_cb(min(t / dur, 0.99))
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg finalizó con código {proc.returncode}")


def normalize_audio(in_path: Path, out_path: Path,
                    target_lufs: float, target_tp: float,
                    measured: dict, progress_cb=None) -> None:
    """Whole-mix normalization via loudnorm's two-pass linear mode."""
    info = get_audio_info(in_path)
    codec = _wav_codec(info["bits_per_raw_sample"])
    sr = str(info["sample_rate"])  # loudnorm upsamples to 192k; restore source rate

    flt = (
        f"loudnorm=I={target_lufs}:TP={target_tp}:LRA=11"
        f":measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}"
        f":linear=true:print_format=summary"
    )
    cmd = [FFMPEG, "-i", str(in_path),
           "-filter:a", flt, "-c:a", codec, "-ar", sr,
           str(out_path), "-y"]
    _run_ffmpeg(cmd, info["duration"], progress_cb)


def render_gain(in_path: Path, out_path: Path, gain_db: float,
                progress_cb=None) -> None:
    """Apply a fixed gain to every channel of the full mix (used when the
    target references a single channel's loudness)."""
    info = get_audio_info(in_path)
    codec = _wav_codec(info["bits_per_raw_sample"])
    sr = str(info["sample_rate"])
    cmd = [FFMPEG, "-i", str(in_path),
           "-filter:a", f"volume={gain_db:.4f}dB", "-c:a", codec, "-ar", sr,
           str(out_path), "-y"]
    _run_ffmpeg(cmd, info["duration"], progress_cb)


def split_to_mono_zip(in_path: Path, zip_path: Path, stem: str,
                      channels_list: list, codec: str, sr: str,
                      duration: float, progress_cb=None) -> None:
    """Extract each channel of a WAV to a mono file and pack them in a ZIP."""
    n = len(channels_list)
    tmp_files = []
    try:
        for idx, ch in enumerate(channels_list):
            mono_path = zip_path.parent / f"{stem}_{ch['label']}.wav"
            tmp_files.append(mono_path)
            cmd = [FFMPEG, "-i", str(in_path),
                   "-filter:a", f"pan=mono|c0=c{ch['index']}",
                   "-c:a", codec, "-ar", sr,
                   str(mono_path), "-y"]
            sub_cb = None
            if progress_cb:
                base, step = idx / n, 1.0 / n
                sub_cb = lambda f, b=base, s=step: progress_cb(b + f * s)
            _run_ffmpeg(cmd, duration, sub_cb)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for p in tmp_files:
                zf.write(p, p.name)
    finally:
        for p in tmp_files:
            p.unlink(missing_ok=True)


# ── Session store ─────────────────────────────────────────────────────────────

TMPDIR = Path(tempfile.mkdtemp(prefix="loudnessnorm_"))
SESSIONS: dict[str, dict] = {}
_LOCK = threading.Lock()


# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "LoudnessNorm/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")

    # -- helpers --
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body_to_file(self, dst: Path) -> int:
        length = int(self.headers.get("Content-Length", 0))
        written = 0
        with open(dst, "wb") as f:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 16, remaining))
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
                remaining -= len(chunk)
        return written

    # -- GET --
    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            if path in ("/", "/index.html"):
                self._serve_static("index.html", "text/html; charset=utf-8")
            elif path == "/api/health":
                self._json({"ok": True})
            elif path == "/api/progress":
                self._handle_progress(qs)
            elif path == "/api/download":
                self._handle_download(qs)
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._safe_500(exc)

    def _serve_static(self, name: str, ctype: str):
        fp = HERE / name
        if not fp.is_file():
            self.send_error(404)
            return
        data = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_progress(self, qs):
        fid = (qs.get("id") or [""])[0]
        sess = SESSIONS.get(fid)
        if not sess:
            self._json({"error": "sesión no encontrada"}, 404)
            return
        self._json({
            "status":   sess["status"],
            "progress": round(sess["progress"], 1),
            "error":    sess["error"],
            "ready":    sess["out"] is not None,
        })

    def _handle_download(self, qs):
        fid = (qs.get("id") or [""])[0]
        sess = SESSIONS.get(fid)
        if not sess or not sess["out"] or not Path(sess["out"]).is_file():
            self.send_error(404)
            return
        out = Path(sess["out"])
        dl_name = sess.get("dl_name") or Path(sess["out"]).name
        dl_type = sess.get("dl_type", "audio/wav")
        data = out.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", dl_type)
        self.send_header("Content-Disposition",
                         f'attachment; filename="{dl_name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- POST --
    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            if path == "/api/analyze":
                self._handle_analyze()
            elif path == "/api/reanalyze":
                self._handle_reanalyze(qs)
            elif path == "/api/render":
                self._handle_render(qs)
            else:
                self.send_error(404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._safe_500(exc)

    def _safe_500(self, exc: Exception):
        print(f"  ! error: {exc!r}")
        try:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        except Exception:
            pass

    @staticmethod
    def _parse_channel(qs) -> int:
        raw = (qs.get("channel") or ["mix"])[0]
        if raw in ("", "mix", "all"):
            return None
        return int(raw)

    def _handle_analyze(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        fid = uuid.uuid4().hex
        raw_name = self.headers.get("X-Filename", "audio.wav")
        name = urllib.parse.unquote(raw_name)
        ext = Path(name).suffix or ".wav"
        src = TMPDIR / (fid + ext)
        try:
            written = self._read_body_to_file(src)
            if written == 0:
                raise ValueError("No se recibió ningún dato del archivo (subida vacía).")
            channel = self._parse_channel(qs)
            info = get_audio_info(src)
            # Always measure the full mix once: its true peak protects the
            # render, and it is the default display scope.
            mix_measured = analyze_lufs(src)
            if channel is not None:
                measured = analyze_lufs(src, channel)
            else:
                measured = mix_measured
        except Exception as exc:
            self._json({"error": str(exc)}, 400)
            return
        with _LOCK:
            SESSIONS[fid] = {
                "path": src, "name": name, "info": info,
                "mix_measured": mix_measured, "mix_tp": float(mix_measured["input_tp"]),
                "measured": measured, "channel": channel,
                "progress": 0.0, "status": "idle",
                "out": None, "error": None,
            }
        self._json({"id": fid, "name": name, "info": info,
                    "measured": measured, "channel": channel})

    def _handle_reanalyze(self, qs):
        fid = (qs.get("id") or [""])[0]
        sess = SESSIONS.get(fid)
        if not sess:
            self._json({"error": "sesión no encontrada"}, 404)
            return
        try:
            channel = self._parse_channel(qs)
            if channel is not None:
                measured = analyze_lufs(sess["path"], channel)
            else:
                measured = sess["mix_measured"]
        except Exception as exc:
            self._json({"error": str(exc)}, 400)
            return
        sess["measured"] = measured
        sess["channel"] = channel
        self._json({"measured": measured, "channel": channel})

    def _handle_render(self, qs):
        fid = (qs.get("id") or [""])[0]
        sess = SESSIONS.get(fid)
        if not sess:
            self._json({"error": "sesión no encontrada"}, 404)
            return
        try:
            lufs = float((qs.get("lufs") or [""])[0])
            tp = float((qs.get("tp") or [""])[0])
        except ValueError:
            self._json({"error": "Valores LUFS/True Peak inválidos"}, 400)
            return
        if not (-70 <= lufs <= 0):
            self._json({"error": "El objetivo LUFS debe estar entre -70 y 0."}, 400)
            return
        if not (-30 <= tp <= 0):
            self._json({"error": "El True Peak debe estar entre -30 y 0."}, 400)
            return

        mode = (qs.get("mode") or ["interleaved"])[0]
        dl_stem = f"{Path(sess['name']).stem}_{_fmt_num(lufs)}lufs_{_fmt_num(tp)}tp"
        if mode == "multimono":
            dl_name, dl_type = dl_stem + ".zip", "application/zip"
        else:
            dl_name, dl_type = dl_stem + ".wav", "audio/wav"
        out = TMPDIR / dl_name
        sess["dl_name"] = dl_name
        sess["dl_type"] = dl_type
        sess["status"] = "running"
        sess["progress"] = 0.0
        sess["out"] = None
        sess["error"] = None
        cb = lambda f: sess.__setitem__("progress", f * 100)

        channel = sess.get("channel")
        resp = {"ok": True, "channel": channel}

        if channel is None:
            # Whole-mix path: loudnorm linear, unchanged proven behaviour.
            render_measured = dict(sess["measured"])
            render_measured["input_tp"] = sess["mix_tp"]
            def core(dest, pcb):
                normalize_audio(sess["path"], dest, lufs, tp, render_measured, pcb)
        else:
            # Channel-referenced path: shift the whole mix so the analysed
            # channel reaches the target, clamped so the mix true peak never
            # exceeds the ceiling (a boost can't push the mix into clipping).
            measured_i = float(sess["measured"]["input_i"])
            desired_gain = lufs - measured_i
            headroom = tp - sess["mix_tp"]          # max gain before mix peak = ceiling
            gain = min(desired_gain, headroom)
            clamped = gain < desired_gain - 1e-6
            resp.update({"gain": round(gain, 2),
                         "desired_gain": round(desired_gain, 2),
                         "clamped": clamped})
            def core(dest, pcb):
                render_gain(sess["path"], dest, gain, pcb)

        if mode == "multimono":
            tmp_iv = TMPDIR / (dl_stem + "_tmp.wav")
            info = sess["info"]
            def work():
                try:
                    core(tmp_iv, lambda f: cb(f * 0.8))
                    split_to_mono_zip(
                        tmp_iv, out, dl_stem,
                        info["channels_list"],
                        _wav_codec(info["bits_per_raw_sample"]),
                        str(info["sample_rate"]),
                        info["duration"],
                        lambda f: cb(0.8 + f * 0.2),
                    )
                    sess["out"] = str(out)
                    sess["progress"] = 100.0
                    sess["status"] = "done"
                except Exception as exc:
                    sess["error"] = str(exc)
                    sess["status"] = "error"
                finally:
                    tmp_iv.unlink(missing_ok=True)
        else:
            def work():
                try:
                    core(out, cb)
                    sess["out"] = str(out)
                    sess["progress"] = 100.0
                    sess["status"] = "done"
                except Exception as exc:
                    sess["error"] = str(exc)
                    sess["status"] = "error"

        threading.Thread(target=work, daemon=True).start()
        self._json(resp)


def _check_ffmpeg():
    for label, binp in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)):
        try:
            subprocess.run([binp, "-version"], capture_output=True, check=True)
        except Exception:
            print(f"⚠️  No se encontró {label!r} (probado: {binp}).")
            print("    Instálalo con:  brew install ffmpeg")
            return False
    return True


def _bind(host):
    last = None
    for port in range(PORT, PORT + 10):
        try:
            return ThreadingHTTPServer((host, port), Handler), port
        except OSError as exc:
            last = exc
            print(f"   puerto {port} ocupado, probando {port + 1}…")
    raise last


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    if not _check_ffmpeg():
        print("    (La app arrancará igual, pero el análisis fallará sin ffmpeg.)\n")

    httpd, port = _bind(HOST)
    url = f"http://{HOST}:{port}/"
    print("─" * 52)
    print(f"  LoudnessNorm Web  →  {url}")
    print(f"  ffmpeg:  {FFMPEG}")
    print(f"  ffprobe: {FFPROBE}")
    print(f"  temp:    {TMPDIR}")
    print("  Ctrl+C para detener.  Mantén esta ventana abierta.")
    print("─" * 52)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo…")
    finally:
        httpd.server_close()
        shutil.rmtree(TMPDIR, ignore_errors=True)


if __name__ == "__main__":
    main()
