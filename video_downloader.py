#!/usr/bin/env python3
"""
Universal Video Downloader (GUI)
---------------------------------
A Tkinter front-end for yt-dlp that lets you paste a link from YouTube,
Instagram, and hundreds of other supported sites and download the
video/audio to a folder of your choice.

ffmpeg handling:
- On startup, the app checks if ffmpeg is already installed on your system.
- If not, it automatically downloads a small, portable copy of ffmpeg in
  the background (no admin rights, no manual PATH editing needed) and
  stores it in a local app folder for future runs.
- Once ready, full quality video merging and mp3 audio extraction work
  automatically.

yt-dlp handling:
- On startup (can be disabled in the window), the app upgrades yt-dlp with
  pip, because an outdated yt-dlp is the most common cause of download
  failures.
- Recent yt-dlp versions need a JavaScript runtime for full YouTube support.
  The app uses an installed runtime or downloads a portable Deno copy once.
- Browser cookies can optionally be loaded for login-only sites.
- Your folder, format, quality and cookie choices are remembered in
  ~/.universal_video_downloader/settings.json.

Notes on platform support:
- YouTube, Instagram, Twitter/X, Facebook, TikTok, Vimeo, Reddit, etc. ->
  fully supported via yt-dlp's built-in extractors.
- Terabox / Diskwala and similar cloud-storage "share link" sites are NOT
  officially supported by yt-dlp. The app will still try (best effort),
  but success depends on the site's current structure, login walls, etc.

Only download content you own or have permission/rights to use. Respect
each platform's Terms of Service and copyright law.

Requirements:
    Python 3.11+  (required by current yt-dlp releases)
    pip install -r requirements.txt
    (or: pip install "yt-dlp[default]" --break-system-packages)

Run:
    python video_downloader.py
"""

import importlib.metadata
import importlib.util
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import threading
import urllib.request
import zipfile
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    yt_dlp = None
    YT_DLP_AVAILABLE = False


def _yt_dlp_version():
    try:
        return importlib.metadata.version("yt-dlp")
    except Exception:
        return None


YT_DLP_VERSION = _yt_dlp_version() or "unknown"


APP_VERSION = "1.2.0"

BEST_EFFORT_HOSTS = ["terabox", "diskwala", "1024tera", "teraboxapp"]

APP_DIR = os.path.join(os.path.expanduser("~"), ".universal_video_downloader")
FFMPEG_DIR = os.path.join(APP_DIR, "ffmpeg_bin")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")

DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# Keep background helpers from flashing console windows on Windows
# (relevant when the app is started with pythonw.exe).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.system() == "Windows" else 0

QUALITY_CHOICES = ["best", "1080p", "720p", "480p", "360p"]
COOKIE_CHOICES = ["none", "chrome", "edge", "firefox", "brave", "opera",
                  "vivaldi", "chromium", "safari"]

WINDOWS_FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
LINUX_FFMPEG_URLS = {
    "x86_64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    "amd64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    "aarch64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
    "arm64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
    "armv7l": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-armhf-static.tar.xz",
    "armv6l": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-armhf-static.tar.xz",
}
MAC_FFMPEG_INFO_URL = "https://evermeet.cx/ffmpeg/info/ffmpeg/release"
MAC_FFPROBE_INFO_URL = "https://evermeet.cx/ffmpeg/info/ffprobe/release"
MAC_ARM_PAGE = "https://www.osxexperts.net/"
# Known-good Apple Silicon fallbacks if the page layout ever changes.
MAC_ARM_FFMPEG_FALLBACK = "https://www.osxexperts.net/ffmpeg902arm.zip"
MAC_ARM_FFPROBE_FALLBACK = "https://www.osxexperts.net/ffprobe902arm.zip"

# yt-dlp needs a JavaScript runtime for full YouTube support (EJS).
JS_DIR = os.path.join(APP_DIR, "js_bin")
DENO_DOWNLOAD_BASE = "https://github.com/denoland/deno/releases/latest/download/"
DENO_ARCHIVE_NAMES = {
    ("Windows", "x86_64"): "deno-x86_64-pc-windows-msvc.zip",
    ("Windows", "aarch64"): "deno-aarch64-pc-windows-msvc.zip",
    ("Darwin", "x86_64"): "deno-x86_64-apple-darwin.zip",
    ("Darwin", "aarch64"): "deno-aarch64-apple-darwin.zip",
    ("Linux", "x86_64"): "deno-x86_64-unknown-linux-gnu.zip",
    ("Linux", "aarch64"): "deno-aarch64-unknown-linux-gnu.zip",
}
_deno_download_attempted = False


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except Exception:
        pass


