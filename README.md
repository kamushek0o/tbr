> [читать на русском](README_RU.md)

# tbr pro — qbittorrent swiss-army knife

> supports **en / ru** ui toggle right in the header!

# features

1. **pause and resume all torrents at once** (groundbreaking technology, i know)

2. **export csv summaries** so you can finally show your wife, mom, dad, or boyfriend why your pc hasn't been turned off in a month

3. **fastresume stats merger:** if you're a ratio-obsessed stats nerd and don't want to lose all upload stats on a torrent—or keep 50 versions of the same game on your pc—you can transfer `uploaded` & `seeding_time` metadata to a new torrent using my *innovative* merger (safely closes and restarts qbittorrent so bencode doesn't get corrupted)

4. **smart eta forecaster & hourly history:** calculate when you'll hit a specific upload/ratio goal using weighted historical data (sqlite), or check how a torrent gained its upload hour-by-hour

5. **works even without qbittorrent webui running** (well, except tab 1—obviously, it basically mirrors the webui)

6. **light as a feather** — tiny standalone `.exe`, no python required

7. **convenient (for me) file structure**

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

1. **qbittorrent webui** — password is now supported! just enter your qb webui login/password in `⚙️ settings` (or leave it bypassed on localhost, up to you)

2. **qbittorrent** — haven't tested other clients (transmission doesn't count, it's kinda creepy). and if you don't use qb, why are you even here, normie?

3. **windows / linux / docker** — `.exe` is built for windows (tested on win 11), and now it also runs on linux & docker in headless web mode (`python main.py --headless` or `Dockerfile`)

4. **paranoid about random `.exe` files?** fair enough! the `.exe` in releases is now auto-compiled by **github actions** straight from this open-source code (no sketchy local builds). or just run `pip install -r requirements.txt` -> `python main.py`, or build it yourself via `build.bat`

# outro

fellow pirates and piratesses, enjoy! don't eat yellow snow. if anything breaks or sucks, open an [issue](https://github.com/kamushek0o/tbr/issues) or hit me up at `loh260330@gmail.com`
