# Take Sync

Line up every take of a piece against one reference take, then hop between takes at the same
musical spot and build an edit list, in your browser.

You get one page, `sync.html`, showing each take as a bar on a shared timeline:

- Press a take's key (`1`–`9`, `0`, `q`–`p`) and playback jumps to the **same spot in the music** in that take.
- Partial takes and pickups show up where they belong in the piece.
- Press **Enter** at an edit point to mean "from here on, use this take". Tick **play the edit** to hear the assembled version.
- Export the edit list as a CSV for your editor, or mark a passage and list where it sits in every take.

The alignment follows the notes being played (pitch content), so it works for any pitched music:
voice and piano, ensembles, solo instruments. It does **not** judge intonation or accuracy. It's
less reliable for unpitched percussion, and for takes where most of the file is talking.

Your audio files are only read, never changed.

**Get it:** `git clone https://github.com/juggleinpink/take-sync.git`, or use the green **Code → Download ZIP** button on GitHub.

Shared as-is under the MIT license: free to use and change. No support is promised, but issues and fixes are welcome.

---

## 1. Install (one time)

You need **Python 3** and **ffmpeg**, plus the Python package **numpy**.

**Mac** (in Terminal):
```
brew install ffmpeg          # needs Homebrew: https://brew.sh
python3 -m pip install numpy
```
**Windows** (in PowerShell): install Python from python.org (tick "Add to PATH"), then
```
winget install ffmpeg
py -m pip install numpy
```
(On Windows, type `py` wherever this guide says `python3`.)

## 2. Put your takes in folders

The quick way is one folder per song, with that song's takes inside it:

```
My Session/
  Song A/
    take 1.wav
    take 2.wav
    take 3 (bars 40-60).wav
  Song B/
    ...
```

WAV, AIFF, FLAC, MP3 and M4A all work. Every take of a song must be the same arrangement (same key and tempo region).
Takes can be partial; that's the point.

## 3. Run it

```
python3 path/to/take_sync.py "path/to/My Session"
```

Tip: type `python3 `, then drag `take_sync.py` into the Terminal window, then drag your session folder in.

The first run reads every file (about a second per file) and creates three things in your session folder:

| File | What it is |
|---|---|
| `sync.html` | The player. Open it in **Chrome or Safari**. |
| `takes.csv` | The list of takes it found. Edit it to improve the results (step 4). |
| `sync_report.csv` | Where each take starts and ends in the reference, and a confidence rating for each. |

**Keep `sync.html` inside the session folder.** It plays your audio files from there; it doesn't contain them.
If you move or rename audio files, run the script again.

## 4. Improve the results with `takes.csv`

Open `takes.csv` in Excel, Numbers or Google Sheets (save it as CSV again). Columns:

| Column | Required | Meaning |
|---|---|---|
| `song` | yes | Song name. Takes with the same name are compared with each other. |
| `take` | yes | The take's name as shown in the player (e.g. `T12`, `Take 3`). Must be unique within a song. |
| `file` | yes | Path to the audio file, relative to the session folder (or a full path). |
| `reference` | | `yes` on the one take everything is lined up against. Choose a **clean, complete run-through** with no false starts or extra material. If blank, the script picks the longest take that isn't unusually long. |
| `starts_at_measure` | | The measure (bar) number where this take's music **begins**, e.g. `61` for a pickup from bar 61. Even one or two of these turn on estimated measure numbers in the player. On the reference row it means "the reference starts at this bar" (default 1). |
| `session` | | Optional label shown next to the take, e.g. `Day 2`. |
| `note` | | Optional note shown next to the take. |

Then run the same command again. Re-runs are fast because the analysis is cached in `.take-sync-cache/` (safe to delete).

You can also skip the folders entirely and write `takes.csv` yourself, with the files anywhere on your disk.

Useful options:
```
python3 take_sync.py "My Session" --songs "Song A"        # only some songs
python3 take_sync.py "My Session" --title "Spring Album"  # page title
python3 take_sync.py "My Session" --workers 2             # use less memory
```

## 5. Using the player

| Key | Action |
|---|---|
| `space` | play / pause |
| `1`–`9`, `0`, `q`–`p` | switch to that take at the same musical spot |
| `↑` / `↓` | previous / next take that covers this spot |
| `←` / `→` | back / forward 3 seconds |
| `[` / `]` | mark start / end of a region; `l` loops it, `b` jumps to its start |
| `Enter` | "use this take from here": adds an edit point |
| `f` | play the edit (switches takes at every edit point) |

- **Bold underlined** take = the reference. The timeline is in the reference's time.
- **Striped bars** = alignment that didn't cross-check well. Listen before trusting those.
- **Faded rows** = takes that don't cover the current spot.
- **Match levels** evens out loudness differences between takes so comparisons are fair.
- Drag an edit point on the EDIT strip to move it (hold Shift for fine moves), or use the ◀ ▶ buttons.
- Edits and groups are saved in your browser, per song. **Export edit list (CSV)** gives your editor
  the exact in and out times in each original file. **Import edit list** loads one back.

Measure numbers ("~m.") are estimates and can be off by 2–3 bars. Seconds are exact.

## Troubleshooting

- **"ffmpeg is not installed"**: see step 1. Close and reopen Terminal after installing.
- **No sound in the player**: make sure `sync.html` is still in the session folder and the audio files haven't moved.
  AIFF files don't play in Chrome; use Safari, or convert the files to WAV.
- **A take lands in the wrong place**: mark a better reference, or add `starts_at_measure` for that take, and re-run.
  Takes that are mostly talking or noise can't be placed.
- **Out of memory on very long pieces (15 min+)**: add `--workers 1`.

## Getting help from an AI assistant

`AGENTS.md` in this folder is a setup guide written for AI assistants. Paste it into ChatGPT, Claude or another
chat assistant and ask it to walk you through. Coding agents (Claude Code, Codex, Cursor and similar)
started in this folder read it automatically.