def update_yt_dlp_auto(log_cb):
    """
    Upgrade yt-dlp to the latest version via pip. YouTube (and other sites)
    change frequently, and an outdated yt-dlp is the #1 cause of 403/format
    errors. This runs quietly in the background on every app launch.
    Returns True only if a new version was actually installed.
    """
    if getattr(sys, "frozen", False):
        log_cb("Packaged build detected — skipping yt-dlp auto-update.")
        return False

    before = _yt_dlp_version()
    base_cmd = [
        sys.executable, "-m", "pip", "install", "--upgrade",
        "--disable-pip-version-check", "-q", "yt-dlp[default]",
    ]
    # --break-system-packages is only understood by pip >= 23 and is needed on
    # PEP 668 ("externally managed") Linux/macOS installs. Retry without it so
    # the app still works with older pip versions.
    attempts = [base_cmd + ["--break-system-packages"], base_cmd]
    last_err = ""

    for cmd in attempts:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=180, creationflags=_NO_WINDOW)
        except Exception as e:
            last_err = str(e)
            continue

        if result.returncode == 0:
            after = _yt_dlp_version()
            return bool(after and after != before)

        last_err = (result.stderr or result.stdout or "").strip()[:200]
        if "--break-system-packages" not in cmd:
            break

    log_cb(f"yt-dlp update check failed: {last_err}")
    return False


# ------------------------------------------------------------- ffmpeg utils
def _ffmpeg_exe_name():
    return "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"


def _ffprobe_exe_name():
    return "ffprobe.exe" if platform.system() == "Windows" else "ffprobe"


def find_system_ffmpeg():
    """
    Return path to ffmpeg if both ffmpeg and ffprobe are already on PATH.
    yt-dlp needs ffprobe too (for merging), so a lone ffmpeg is not enough.
    """
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    return ffmpeg if (ffmpeg and ffprobe) else None


def local_ffmpeg_path():
    """
    Return path to our own downloaded copy, if a complete install is present.
    Both ffmpeg and ffprobe are required, otherwise merging would fail later.
    """
    ffmpeg = os.path.join(FFMPEG_DIR, _ffmpeg_exe_name())
    ffprobe = os.path.join(FFMPEG_DIR, _ffprobe_exe_name())
    return ffmpeg if (os.path.isfile(ffmpeg) and os.path.isfile(ffprobe)) else None


def ffmpeg_ready():
    return find_system_ffmpeg() is not None or local_ffmpeg_path() is not None


def ffmpeg_location_for_ydl():
    """
    What to pass as yt-dlp's ffmpeg_location option.
    None means "let yt-dlp find it on PATH itself" (system install).
    A folder path means "use our downloaded copy".
    """
    if find_system_ffmpeg():
        return None
    if local_ffmpeg_path():
        return FFMPEG_DIR
    return None


def _download_with_progress(url, dest_path, progress_cb):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 65536
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                progress_cb(min(100, downloaded / total * 100))


