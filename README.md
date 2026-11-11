# Universal Video Downloader

A simple desktop app (Python + Tkinter) that downloads videos and audio from
YouTube, Instagram, TikTok, Twitter/X, Facebook, Vimeo, Reddit and hundreds of
other sites, powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

Paste a link, pick a folder, choose video (MP4) or audio (MP3), and click
**Download**. No command line needed while using it.

> **Only download content you own or have permission to use.** Respect each
> platform's Terms of Service and copyright law.

---

## Features

- **Paste-and-go GUI** – no terminal commands during normal use.
- **Automatic ffmpeg setup** – on first launch the app checks for ffmpeg and,
  if it is missing, downloads a portable copy for Windows, macOS (Intel and
  Apple Silicon) or Linux (x86_64, arm64, armhf) — no admin rights and no PATH
  editing. Full-quality merging and MP3 extraction then work automatically.
- **Automatic yt-dlp updates** – yt-dlp (with its `default` extras, including
  `yt-dlp-ejs`) is upgraded in the background at startup by default (can be
  switched off in the window), because an outdated yt-dlp is the most common
  cause of download errors and 403 responses.
- **Automatic JavaScript runtime** – recent yt-dlp versions need a JS runtime
  for full YouTube support. The app uses a recent installed Deno/Node/Bun, or
  downloads a portable copy of Deno once (~40 MB), and fetches the yt-dlp
  challenge-solver scripts when needed.
- **Remembers your settings** – download folder, format, quality, cookie source
  and update preference are restored on the next launch.
- **Video or audio** – save as MP4 (video + audio merged, MKV fallback when the
  codecs are incompatible) or MP3 (192 kbps).
- **Quality selector** – best available, 1080p, 720p, 480p or 360p.
- **YouTube 403 workaround** – retries automatically with alternate player
  clients before giving up.
- **Browser cookies (optional)** – load cookies from your browser for sites
  that require a login (Instagram, private/age-restricted videos, etc.).
- **Safe closing** – asks for confirmation if a download is still running.
- **Graceful fallback** – if ffmpeg cannot be installed, downloads still work
  using pre-merged formats (quality may be capped, MP3 disabled).

---

## Requirements

| Requirement | Notes |
|---|---|
| **Python 3.11+** | Current yt-dlp releases require Python 3.11 or newer. |
| **yt-dlp[default]** | Installed with pip; `default` extras provide the YouTube challenge-solver scripts. |
| **Internet connection** | For downloads, the first-run ffmpeg download, and yt-dlp updates. |
| **Tkinter** | Bundled with the standard Python installers for Windows and macOS. On Linux install `python3-tk`. |

The app downloads ffmpeg automatically; you do **not** need to install it
yourself.

---

## Installation

1. **Install Python 3.11 or newer** from
   [python.org](https://www.python.org/downloads/) (tick *Add Python to PATH*
   on Windows). On Linux, use your distribution's Python 3 package.

2. **Download or clone this repository**, then open a terminal in its folder.

3. **Install the dependency:**

   ```bash
   python -m pip install -r requirements.txt
   ```

   If pip refuses because the environment is "externally managed" (common on
   recent Linux distributions and Homebrew Python), use one of:

   ```bash
   python -m pip install -r requirements.txt --break-system-packages
   ```

   or, preferably, create a virtual environment first:

   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS / Linux:
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

4. **Run the app:**

   ```bash
   python video_downloader.py
   ```

On Linux, if you see `ModuleNotFoundError: No module named 'tkinter'`, install
the Tk package for your distribution, for example:

```bash
sudo apt install python3-tk        # Debian / Ubuntu
sudo dnf install python3-tkinter   # Fedora
sudo pacman -S tk                  # Arch
```

---

## Usage

1. Paste a video link into **Video URL** (or press **Paste**) and press
   **Enter** or click **Download**.
2. Choose the **Save to** folder.
3. Select **Video (mp4)** or **Audio only (mp3)**.
4. Pick a **Max quality** (video mode only).
5. If the site asks you to log in, select a browser in
   **Browser cookies (optional)**. Close that browser first if cookie reading
   fails (common with Chrome on Windows).
6. Leave **Automatically update yt-dlp on startup** ticked unless you manage
   yt-dlp yourself.
7. Click **Download** and watch the progress bar and log.

