# Take Sync: guide for AI assistants

You're helping someone, usually a musician and not a programmer, set up and run Take Sync on their own
recordings. Read this whole file before acting. `README.md` is the user-facing version of the same material.

## What the tool is

- `take_sync.py` (Python 3, numpy, ffmpeg) aligns every take of a piece to one reference take, using chroma
  features (pitch-class energy every 50 ms) and subsequence dynamic time warping. Each take's music,
  with silence trimmed, is located inside the reference, so partial takes land in the right place. Each take
  is also aligned to a second full take as a cross-check, which produces the confidence ratings.
- `sync_template.html` is the player. The script injects the alignment data and writes `sync.html` into
  the user's project folder. The page plays the original audio files through relative paths. It's offline
  and self-contained apart from the audio, and saves edits in the browser's localStorage.
- Outputs in the project folder: `sync.html`, `sync_report.csv`, `takes.csv` (written only if it didn't exist), and
  `.take-sync-cache/`.

Command: `python3 take_sync.py PROJECT_FOLDER [--songs NAME ...] [--title TEXT] [--workers N]`

## Ground rules

1. **Never modify, move, rename, re-encode or delete the user's audio files.** The tool only reads them.
   If files need organising, propose a plan and get a yes first, and prefer copying over moving. Better still,
   leave the files where they are and point `takes.csv` at them, since `file` accepts any path.
2. Don't edit `take_sync.py` or `sync_template.html` to fix a data problem. Fix `takes.csv` instead.
   Only change the code if the user asks for a feature, and keep `/*__DATA__*/null` in the template intact.
3. The user is probably not technical. Give one step at a time, say what to expect, and explain errors in plain words.
4. Don't upload their recordings anywhere. Everything runs locally.

## If you can run commands (coding agent)

1. Check prerequisites: `python3 --version` (3.9+), `ffmpeg -version`, `python3 -c "import numpy"`.
   If any is missing, tell the user the install command (see README step 1) and ask before installing anything.
2. Find out where the recordings are and how they're named. List the folder; don't open the audio files.
3. Build `takes.csv` (see next section). Either:
   - run the script once on a folder-per-song layout and then refine the `takes.csv` it writes, or
   - write `takes.csv` directly from the existing filenames. This is usually better when the files sit in session
     folders (Day 1, Day 2) rather than song folders.
4. Run the script. Read its output and `sync_report.csv`.
5. Report back: songs and takes aligned, which reference each song used, and which takes are `check` or
   `unverified` (they should listen to those). Then tell them to open `sync.html` in Chrome or Safari.
6. Iterate: if a take is misplaced, try a different reference or add `starts_at_measure`, then re-run. Re-runs are cached and fast.

## If you're in a chat and can't run anything

Walk the user through README steps 1–4, one at a time. Ask them to paste their folder listing (on a Mac,
`ls -R "path/to/folder"` in Terminal) and any take log or notes, then write `takes.csv` for them as text
they can save. Ask them to paste the script's console output and `sync_report.csv` after each run.

## Writing takes.csv

Header (exact): `song,take,file,reference,starts_at_measure,session,note`

- `song`: groups takes for comparison. Every take in a group must be the **same music**: same arrangement and
  key. Don't group a song with a different cut or transposition of it.
- `take`: a short, unique label per song, ideally the take number from the session (`T12`, `12`, `Take 3`).
  Keep it short, because it appears on every bar and in the edit list.
- `file`: path relative to the project folder, or absolute. Quote with `"` if it contains commas.
- `reference`: `yes` on exactly one take per song. This is the most important choice. Pick a clean,
  complete run-through. Avoid takes with false starts, a second attempt in the same file, long talking or
  noodling, or cuts. If the user has picked a "base" take or keeper, use that. If blank, the script picks the
  longest take not much longer than the other long ones, and prints its choice. Check that choice with the user.
- `starts_at_measure`: the bar where the take's music **begins** (first sound). Fill this from filenames
  ("mm 61-81", "from 40", "p. 12 sys 2" converts only if the user knows the bar) or from a take log. Use decimals for
  mid-bar starts (`70.5` = beat 3 of 4/4 bar 70). Only enter values you're confident of. Wrong anchors distort every
  measure estimate. Put uncertain or conflicting info in `note`. The reference row's value means "the reference
  starts at this bar" (default 1). Measure numbers are interpolated linearly between anchors, so they're ±2–3 bars.
- `session` / `note`: free text shown on the take's row.

Spreadsheet apps sometimes save CSVs with odd encodings or semicolons. If the script complains about missing
columns, re-save as "CSV UTF-8 (comma delimited)".

## Reading sync_report.csv

- `kind`: `full` (covers ≥85% of the reference) or `partial`.
- `confidence`:
  - `ref`: the reference itself.
  - `ok`: the second alignment route agrees on the start within 2 s. Trustworthy.
  - `check`: the routes disagree. Shown as striped bars. Could still be right; the user should check by ear.
  - `unverified`: no second full take existed to cross-check against (common for songs where only one take is complete).
- `why` saying "end differs ... (tail/extra material?)" usually means the file has extra playing after the passage.
- `align_cost`: 0 is perfect. Under ~0.2 is good, above ~0.35 is suspicious.

Common fixes, in order:
1. Wrong or poor reference: mark a cleaner complete take as `reference`.
2. A take that contains two attempts: the alignment places only one of them. Suggest the user note which one, or
   ask whether they'd like a trimmed copy made, and only make it with their yes, as a new file.
3. A different arrangement or key mixed into the song group: move it to its own `song` name.
4. Mostly talking or silence: the tool can't place it, and that's expected.

## Limits worth saying out loud

- It aligns by pitch content. It doesn't judge tuning, wrong notes or performance quality.
- Unpitched percussion, heavily distorted sound and very sparse textures align poorly.
- Memory grows with (take length × reference length). For pieces over ~15 minutes use `--workers 1`.
- `sync.html` must stay in the project folder next to the audio paths it references. To share a session with
  someone else, they need the whole folder, or they run the tool themselves.
- AIFF doesn't play in Chrome. Use Safari or convert copies to WAV.
- Edits live in that browser's localStorage. Exporting the edit list CSV is the durable record.

## Edit list export columns (for explaining to the user or their editor)

`song, segment, take, file, ref_in, ref_out, est_measure_in, est_measure_out, take_in, take_out, take_in_sec,
take_out_sec, gain_db, covered, note`. `take_in`/`take_out` are the times **in that take's original file**.
That's what an editor needs. `gain_db` is the level offset that matches the take to the reference.
`covered = NO` means the chosen take doesn't contain that whole stretch.