def _fetch_text(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _extract_bins_from_zip(zip_path, dest_dir, wanted):
    """Copy just the wanted executables out of a zip archive."""
    found = set()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename)
            if base in wanted:
                with z.open(info) as src, open(os.path.join(dest_dir, base), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                found.add(base)
    return found


def _resolve_mac_urls(log_cb):
    """
    Return (ffmpeg_zip_url, ffprobe_zip_url) for macOS.

    Apple Silicon gets native builds from osxexperts.net; Intel Macs get
    builds from evermeet.cx. evermeet's old /getrelease/zip endpoints were
    removed (HTTP 410), so the current download URL is looked up through
    its info API instead.
    """
    machine = platform.machine().lower()

    if machine in ("arm64", "aarch64"):
        ff = fp = None
        try:
            html = _fetch_text(MAC_ARM_PAGE)
            ff_versions = [int(v) for v in re.findall(r"/ffmpeg(\d+)arm\.zip", html)]
            fp_versions = [int(v) for v in re.findall(r"/ffprobe(\d+)arm\.zip", html)]
            if ff_versions:
                ff = f"https://www.osxexperts.net/ffmpeg{max(ff_versions)}arm.zip"
            if fp_versions:
                fp = f"https://www.osxexperts.net/ffprobe{max(fp_versions)}arm.zip"
        except Exception as e:
            log_cb(f"Could not read the Apple Silicon download page: {e}")
        if not ff or not fp:
            log_cb("Falling back to known-good Apple Silicon ffmpeg links.")
            ff, fp = MAC_ARM_FFMPEG_FALLBACK, MAC_ARM_FFPROBE_FALLBACK
        return ff, fp

    # Intel Mac (or unknown architecture — evermeet builds run under Rosetta)
    def zip_url(info_url):
        data = json.loads(_fetch_text(info_url))
        return data["download"]["zip"]["url"]

    return zip_url(MAC_FFMPEG_INFO_URL), zip_url(MAC_FFPROBE_INFO_URL)


def download_ffmpeg_auto(progress_cb, log_cb):
    """
    Download a portable ffmpeg build for the current OS into FFMPEG_DIR.
    Raises an exception on failure (caller should catch it).
    """
    system = platform.system()
    os.makedirs(FFMPEG_DIR, exist_ok=True)
    tmp_dir = os.path.join(APP_DIR, "_tmp_ffmpeg_dl")
    # Remove leftovers from an interrupted previous attempt.
    shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        if system == "Windows":
            zip_path = os.path.join(tmp_dir, "ffmpeg.zip")
            log_cb("Downloading ffmpeg for Windows (one-time setup, ~100MB)...")
            _download_with_progress(WINDOWS_FFMPEG_URL, zip_path, progress_cb)
            log_cb("Extracting ffmpeg...")
            found = _extract_bins_from_zip(
                zip_path, FFMPEG_DIR, {"ffmpeg.exe", "ffprobe.exe"})
            missing = {"ffmpeg.exe", "ffprobe.exe"} - found
            if missing:
                raise RuntimeError("Windows download did not contain: "
                                   + ", ".join(sorted(missing)))

        elif system == "Darwin":
            log_cb("Downloading ffmpeg for macOS (one-time setup)...")
            ff_url, fp_url = _resolve_mac_urls(log_cb)
            zip1 = os.path.join(tmp_dir, "ffmpeg_mac.zip")
            _download_with_progress(ff_url, zip1, progress_cb)
            found = _extract_bins_from_zip(zip1, FFMPEG_DIR, {"ffmpeg"})

            log_cb("Downloading ffprobe for macOS...")
            zip2 = os.path.join(tmp_dir, "ffprobe_mac.zip")
            _download_with_progress(fp_url, zip2, progress_cb)
            found |= _extract_bins_from_zip(zip2, FFMPEG_DIR, {"ffprobe"})

            mac_missing = {"ffmpeg", "ffprobe"} - found
            if mac_missing:
                raise RuntimeError("macOS download did not contain: "
                                   + ", ".join(sorted(mac_missing)))
            for exe in ("ffmpeg", "ffprobe"):
                os.chmod(os.path.join(FFMPEG_DIR, exe), 0o755)

            if platform.machine().lower() in ("arm64", "aarch64"):
                # macOS refuses to run unsigned arm64 binaries; ad-hoc signing
                # is enough and does not require a developer certificate.
                for exe in ("ffmpeg", "ffprobe"):
                    exe_path = os.path.join(FFMPEG_DIR, exe)
                    try:
                        subprocess.run(["codesign", "--force", "--sign", "-", exe_path],
                                       capture_output=True, timeout=60,
                                       creationflags=_NO_WINDOW)
                    except Exception as e:
                        log_cb(f"Could not ad-hoc sign {exe}: {e}")

        elif system == "Linux":
            machine = platform.machine().lower()
            url = LINUX_FFMPEG_URLS.get(machine)
            if not url:
                raise RuntimeError(
                    f"No automatic ffmpeg build for Linux/{machine}. "
                    f"Please install ffmpeg with your package manager "
                    f"(e.g. sudo apt install ffmpeg) and restart the app.")
            log_cb(f"Downloading ffmpeg for Linux/{machine} (one-time setup)...")
            tar_path = os.path.join(tmp_dir, "ffmpeg.tar.xz")
            _download_with_progress(url, tar_path, progress_cb)
            log_cb("Extracting ffmpeg...")
            found = set()
            with tarfile.open(tar_path) as t:
                for member in t.getmembers():
                    base = os.path.basename(member.name)
                    if base in ("ffmpeg", "ffprobe") and member.isfile():
                        # Read the member and write it ourselves: TarFile.extract()
                        # is deprecated since Python 3.12 and removed in 3.14.
                        src = t.extractfile(member)
                        if src is None:
                            continue
                        with src, open(os.path.join(FFMPEG_DIR, base), "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        found.add(base)
            missing = {"ffmpeg", "ffprobe"} - found
            if missing:
                raise RuntimeError("Linux download did not contain: "
                                   + ", ".join(sorted(missing)))
            for exe in ("ffmpeg", "ffprobe"):
                os.chmod(os.path.join(FFMPEG_DIR, exe), 0o755)
        else:
            raise RuntimeError(f"Automatic ffmpeg download isn't supported on {system}. "
                                f"Please install ffmpeg manually and ensure it's on PATH.")

        if not local_ffmpeg_path():
            raise RuntimeError("Download finished but ffmpeg/ffprobe were not found afterward.")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ------------------------------------------- JavaScript runtime (YouTube/EJS)
def _deno_exe_name():
    return "deno.exe" if platform.system() == "Windows" else "deno"


def _normalized_arch():
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(machine, machine)


def local_deno_path():
    p = os.path.join(JS_DIR, _deno_exe_name())
    return p if os.path.isfile(p) else None


def _exe_in_scripts_dir(name):
    """Find executables installed by pip into Python's Scripts/bin folder."""
    try:
        scripts = sysconfig.get_path("scripts")
    except Exception:
        return None
    if not scripts:
        return None
    names = [name + ".exe", name] if platform.system() == "Windows" else [name]
    for candidate in names:
        path = os.path.join(scripts, candidate)
        if os.path.isfile(path):
            return path
    return None


def _find_runtime_exe(name):
    return shutil.which(name) or _exe_in_scripts_dir(name)


def _runtime_version(path):
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True,
                                timeout=20, creationflags=_NO_WINDOW)
    except Exception:
        return None
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?",
                      (result.stdout or "") + (result.stderr or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def _version_at_least(version, minimum):
    if not version:
        return False
    padded = tuple(version) + (0,) * (len(minimum) - len(version))
    return padded[:len(minimum)] >= minimum


# Minimum versions yt-dlp can actually use (see yt-dlp's EJS documentation).
JS_RUNTIME_MINIMUMS = {
    "deno": (2, 3, 0),
    "node": (22, 0, 0),
    "bun": (1, 2, 11),
}


def _supported_system_js_runtime():
    """Name of an installed runtime yt-dlp can really use, or None.

    An outdated Node (e.g. 18) is common, and yt-dlp ignores it, so simply
    finding the executable is not enough.
    """
    for name, exe in (("deno", "deno"), ("node", "node"), ("bun", "bun")):
        path = _find_runtime_exe(exe)
        if path and _version_at_least(_runtime_version(path), JS_RUNTIME_MINIMUMS[name]):
            return name
    # QuickJS is rare; if it is installed at all it is almost certainly recent.
    if _find_runtime_exe("qjs"):
        return "quickjs"
    return None


def _has_usable_js_runtime():
    return bool(local_deno_path() or _supported_system_js_runtime())


def _ejs_available():
    """yt-dlp-ejs ships the challenge-solver scripts (installed by [default])."""
    try:
        return importlib.util.find_spec("yt_dlp_ejs") is not None
    except Exception:
        return False


def js_runtime_options():
    """
    yt-dlp option enabling every runtime that might be available. Deno is the
    recommended one and is used from our local copy when present.
    """
    options = {}
    local_deno = local_deno_path()
    options["deno"] = {"path": local_deno} if local_deno else {}
    for key, exe in (("node", "node"), ("bun", "bun"), ("quickjs", "qjs")):
        if _find_runtime_exe(exe):
            options[key] = {}
    return options


def download_deno_auto(log_cb):
    """
    Download a portable Deno binary (one-time) so yt-dlp's YouTube extractor
    can use its JavaScript runtime. Returns the path to deno, or None.
    """
    global _deno_download_attempted
    if _deno_download_attempted:
        return local_deno_path()
    _deno_download_attempted = True

    system = platform.system()
    asset = DENO_ARCHIVE_NAMES.get((system, _normalized_arch()))
    if not asset:
        log_cb(f"No portable Deno build for {system}/{platform.machine()}.")
        return None

    os.makedirs(JS_DIR, exist_ok=True)
    tmp_dir = os.path.join(APP_DIR, "_tmp_deno_dl")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        url = DENO_DOWNLOAD_BASE + asset
        log_cb("Downloading Deno (~40MB, one-time setup) for full YouTube support...")
        zip_path = os.path.join(tmp_dir, "deno.zip")
        logged = [-20]

        def progress_cb(pct):
            if pct - logged[0] >= 20:
                logged[0] = pct
                log_cb(f"Deno download: {pct:.0f}%")

        _download_with_progress(url, zip_path, progress_cb)
        exe = _deno_exe_name()
        if exe not in _extract_bins_from_zip(zip_path, JS_DIR, {exe}):
            raise RuntimeError("Deno archive did not contain the deno executable.")
        if system != "Windows":
            os.chmod(os.path.join(JS_DIR, exe), 0o755)
        log_cb("Deno is ready — full YouTube format support is enabled.")
        return local_deno_path()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------- GUI class
class _YdlLogger:
    """Forward yt-dlp warnings/errors into the app's log panel."""

    def __init__(self, msg_queue):
        self.msg_queue = msg_queue

    def debug(self, msg):
        # yt-dlp sends regular output with a "[debug] " prefix.
        return

    def info(self, msg):
        return

    def warning(self, msg):
        self.msg_queue.put(("log", f"yt-dlp warning: {msg}"))

    def error(self, msg):
        self.msg_queue.put(("log", f"yt-dlp: {msg}"))


class DownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Universal Video Downloader {APP_VERSION}")
        self.root.geometry("660x660")
        self.root.minsize(580, 620)

        settings = load_settings()
        saved_dir = settings.get("download_dir")
        saved_mode = settings.get("mode")
        saved_quality = settings.get("quality")
        saved_cookies = settings.get("cookies")

        self.download_dir = tk.StringVar(
            value=saved_dir if isinstance(saved_dir, str) and saved_dir else DEFAULT_DOWNLOAD_DIR)
        self.url_var = tk.StringVar()
        self.mode_var = tk.StringVar(
            value=saved_mode if saved_mode in ("video", "audio") else "video")
        self.quality_var = tk.StringVar(
            value=saved_quality if saved_quality in QUALITY_CHOICES else "best")
        self.cookies_var = tk.StringVar(
            value=saved_cookies if saved_cookies in COOKIE_CHOICES else "none")
        self.auto_update_var = tk.BooleanVar(value=settings.get("auto_update", True) is not False)

        self.msg_queue = queue.Queue()
        self.is_downloading = False
        self.ffmpeg_setup_done = ffmpeg_ready()
        self.yt_dlp_update_done = False

        self._build_ui()
        self._sync_quality_state()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._focus_url)
        self.root.after(150, self._poll_queue)

        self._log(f"Universal Video Downloader v{APP_VERSION} — Python "
                  f"{platform.python_version()}, yt-dlp {YT_DLP_VERSION}")

        self._begin_yt_dlp_update()

        if not self.ffmpeg_setup_done:
            self._begin_ffmpeg_setup()
        else:
            self.status_var.set("Ready. (ffmpeg detected)")

    # ---------------------------------------------------------- UI LAYOUT
    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}

        families = set(tkfont.families(self.root))

        def pick_font(candidates, fallback):
            for name in candidates:
                if name in families:
                    return name
            return fallback

        ui_font = pick_font(
            ["Segoe UI", "SF Pro Text", "Helvetica Neue", "DejaVu Sans", "Noto Sans"],
            "TkDefaultFont")
        mono_font = pick_font(
            ["Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"],
            "TkFixedFont")

        title = ttk.Label(self.root, text="Universal Video Downloader",
                           font=(ui_font, 16, "bold"))
        title.pack(pady=(14, 0))

        subtitle = ttk.Label(
            self.root,
            text="YouTube • Instagram • Twitter/X • TikTok • Facebook • Vimeo • and more\n"
                 "(Terabox/Diskwala: best-effort, not officially supported)",
            font=(ui_font, 9), foreground="#666", justify="center"
        )
        subtitle.pack(pady=(2, 10))

        url_frame = ttk.Frame(self.root)
        url_frame.pack(fill="x", **pad)
        ttk.Label(url_frame, text="Video URL:").pack(anchor="w")
        url_row = ttk.Frame(url_frame)
        url_row.pack(fill="x", pady=(4, 0))
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_var, font=(ui_font, 10))
        self.url_entry.pack(side="left", fill="x", expand=True)
        self.url_entry.bind("<Return>", lambda _event: self._start_download())
        ttk.Button(url_row, text="Paste", width=8,
                   command=self._paste_url).pack(side="left", padx=(6, 0))

        dir_frame = ttk.Frame(self.root)
        dir_frame.pack(fill="x", **pad)
        ttk.Label(dir_frame, text="Save to:").pack(anchor="w")
        row = ttk.Frame(dir_frame)
        row.pack(fill="x", pady=(4, 0))
        ttk.Entry(row, textvariable=self.download_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse...", command=self._choose_dir).pack(side="left", padx=(6, 0))

        opt_frame = ttk.Frame(self.root)
        opt_frame.pack(fill="x", **pad)

        mode_box = ttk.LabelFrame(opt_frame, text="Format")
        mode_box.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Radiobutton(mode_box, text="Video (mp4)", variable=self.mode_var,
                         value="video", command=self._sync_quality_state).pack(anchor="w", padx=8, pady=2)
        ttk.Radiobutton(mode_box, text="Audio only (mp3)", variable=self.mode_var,
                         value="audio", command=self._sync_quality_state).pack(anchor="w", padx=8, pady=2)

        quality_box = ttk.LabelFrame(opt_frame, text="Max quality")
        quality_box.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.quality_combo = ttk.Combobox(
            quality_box, textvariable=self.quality_var, state="readonly",
            values=QUALITY_CHOICES
        )
        self.quality_combo.pack(padx=8, pady=8, fill="x")

        options_frame = ttk.Frame(self.root)
        options_frame.pack(fill="x", **pad)
        ttk.Label(options_frame,
                  text="Browser cookies (optional — use if a site asks you to log in):").pack(anchor="w")
        self.cookies_combo = ttk.Combobox(
            options_frame, textvariable=self.cookies_var, state="readonly",
            values=COOKIE_CHOICES
        )
        self.cookies_combo.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(
            options_frame,
            text="Automatically update yt-dlp on startup (recommended)",
            variable=self.auto_update_var,
        ).pack(anchor="w", pady=(4, 0))

        self.download_btn = ttk.Button(self.root, text="Download", command=self._start_download)
        self.download_btn.pack(pady=10)
        if not self.ffmpeg_setup_done:
            self.download_btn.configure(state="disabled")

        self.progress = ttk.Progressbar(self.root, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", padx=12)

        self.status_var = tk.StringVar(value="Checking ffmpeg...")
        ttk.Label(self.root, textvariable=self.status_var, foreground="#333").pack(pady=(4, 4))

        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        ttk.Label(log_frame, text="Log:").pack(anchor="w")
        self.log_box = tk.Text(log_frame, height=8, state="disabled", wrap="word",
                                font=(mono_font, 9))
        self.log_box.pack(fill="both", expand=True, pady=(2, 0))

    def _focus_url(self):
        self.url_entry.focus_set()

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.download_dir.get())
        if d:
            self.download_dir.set(d)

    def _save_settings(self):
        save_settings({
            "download_dir": self.download_dir.get(),
            "mode": self.mode_var.get(),
            "quality": self.quality_var.get(),
            "cookies": self.cookies_var.get(),
            "auto_update": bool(self.auto_update_var.get()),
        })

    def _on_close(self):
        self._save_settings()
        if self.is_downloading:
            quit_anyway = messagebox.askyesno(
                "Quit while downloading?",
                "A download is still in progress.\n\n"
                "Quit anyway? The unfinished file may be left in the download folder.")
            if not quit_anyway:
                return
        self.root.destroy()

    def _paste_url(self):
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            return
        if text:
            self.url_var.set(text)

    def _sync_quality_state(self):
        if self.mode_var.get() == "audio":
            self.quality_combo.configure(state="disabled")
        else:
            self.quality_combo.configure(state="readonly")

    def _log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------- yt-dlp update
    def _begin_yt_dlp_update(self):
        if not self.auto_update_var.get():
            self._log("yt-dlp auto-update is disabled (see the checkbox above).")
            return
        if getattr(sys, "frozen", False):
            self._log("Packaged build detected — skipping yt-dlp auto-update.")
            return
        self._log(f"Checking for yt-dlp updates (current: {YT_DLP_VERSION})...")
        thread = threading.Thread(target=self._run_yt_dlp_update, daemon=True)
        thread.start()

    def _run_yt_dlp_update(self):
        def log_cb(text):
            self.msg_queue.put(("log", text))
        upgraded = update_yt_dlp_auto(log_cb)
        self.msg_queue.put(("yt_dlp_update_done", upgraded))

    # ------------------------------------------------------- ffmpeg setup
    def _begin_ffmpeg_setup(self):
        self._log("ffmpeg not found on this system — downloading a portable copy automatically...")
        self.status_var.set("Setting up ffmpeg (one-time)...")
        thread = threading.Thread(target=self._run_ffmpeg_setup, daemon=True)
        thread.start()

    def _run_ffmpeg_setup(self):
        try:
            def progress_cb(pct):
                self.msg_queue.put(("ffmpeg_progress", pct))

            def log_cb(text):
                self.msg_queue.put(("log", text))

            download_ffmpeg_auto(progress_cb, log_cb)
            self.msg_queue.put(("ffmpeg_done", True))
        except Exception as e:
            self.msg_queue.put(("ffmpeg_done", False, str(e) or repr(e)))

    # ------------------------------------------------------------- LOGIC
    def _start_download(self):
        if not self.ffmpeg_setup_done:
            messagebox.showinfo("Please wait", "ffmpeg is still being set up. Try again in a moment.")
            return

        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please paste a video link first.")
            return
        # A pasted block may contain extra lines; only the first one is a URL.
        url = url.splitlines()[0].strip()
        if self.is_downloading:
            messagebox.showinfo("Busy", "A download is already in progress.")
            return
        if "://" not in url:
            # Users often paste "www.youtube.com/watch?v=..." without a scheme.
            url = "https://" + url
        self.url_var.set(url)

        save_dir = self.download_dir.get().strip()
        if not save_dir:
            messagebox.showwarning("Missing folder", "Please choose a save folder.")
            return
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Cannot use that folder",
                                 f"Could not create or access:\n{save_dir}\n\n{e}")
            return

        self._save_settings()

        if any(host in url.lower() for host in BEST_EFFORT_HOSTS):
            self._log("Note: this looks like Terabox/Diskwala — not officially "
                       "supported by yt-dlp. Attempting anyway (best effort)...")

        # Read all Tk variables here, on the main thread. Tkinter is not
        # thread-safe, so the worker only receives plain values.
        mode = self.mode_var.get()
        quality = self.quality_var.get()
        cookies_browser = self.cookies_var.get()

        self.is_downloading = True
        self.download_btn.configure(state="disabled")
        self.progress["value"] = 0
        self.status_var.set("Starting...")

        thread = threading.Thread(
            target=self._run_download,
            args=(url, save_dir, mode, quality, cookies_browser),
            daemon=True)
        thread.start()

    def _run_download(self, url, save_dir, mode, quality, cookies_browser):
        try:
            self._download(url, save_dir, mode, quality, cookies_browser)
        except Exception as e:
            self.msg_queue.put(("error", str(e) or repr(e)))

    def _download(self, url, save_dir, mode, quality, cookies_browser):
        outtmpl = os.path.join(save_dir, "%(title).120s.%(ext)s")

        ydl_opts = {
            "outtmpl": outtmpl,
            "noplaylist": True,
            "progress_hooks": [self._progress_hook],
            "logger": _YdlLogger(self.msg_queue),
            "quiet": True,
            "no_warnings": False,
        }

        loc = ffmpeg_location_for_ydl()
        if loc:
            ydl_opts["ffmpeg_location"] = loc

        if cookies_browser and cookies_browser != "none":
            ydl_opts["cookiesfrombrowser"] = (cookies_browser,)
            self.msg_queue.put(("log", f"Using cookies from {cookies_browser}..."))

        is_youtube = any(d in url.lower() for d in
                          ("youtube.com", "youtu.be", "youtube-nocookie.com", "m.youtube."))

        # Recent yt-dlp versions need a JavaScript runtime for full YouTube
        # format support. Use a usable system runtime, or fetch Deno once.
        if is_youtube and not _has_usable_js_runtime():
            try:
                download_deno_auto(lambda text: self.msg_queue.put(("log", text)))
            except Exception as e:
                self.msg_queue.put(("log",
                    f"Could not set up Deno ({e}). YouTube may offer fewer formats; "
                    f"install Deno 2.3+ or Node.js 22+ and restart the app."))
        ydl_opts["js_runtimes"] = js_runtime_options()
        if is_youtube and not _ejs_available():
            # Without the yt-dlp-ejs package (part of the "default" extras),
            # yt-dlp can fetch the solver scripts from its GitHub release.
            ydl_opts["remote_components"] = {"ejs:github"}

        have_ffmpeg = ffmpeg_ready()

        if mode == "audio":
            if not have_ffmpeg:
                raise RuntimeError(
                    "Audio (mp3) extraction requires ffmpeg, which is not available. "
                    "Check your internet connection and restart the app so the automatic "
                    "setup can retry, or install ffmpeg manually.")
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            if have_ffmpeg:
                if quality == "best":
                    fmt = "bestvideo+bestaudio/best"
                else:
                    height = quality.replace("p", "")
                    # Prefer the requested cap, but never fail just because the
                    # site has no format at or below it.
                    fmt = (f"bestvideo[height<={height}]+bestaudio/"
                           f"best[height<={height}]/"
                           f"bestvideo+bestaudio/best")
                ydl_opts.update({
                    "format": fmt,
                    # mp4 when the codecs allow it, otherwise fall back to mkv
                    # instead of failing the merge.
                    "merge_output_format": "mp4/mkv",
                })
            else:
                self.msg_queue.put(("log",
                    "ffmpeg unavailable — using a pre-merged format (quality may be capped)."))
                if quality == "best":
                    fmt = "best"
                else:
                    height = quality.replace("p", "")
                    fmt = f"best[height<={height}]/best"
                ydl_opts.update({"format": fmt})

        try:
            title = self._download_once(ydl_opts, url)
        except Exception as e:
            err_str = str(e) or repr(e)
            if not (("403" in err_str or "Forbidden" in err_str) and is_youtube):
                raise

            # Try a few known-good player clients in turn — different clients
            # get blocked/unblocked at different times as YouTube changes things.
            title = None
            for client in ("android", "ios", "tv"):
                self.msg_queue.put(("log",
                    f"Got a 403 — retrying with YouTube's '{client}' client workaround..."))
                retry_opts = dict(ydl_opts)
                retry_opts["extractor_args"] = {"youtube": {"player_client": [client]}}
                try:
                    title = self._download_once(retry_opts, url)
                    break
                except Exception as e2:
                    err_str = str(e2) or repr(e2)
            if title is None:
                raise RuntimeError(err_str)

        self.msg_queue.put(("done", title))

    def _download_once(self, ydl_opts, url):
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
        return info.get("title") or "video"

    def _progress_hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            pct = (downloaded / total * 100) if total else 0
            speed = d.get("speed")
            speed_str = f"{speed / 1024 / 1024:.2f} MB/s" if speed else "..."
            self.msg_queue.put(("progress", pct, speed_str))
        elif d["status"] == "finished":
            self.msg_queue.put(("postprocessing", None))

    def _poll_queue(self):
        try:
            while True:
                item = self.msg_queue.get_nowait()
                kind = item[0]

                if kind == "log":
                    self._log(item[1])

                elif kind == "yt_dlp_update_done":
                    upgraded = item[1]
                    self.yt_dlp_update_done = True
                    if upgraded:
                        self._log("✔ yt-dlp updated to the latest version "
                                   "(takes effect next app restart).")
                    else:
                        self._log("yt-dlp is already up to date (or update check failed).")

                elif kind == "ffmpeg_progress":
                    pct = item[1]
                    self.progress["value"] = pct
                    self.status_var.set(f"Setting up ffmpeg... {pct:.0f}%")

                elif kind == "ffmpeg_done":
                    success = item[1]
                    self.progress["value"] = 0
                    if success:
                        self.ffmpeg_setup_done = True
                        self.download_btn.configure(state="normal")
                        self.status_var.set("Ready. (ffmpeg set up successfully)")
                        self._log("✔ ffmpeg is ready. Full quality downloads and mp3 audio are now enabled.")
                    else:
                        err = item[2] if len(item) > 2 else "unknown error"
                        self.status_var.set("ffmpeg auto-setup failed — downloads still work in fallback mode.")
                        self._log(f"✘ ffmpeg auto-setup failed: {err}")
                        self._log("You can still download videos (single pre-merged formats only). "
                                   "For mp3 audio and best quality, install ffmpeg manually and restart.")
                        self.ffmpeg_setup_done = True
                        self.download_btn.configure(state="normal")

                elif kind == "progress":
                    pct, speed = item[1], item[2]
                    self.progress["value"] = pct
                    self.status_var.set(f"Downloading... {pct:.1f}%  ({speed})")

                elif kind == "postprocessing":
                    self.status_var.set("Processing (merging/converting)...")

                elif kind == "done":
                    title = item[1]
                    self.progress["value"] = 100
                    self.status_var.set("Done!")
                    self._log(f"✔ Downloaded: {title}")
                    self.is_downloading = False
                    self.download_btn.configure(state="normal")

                elif kind == "error":
                    err = item[1]
                    low = err.lower()
                    is_youtube = "youtube" in low or "youtu.be" in low
                    self.status_var.set("Failed.")
                    self._log(f"✘ Error: {err}")
                    if "confirm you" in low and "bot" in low:
                        messagebox.showerror(
                            "YouTube sign-in required",
                            "YouTube asked for a sign-in confirmation (bot check).\n\n"
                            "Select the browser you use for YouTube under "
                            "'Browser cookies', make sure you are logged in there, "
                            "close the browser, and try again.")
                    elif ("403" in err or "forbidden" in low) and is_youtube:
                        friendly = (
                            "YouTube returned a 403 Forbidden error. This usually means "
                            "yt-dlp is out of date for YouTube's current site changes, or the "
                            "video requires a signed-in session.\n\n"
                            "The app already tried updating yt-dlp in the background this "
                            "session (see the log). Please fully CLOSE and REOPEN the app so "
                            "the update takes effect, then try again.\n\n"
                            "If that does not help, select your browser under "
                            "'Browser cookies' so yt-dlp can use your logged-in session, or "
                            "wait a day or two for a yt-dlp fix."
                        )
                        messagebox.showerror("Download failed (403 Forbidden)", friendly)
                    else:
                        messagebox.showerror("Download failed", err)
                    self.is_downloading = False
                    self.download_btn.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)


def main():
    if platform.system() == "Windows":
        try:
            import ctypes
            # Crisp text on high-DPI displays (fails harmlessly on old Windows).
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    if not YT_DLP_AVAILABLE:
        root.withdraw()
        messagebox.showerror(
            "Missing dependency",
            "yt-dlp is not installed.\n\n"
            "Install it with:\n"
            f'    "{sys.executable}" -m pip install "yt-dlp[default]"\n\n'
            "then start this app again.",
        )
        root.destroy()
        return

    app = DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