On the first launch the app may spend a minute downloading ffmpeg and updating
yt-dlp. The Download button is enabled as soon as setup finishes.

### Where files are stored

| What | Location |
|---|---|
| Downloaded media | The folder you choose (defaults to `~/Downloads`) |
| Portable ffmpeg | `~/.universal_video_downloader/ffmpeg_bin/` |
| Portable Deno (if needed) | `~/.universal_video_downloader/js_bin/` |
| Your settings | `~/.universal_video_downloader/settings.json` |
| Temporary downloads | `~/.universal_video_downloader/_tmp_*` (removed automatically) |

---

## Supported sites

Anything supported by yt-dlp, including:

YouTube, Instagram, TikTok, Twitter/X, Facebook, Vimeo, Reddit, Twitch,
Dailymotion, SoundCloud, Bilibili, and many more. See the full
[yt-dlp supported sites list](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).

**Not officially supported:** Terabox / Diskwala / 1024tera-type cloud-storage
share links. The app still attempts them on a best-effort basis, but success
depends on the site's current structure and login walls.

---

## Troubleshooting

| Problem | What to try |
|---|---|
| `yt-dlp is not installed` | Run `python -m pip install -r requirements.txt`, then restart the app. |
| `ModuleNotFoundError: No module named 'tkinter'` | Install your OS's Tk package (see [Installation](#installation)). |
| Download fails with **403 Forbidden** on YouTube | The app already tried to update yt-dlp. Fully close and reopen the app so the new version is loaded, then retry. If it still fails, choose your browser under **Browser cookies** (for age-restricted or member-only videos) or wait a day or two for a yt-dlp fix. |
| YouTube says **“Sign in to confirm you're not a bot”** | YouTube is asking for a logged-in session. Select the browser where you are logged into YouTube under **Browser cookies**, close that browser, and try again. |
| **“n challenge solving failed” / no JavaScript runtime** | The app downloads Deno automatically on the first YouTube download. If that fails (for example GitHub is blocked), install Deno or Node.js 22+ and restart the app. |
| **ffmpeg auto-setup failed** | Check your connection/proxy, then restart the app. You can also install ffmpeg manually and make sure both `ffmpeg` and `ffprobe` are on `PATH`. On Linux, also check that your CPU architecture is supported by the automatic download (x86_64, arm64, armv7); otherwise install ffmpeg with your package manager. |
| **mp3 option does nothing / fails** | MP3 extraction needs ffmpeg. Restart the app so the automatic setup runs, or install ffmpeg manually. |
| **macOS blocks the downloaded ffmpeg** | The app ad-hoc signs the binaries on Apple Silicon automatically. If Gatekeeper still complains, run `xattr -dr com.apple.quarantine ~/.universal_video_downloader/ffmpeg_bin/` once, or `brew install ffmpeg`. |
| Instagram/private video asks for login | Select your browser under **Browser cookies**. Make sure you are logged in there, and close the browser before downloading. |
| `SSL: CERTIFICATE_VERIFY_FAILED` (macOS python.org build) | Run `/Applications/Python 3.x/Install Certificates.command` once. |
| The pip update fails silently | The app still works; the update is only a convenience. Update manually with `python -m pip install -U "yt-dlp[default]"`. |
| Some sites stopped working | Update yt-dlp manually: `python -m pip install -U "yt-dlp[default]"`. |

The **Log** panel at the bottom of the window shows the exact error message from
yt-dlp, which is useful when reporting an issue.

---

## Build a standalone executable (optional)

You can package the app with [PyInstaller](https://pyinstaller.org/):

```bash
python -m pip install pyinstaller
pyinstaller --noconsole --onefile --name UniversalVideoDownloader video_downloader.py
```

The executable is written to `dist/`. Note that the in-app yt-dlp auto-update
relies on pip and a normal Python environment, so a packaged build will not be
able to update itself; ship a new build or use a normal Python install if you
want automatic updates.

---

## Project structure

```
.
├── video_downloader.py   # The application (single file)
├── requirements.txt      # Python dependencies
├── README.md
├── LICENSE
└── .gitignore
```

---

## Disclaimer

This tool is a graphical front-end for yt-dlp. It does not host or distribute
any media. Downloading copyrighted material without permission may be illegal
in your country. You are responsible for how you use this software and for
complying with the terms of service of the sites you access.

---

## License

Released under the [MIT License](LICENSE).
