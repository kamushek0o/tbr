> [читать на русском](README_RU.md)

# tbr pro — qbittorrent swiss-army knife

> supports **en / ru** ui toggle right in the header!

# features

1. **pause and resume all torrents at once** (groundbreaking technology, i know)

2. **export csv summaries** so you can finally show your wife, mom, dad, or boyfriend why your pc hasn't been turned off in a month

3. **fastresume stats merger with safe source cleanup:** if you're a ratio-obsessed stats nerd and don't want to lose all upload stats on a torrent—or keep 50 versions of the same game on your pc—you can transfer `uploaded` & `seeding_time` metadata to a new torrent using my *innovative* merger (safely closes and restarts qBittorrent so bencode doesn't get corrupted). Now with optional automated source deletion: it checks file paths to prevent accidental data loss and safely downgrades to torrent-only removal if folders overlap

4. **smart eta forecaster & honest speed history:** calculates when you'll hit a specific upload/ratio goal using weighted historical data (SQLite). The load chart is now continuous—no dumb hourly buckets, smoothed phantom spikes from newly added torrents, and detailed tooltips (hover over any point to see exact transfer speed and volume uploaded between snapshots)

5. **dead torrents & tracker error scanner:** multi-threaded scan through all trackers across your library, groups recurring tracker errors, and lets you pause all dead weight with a single click

6. **android home screen widget (`tbr-widget`) + PWA:** yes, you can now stare at your seedbox speeds right from your phone's home screen. Native Android widget with one-tap chart toggling (24h speed vs daily bars) and a manual `↻` refresh button, plus the web UI installs cleanly as an address-bar-free PWA

7. **profiles & RBAC (Admin / Viewer):** generate 1-click magic links with read-only Viewer permissions for friends or family—they get to admire your upload flex without being able to stop torrents or mess up your config

8. **personal spam bot disguised as automation (tg & discord):** set rules (min ratio / seeding days / upload volume / average speed in window W) so torrents auto-pause or get tagged—or just drop a discord webhook into your friends' server and forcibly subject them to your upload achievements

9. **works even without qbittorrent webui running** (well, except tab 1—obviously, it basically mirrors the webui)

10. **light as a feather** — tiny standalone `.exe`, no python required

11. **clean (for me) modular architecture** — every file strictly under 300 lines, zero spaghetti code

# screenshots

### 1. torrents
![torrents](interfaces/interface1.png)

### 2. fastresume merger
![merger](interfaces/interface2.png)

### 3. summary
![summary](interfaces/interface3.png)

### 4. analytics & forecaster
![analytics](interfaces/interface4.png)

# why should i download your vibecode?

1. i haven't seen any real alternatives

2. the features are actually useful

3. please

# what do i need to make it work?

1. **qbittorrent webui** — password protected setups are supported! just enter your qB webui login/password in `⚙️ settings` (or leave it bypassed on localhost, up to you)

2. **qbittorrent** — haven't tested other clients (transmission doesn't count, it's kinda creepy). and if you don't use qB, why are you even here, normie?

3. **windows / linux / docker** — `.exe` is built for windows (tested on win 11), and now it also runs headless on linux & docker (`python main.py --headless` or via `Dockerfile`)

4. **want the phone widget?** grab the prebuilt `.apk` from the companion repo [tbr-widget](https://github.com/kamushek0o/tbr-widget/releases) — plug in your server URL and Viewer token, and you're good to go

5. **paranoid about random `.exe` files?** fair enough! the `.exe` in releases is auto-compiled by **github actions** straight from this open-source code (no sketchy local builds). or just run `pip install -r requirements.txt` -> `python main.py`, or build it yourself via `build.bat`

# outro

fellow pirates and piratesses, enjoy! don't eat yellow snow. if anything breaks or sucks, open an [issue](https://github.com/kamushek0o/tbr/issues) or hit me up at `loh260330@gmail.com`
