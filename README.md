# TTMediaBot (Windows Edition)

**Hello! I am Smart Thinh.** Welcome to the **TTMediaBot** edition optimized specifically for **Microsoft Windows** (based on João Almeida's fork and the original TTMediaBot by Amir Gumerov).

This repository is dedicated to rock-solid stability, studio-grade audio quality, seamless Windows compatibility (Windows 10, 11, and Windows Server), and ultra-fast response times.

> 🔗 **Official Repository:** [https://github.com/smartthinh/TTMediaBot](https://github.com/smartthinh/TTMediaBot)  
> 🐧 **Looking for Linux/Docker?** This repository is specifically dedicated to the **Native Windows Edition**. If you need the Linux/Docker version, please visit [João Almeida's upstream repository](https://github.com/JoaoDEVWHADS/TTMediaBot) or the [original TTMediaBot](https://github.com/gumerov-amir/TTMediaBot).

---

## ✨ Highlights of the Windows Edition

Compared to the original Linux/Docker implementation, this edition has been completely re-architected for Windows:

1. **🪟 Pure Native Windows Architecture (Zero Docker / Zero Node.js):**
   - Completely removes Docker containers, Linux shell scripts (`*.sh`), systemd services, and the external Node.js `youtube_bridge` daemon.
   - Runs directly on Windows with Python 3.10+, utilizing pre-bundled `TeamTalk5.dll` and `mpv.dll` dynamic libraries.
   - Powered by the **Windows WASAPI** audio backend (`ao="wasapi"`), delivering bit-perfect, jitter-free playback with ultra-low latency.
   - Features automatic in-memory patching (`_disable_trial_dialog`) in `TeamTalkPy/TeamTalk5.py` to eliminate blocking trial dialog popups during bot startup on Windows.
   - Built-in UTF-8 console output for international/Unicode titles and prioritized IPv4 DNS lookups to eliminate network resolution bottlenecks.

2. **🔍 Intelligent Hybrid Song Recognition (`ws` - v3.1):**
   - Integrates a 3-tier hybrid recognition engine: **YouTube Chapters -> Shazam -> Google Voice AI**.
   - Accurately identifies both **instrumentals without words** (piano, guitar, lofi) and **vocal songs** (Bolero, pop, covers, live performances).
   - High-speed parallel concurrency architecture: extracts a single 10-second 16kHz mono WAV slice, queries Shazam and Google Speech simultaneously, and returns results in **3 to 5 seconds**.

3. **🎛️ Studio-Grade Audio DSP Suite:**
   - **Musical Pitch Shift (`pt`):** Shift playback pitch in real-time between `-12` and `+12` semitones using mpv's tuned Rubber Band v3 engine (`@pitch:rubberband`), preserving punchy drum transients and crystal-clear vocals.
   - **Automated Silence Trimming (`ts`):** Strips leading and trailing dead silence from streams to ensure seamless track transitions.

4. **⚡ Self-Contained Direct `yt-dlp` Media Engine:**
   - Resolves YouTube and YouTube Music streams directly via native Python `yt-dlp` without external background daemons.
   - Multi-track prefetching pipeline resolves both the upcoming track and the track after next for instant, buffer-free track skipping.
   - Retrieve permanent canonical YouTube URLs with the **`yl`** command (with optional TinyURL shortening).
   - Download complete playlists and albums as compressed ZIP archives to the channel via the **`dlp`** command.

---

## 🚀 Windows Installation Guide

### 1. Prerequisites
- **Operating System:** Windows 10, Windows 11, or Windows Server (64-bit).
- **Python 3.10 or newer** (Python 3.11, 3.12, or 3.13 64-bit recommended). Make sure to check **"Add python.exe to PATH"** during installation.
- **TeamTalk 5 client installed on Windows** (the bot automatically detects `TeamTalk5.dll` from `C:\Program Files\TeamTalk5\` or the bot root folder).
- `mpv.dll` (shared C library for the MPV audio engine, setup in Step 2 below).

### 2. Setup Steps

#### Step 1: Clone or Download the Repository
Clone the repository with Git or download and extract the ZIP file:
```cmd
git clone https://github.com/smartthinh/TTMediaBot.git
cd TTMediaBot
```

#### Step 2: Download & Setup the MPV Library (`mpv.dll`)
Because the high-performance `mpv.dll` dynamic library exceeds 100MB, obtain the official Windows release directly:
1. Visit the official Windows releases page: [https://github.com/shinchiro/mpv-winbuild-cmake/releases](https://github.com/shinchiro/mpv-winbuild-cmake/releases)
2. In the **Assets** section of the latest release, search for and download the archive starting with:
   ```
   mpv-dev-x86_64-*.7z
   ```
   > ⚠️ **Important:**
   > - Make sure the archive contains **`dev`** (`mpv-dev-x86_64-...`). Do not download standard player builds as they lack the C developer DLL.
   > - Avoid builds containing **`v3`** (e.g., `mpv-dev-x86_64-v3-...`) if deploying to a VPS or older PC, as they require AVX2 instructions and will crash on virtual machine CPUs.
3. Extract the downloaded `.7z` archive using 7-Zip or WinRAR.
4. Inside the extracted folder, find `libmpv-2.dll` (or `mpv-2.dll`) and rename it to:
   ```
   mpv.dll
   ```
5. Copy `mpv.dll` and paste it into the root directory of the bot (`TTMediaBot`).

#### Step 3: Install Dependencies
Open Command Prompt (cmd) or PowerShell inside the bot directory and run:
```cmd
pip install -r requirements.txt
```
*(The `static-ffmpeg` package automatically manages FFmpeg binaries for Windows, so no manual system PATH configuration is required).*

#### Step 4: Inspect Audio Devices
Run the following command in your terminal:
```cmd
python TTMediaBot.py --devices
```
This will print a numbered list of available Windows audio Input and Output devices along with their device IDs.

#### Step 5: Configure the Bot (`config.json`)
Open `config.json` with Notepad or your favorite editor and configure your server settings:
- `teamtalk.hostname`: TeamTalk 5 server address (e.g., `tt5.example.com`).
- `teamtalk.tcp_port` & `udp_port`: Connection ports (default: `10333`).
- `teamtalk.username` & `password`: Bot account login credentials.
- `teamtalk.nickname`: Nickname displayed by the bot in channels.
- `teamtalk.channel`: Channel the bot joins on connect (e.g., `/` or `/Music`).
- `teamtalk.users.admins`: Array of TeamTalk usernames with administrator privileges (e.g., `["admin"]`).
- `sound_devices.output_device`: Output device ID obtained from Step 4.
- `sound_devices.input_device`: Input device ID obtained from Step 4.

#### Step 6: Start the Bot
Run the following command:
```cmd
python TTMediaBot.py
```

---

## 🎮 Command Reference

Send commands via private message (PM) to the bot or directly in the channel (if channel messages are enabled).

### User Commands

| Command | Arguments | Description |
| :--- | :--- | :--- |
| **h** | `[command]` | Shows the general help menu or detailed instructions for a specific command. |
| **p** | `[query/url]` | Searches and plays tracks. If called without an argument, toggles Pause / Resume. |
| **u** | `[url]` | Plays an audio stream or file directly from a URL. |
| **s** | | Stops playback. |
| **n** | `[number/?]` | Plays the next track, jumps to a track index, or reports current position with `?`. |
| **b** | | Plays the previous track. |
| **v** | `[0-100]` | Adjusts playback volume (0 to 100%). Calling without an argument displays current volume. |
| **sb** | `[seconds]` | Seeks backward by the specified duration (default: 5 seconds). |
| **sf** | `[seconds]` | Seeks forward by the specified duration (default: 5 seconds). |
| **c** | `[number/?]` | Jumps to a track number or reports the current playlist position with `?`. |
| **m** | `[mode]` | Sets playback mode: `SingleTrack`, `RepeatTrack`, `TrackList`, `RepeatTrackList`, `Random`. |
| **pt** | `[-12 to 12]` | **Adjusts Pitch/Key:** Shifts playback pitch in semitones (e.g., `pt 2`, `pt -2`, `pt 0` to reset). Calling without arguments displays the current pitch. |
| **ts** | | **Toggles Silence Trimming:** Automatically removes leading and trailing dead silence from audio streams. |
| **ws** | `[-s]` | **Identifies Current Song:** Identifies the song playing in a mix or compilation using Chapters, Shazam, or Google Voice AI. Use `ws -s` to bypass chapters and force acoustic recognition. |
| **yl** | | **Gets Canonical YouTube Link:** Returns the permanent YouTube watch URL of the current playing track. |
| **gl** | | Returns the direct CDN stream link of the current track. |
| **sv** | `[yt/ytm]` | Switches playback service: `sv yt` (YouTube) or `sv ytm` (YouTube Music). |
| **sp** | `[0.25-4]` | Adjusts playback speed. |
| **f** | `[+/-][num]` | Manages Favorites: `f` lists, `f +` adds current track, `f -` removes, `f [num]` plays. |
| **r** | `[num]` | Manages playback history (Recents): `r` lists recent tracks, `r [num]` plays. |
| **qa** | `[query]` | Adds a track to the playback queue. |
| **ql** | | Lists all tracks currently waiting in the queue. |
| **qr** | `[num]` | Removes a specific track from the queue by index. |
| **qc** | | Clears the entire playback queue. |
| **qs** | | Skips the current track and immediately plays the next track from the queue. |
| **dl** | | Downloads the current track and uploads it to the TeamTalk channel. |
| **dlv** | | Downloads the current track as a video file and uploads it to the channel. |
| **dlp** | `[url]` | Downloads an entire playlist/album, zips it, and uploads the archive to the channel. |
| **aad** | `[link]` | Adds a single URL to your custom download queue. |
| **ad** | `[link1 link2]`| Adds multiple space-separated links to your custom download queue. |
| **ld** | | Lists all links currently in your custom download queue. |
| **rd** | `[num/link]` | Removes a link from the download list by its index or URL. |
| **ldd** | `[link]` | Directly downloads a link and uploads the audio to the channel. |
| **ads** | `[1/2]` | Downloads custom list: Option `1` (sequential files) or Option `2` (compressed ZIP). |
| **adsc** | | Toggles local download mode: saves files locally on the computer instead of uploading to TeamTalk. |
| **jc** | | Directs the bot to join the requester's current channel. |
| **sr** | `[on/off]` | Toggles Search Results mode: `p QUERY` presents a numbered list instead of playing immediately. |
| **sl** | `[num]` | Selects and plays a numbered track from the last `sr` search list. |
| **slc** | `[num]` | Configures the number of search results shown in `sr` mode. |
| **a** | | Displays bot version, author details, and about information. |

---

### Admin Commands
*Restricted to accounts listed in the `teamtalk.users.admins` array in `config.json`.*

| Command | Arguments | Description |
| :--- | :--- | :--- |
| **cg** | `[n/m/f]` | Changes the bot's account gender (`n`: None, `m`: Male, `f`: Female). |
| **cl** | `[code]` | Changes bot language (e.g., `cl en`, `cl pt_BR`, `cl ru`, `cl es`, `cl tr`, `cl ar`, etc.). |
| **cn** | `[name]` | Updates the bot's nickname on the server. |
| **cs** | `[status]` | Updates the bot's status text message. |
| **cc** | `[r/f]` | Clears cache data (`cc r`: clears recents history, `cc f`: clears favorites). |
| **cm** | | Toggles channel messaging mode between public channel broadcasts and private messages (PM). |
| **ajc** | `[id] [pass]` | Force-joins a channel using channel ID and optional password. |
| **bc** | `[+/-cmd]` | Blocks or unblocks a specific command for non-admin users. |
| **l** | | Locks or unlocks the bot (when locked, only admins can issue commands). |
| **ua** | `[+/-user]` | Grants or revokes administrator privileges for a TeamTalk user. |
| **ub** | `[+/-user]` | Bans or unbans a user from interacting with the bot. |
| **eh** | | Toggles custom event handling routines. |
| **sc** | | Saves current runtime settings to `config.json`. |
| **va** | | Toggles voice transmission on/off. |
| **rs** | | Restarts the bot process. |
| **q** | | Shuts down the bot. |
| **gcid** | | Outputs the current channel ID. |

---

## 🍪 YouTube & YouTube Music Cookies Configuration (Recommended)

Due to YouTube rate-limiting and bot checks, configuring authentication cookies is recommended for reliable, uninterrupted playback.

### How to Export Cookies:
1. Log into your Google / YouTube account in your web browser (Chrome, Edge, or Firefox).
2. Install a Netscape-compatible cookie exporter extension:
   - **Chrome / Edge:** [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid)
   - **Firefox:** [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)
3. Visit `youtube.com`.
4. Click the extension icon, select **"Export All Cookies"**, and save the file as `cookies.txt`.
5. Create a `data` folder inside your bot root directory and place the file at `data/cookies.txt`.
6. Ensure `services.yt.cookiefile_path` in `config.json` points to `"data/cookies.txt"`.

---

## 🔧 Windows Troubleshooting & FAQ

### 1. Bot connects but there is no sound
- Verify your audio device settings: Run `python TTMediaBot.py --devices` to ensure the device IDs specified in `config.json` under `sound_devices` match your active Windows playback hardware.
- Test volume levels by sending `v 80` to the bot.

### 2. Missing DLL or Module Error on Startup
- Re-run `pip install -r requirements.txt` in your command prompt.
- Confirm that `TeamTalk5.dll` and `mpv.dll` are located directly in the root directory alongside `TTMediaBot.py`. Refer to **Step 2** above if you need to download and set up `mpv.dll`.

### 3. Running Multiple Bots Simultaneously on Windows
You can run multiple bot instances concurrently on a single Windows machine:
1. Make a copy of `config.json` (e.g., `config_bot2.json`).
2. Modify `nickname` (and `username` if separate accounts are needed on the TeamTalk server).
3. Open a second command prompt window and start the secondary bot:
   ```cmd
   python TTMediaBot.py -c config_bot2.json
   ```

### 4. Viewing Diagnostics & Logs
All execution logs, track resolution diagnostics, and song identification logs are recorded in:
```
TTMediaBot.log
```
located directly in the bot root directory.

---

## ⚖️ License & Disclaimer

This software is distributed "AS IS" under the open-source MIT License. The authors assume no liability for service interruptions, data loss, or system issues arising from the use of this software.
