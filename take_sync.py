#!/usr/bin/env python3
"""Take Sync: line up every take of a piece against one reference take, then audition and
choose between them in a browser page (sync.html).

Usage
    python3 take_sync.py PROJECT_FOLDER
    python3 take_sync.py PROJECT_FOLDER --songs "Song A" "Song B"     (only some songs)
    python3 take_sync.py PROJECT_FOLDER --title "My Album Sessions"

PROJECT_FOLDER holds your recordings. Two ways to describe them:
  1. Quick start: one subfolder per song, audio files inside it.
         My Project/Song A/take 1.wav, take 2.wav ...
     The first run writes My Project/takes.csv from those folders (longest take = reference).
     Edit that file and re-run to improve the results.
  2. Write takes.csv yourself (see README.md for the columns). Files can live anywhere.

Outputs (in PROJECT_FOLDER): sync.html, sync_report.csv, .take-sync-cache/ (safe to delete).
Your audio files are only read, never changed.

How it works
- Each take becomes a chroma sequence (which pitch classes sound, every 50 ms). This is used
  ONLY to line takes up; nothing here judges intonation or wrong notes.
- Each take's music (silence trimmed) is found inside the reference with subsequence DTW, so
  partial takes and pickups land where they belong.
- Cross-check: every take is also aligned to a second full take, and the two answers are compared.
- Measure numbers are ESTIMATES, interpolated from "starts_at_measure" values in takes.csv.

Needs: Python 3.9+, numpy, and ffmpeg on the PATH.
"""
import argparse, csv, hashlib, json, os, re, shutil, subprocess, sys, urllib.parse
from concurrent.futures import ProcessPoolExecutor

try:
    import numpy as np
except ImportError:
    sys.exit("numpy is missing. Install it with:  python3 -m pip install numpy")

HERE = os.path.dirname(os.path.abspath(__file__))
SR, NFFT, HOP = 22050, 4096, 1102          # hop ~ 50 ms
FPS = SR / HOP
AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus"}
COLUMNS = ["song", "take", "file", "reference", "starts_at_measure", "session", "note"]


# ---------- features ----------
def chroma(path, cache):
    os.makedirs(cache, exist_ok=True)
    st = os.stat(path)
    key = hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}|{NFFT}|{HOP}|v3".encode()).hexdigest()[:16]
    cp = os.path.join(cache, key + ".npz")
    if os.path.exists(cp):
        z = np.load(cp)
        return z["C"], z["E"]
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                          capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"ffmpeg could not read {path}: {proc.stderr.decode(errors='replace').strip()[:300]}")
    x = np.frombuffer(proc.stdout, dtype=np.float32)
    x = np.concatenate([np.zeros(NFFT // 2, np.float32), x, np.zeros(NFFT, np.float32)])
    n = 1 + (len(x) - NFFT) // HOP
    win = np.hanning(NFFT).astype(np.float32)
    f = np.fft.rfftfreq(NFFT, 1 / SR)
    band = (f >= 60) & (f <= 4200)
    pc = (np.round(69 + 12 * np.log2(f[band] / 440)).astype(int)) % 12
    W = np.zeros((band.sum(), 12), np.float32)
    W[np.arange(band.sum()), pc] = 1
    C = np.empty((n, 12), np.float32)
    E = np.empty(n, np.float32)
    fr = np.lib.stride_tricks.sliding_window_view(x, NFFT)[::HOP][:n]
    for s in range(0, n, 2000):
        m = np.abs(np.fft.rfft(fr[s:s + 2000] * win, axis=1)).astype(np.float32)
        E[s:s + 2000] = np.sqrt((m ** 2).sum(1))
        C[s:s + 2000] = (m[:, band] ** 2) @ W
    # smooth 200 ms, normalise; near-silent frames become neutral so silence matches silence
    k = np.ones(4, np.float32) / 4
    C = np.stack([np.convolve(C[:, i], k, mode="same") for i in range(12)], 1)
    floor = np.percentile(E, 10)
    C = np.log1p(100 * C / (C.max() + 1e-9))
    C = C - C.min(axis=1, keepdims=True)
    C = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-9)
    C[E < floor * 3] = 0
    np.savez(cp, C=C, E=E)
    return C, E


def features_job(args):
    path, cache = args
    C, _ = chroma(path, cache)
    return path, len(C) / FPS


def music_start(E):
    """First frame of sustained sound: 15 dB over the file's quiet floor for >= 0.5 s."""
    db = 20 * np.log10(E + 1e-9)
    on = db > np.percentile(db, 10) + 15
    run = int(0.5 * FPS)
    c = np.convolve(on.astype(int), np.ones(run, int), mode="valid")
    return int(np.argmax(c >= run * 0.9))


def music_end(E):
    return len(E) - 1 - music_start(E[::-1])


# ---------- DTW ----------
W = np.float32(0.15)  # off-diagonal step penalty


def dtw(X, Y, subseq):
    """Rows = take frames (X), cols = reference frames (Y). Returns path [(i, j)], mean cost."""
    n, m = len(X), len(Y)
    ptr = np.empty((n, m), np.int8)  # 0 diag, 1 up, 2 left
    c0 = 1 - Y @ X[0]
    Dp = c0.copy() if subseq else np.cumsum(c0)
    ptr[0] = 2
    ptr[0, 0] = 0
    if subseq:
        ptr[0] = 0  # free start anywhere in reference
    inf = np.float32(np.inf)
    for i in range(1, n):
        c = 1 - Y @ X[i]
        diag = np.concatenate(([inf], Dp[:-1]))
        up = Dp + W
        A = np.minimum(diag, up)
        S = np.cumsum(c + W)
        B = A + c - S
        M = np.minimum.accumulate(B)
        D = S + M
        left = np.concatenate(([False], M[1:] < B[1:]))
        p = np.where(up < diag, 1, 0).astype(np.int8)
        p[left] = 2
        ptr[i] = p
        Dp = D
    j = int(np.argmin(Dp)) if subseq else m - 1
    i = n - 1
    total = float(Dp[j])
    path = [(i, j)]
    while i > 0 or (j > 0 and not subseq):
        p = ptr[i, j]
        if i == 0:
            if subseq:
                break
            j -= 1
        elif p == 0:
            i, j = i - 1, j - 1
        elif p == 1:
            i -= 1
        else:
            j -= 1
        if j < 0:
            break
        path.append((i, j))
    path.reverse()
    return path, total / len(path)


def align(args):
    """Subsequence-align the take's music (silence trimmed) inside the reference."""
    song, take, path, ref_path, cache = args
    X, EX = chroma(path, cache)
    Y, EY = chroma(ref_path, cache)
    s0, s1 = music_start(EX), music_end(EX) + 1
    if s1 - s0 < FPS:  # under a second of sound: align the whole file
        s0, s1 = 0, len(X)
    p, _ = dtw(X[s0:s1], Y, subseq=True)
    p = np.array(p)
    tt = (p[:, 0] + s0) / FPS
    rt = np.maximum.accumulate(p[:, 1] / FPS)
    tt = np.concatenate(([tt[0] - 600], tt, [tt[-1] + 600]))
    rt = np.concatenate(([rt[0] - 600], rt, [rt[-1] + 600]))
    grid = np.arange(0, len(X) / FPS, 0.25)
    rmap = np.interp(grid, tt, rt)
    ex = EX[p[:, 0] + s0]; ey = EY[p[:, 1]]
    ok = (ex > np.percentile(EX, 10) * 3) & (ey > np.percentile(EY, 10) * 3)
    sim = (X[p[:, 0] + s0] * Y[p[:, 1]]).sum(1)
    cost = float(1 - sim[ok].mean()) if ok.sum() > 20 else 1.0
    gain = float(np.median(20 * np.log10(ey[ok] / ex[ok]))) if ok.sum() > 20 else 0.0
    return dict(song=song, take=take, cost=round(cost, 3), gain=round(gain, 1), start_take=s0 / FPS,
                end_take=s1 / FPS, start_ref=float(rt[1]), end_ref=float(rt[-2]),
                ref_lo=float(max(0, rt[1])), ref_hi=float(rt[-2]), dur=len(X) / FPS,
                map=[[round(a, 2), round(b, 2)] for a, b in zip(grid, rmap)])


def via(m, t):
    m = np.array(m)
    return float(np.interp(t, m[:, 0], m[:, 1]))


# ---------- measures ----------
def measure_map(ref_start, base, anchors_t):
    pts = sorted([(ref_start, base)] + anchors_t)
    keep = []
    for t, m in pts:
        if not keep or (m > keep[-1][1] and t > keep[-1][0] + 0.5):
            keep.append((t, m))
    return [k[0] for k in keep], [k[1] for k in keep]


def est_measure(t, T, M):
    if len(T) < 2:
        return None
    if t <= T[-1]:
        return float(np.interp(t, T, M))
    return M[-1] + (t - T[-1]) * (M[-1] - M[-2]) / (T[-1] - T[-2])


def fmt(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def natkey(s):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(s))]


# ---------- takes.csv ----------
def scan_folders(project):
    """Quick start: each subfolder of the project = one song; each audio file in it = one take."""
    rows = []
    for d in sorted(os.listdir(project), key=natkey):
        full = os.path.join(project, d)
        if d.startswith(".") or not os.path.isdir(full):
            continue
        for root, dirs, files in os.walk(full):
            dirs[:] = sorted((x for x in dirs if not x.startswith(".")), key=natkey)
            for fn in sorted(files, key=natkey):
                if os.path.splitext(fn)[1].lower() in AUDIO_EXT and not fn.startswith("."):
                    rel = os.path.relpath(os.path.join(root, fn), project)
                    rows.append(dict(song=d, take=os.path.splitext(fn)[0], file=rel, reference="",
                                     starts_at_measure="", session="", note=""))
    return rows


def read_takes(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"{path} has no rows.")
    missing = {"song", "take", "file"} - set(rows[0].keys())
    if missing:
        sys.exit(f"{path} is missing column(s): {', '.join(sorted(missing))}. Needed: song, take, file.")
    out = []
    for r in rows:
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        if r.get("song") and r.get("take") and r.get("file"):
            out.append({c: r.get(c, "") for c in COLUMNS})
    return out


def write_takes(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in COLUMNS} for r in rows)


def yes(v):
    return v.strip().lower() in {"y", "yes", "x", "1", "true", "ref", "reference"}


def main():
    ap = argparse.ArgumentParser(description="Line up takes of the same piece and build sync.html.")
    ap.add_argument("project", help="folder with your recordings (and takes.csv)")
    ap.add_argument("--songs", nargs="+", help="only these songs")
    ap.add_argument("--title", help="page title (default: the project folder's name)")
    ap.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 1)),
                    help="parallel jobs (lower it if you run out of memory)")
    a = ap.parse_args()

    project = os.path.abspath(os.path.expanduser(a.project))
    if not os.path.isdir(project):
        sys.exit(f"Not a folder: {project}")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is not installed or not on the PATH. On a Mac: brew install ffmpeg  "
                 "(Windows: winget install ffmpeg; Linux: your package manager).")
    cache = os.path.join(project, ".take-sync-cache")
    title = a.title or os.path.basename(project)

    tpath = os.path.join(project, "takes.csv")
    if os.path.exists(tpath):
        rows = read_takes(tpath)
        print(f"Using {tpath} ({len(rows)} takes).")
    else:
        rows = scan_folders(project)
        if not rows:
            sys.exit("No takes.csv and no song subfolders with audio files in them. See README.md.")
        print(f"No takes.csv found, so I read the subfolders: {len(rows)} audio files in "
              f"{len({r['song'] for r in rows})} song folder(s).")

    filepath = lambda r: r["file"] if os.path.isabs(os.path.expanduser(r["file"])) else os.path.join(project, r["file"])
    for r in rows:
        r["_path"] = os.path.expanduser(filepath(r))
    bad = [r["_path"] for r in rows if not os.path.isfile(r["_path"])]
    if bad:
        sys.exit("These files from takes.csv don't exist:\n  " + "\n  ".join(bad[:20]))

    by_song = {}
    for r in rows:
        if not a.songs or r["song"] in a.songs:
            by_song.setdefault(r["song"], []).append(r)
    for song, rs in list(by_song.items()):
        labels = [r["take"] for r in rs]
        dup = sorted({x for x in labels if labels.count(x) > 1})
        if dup:
            sys.exit(f'"{song}": take name(s) used twice: {", ".join(dup)}. Each take in a song needs its own name.')
        if len(rs) < 2:
            print(f'  skipping "{song}": only one take')
            del by_song[song]
    if not by_song:
        sys.exit("Nothing to align (need at least two takes of a song).")

    # 1. decode + features for every file (cached), which also gives durations
    paths = sorted({r["_path"] for rs in by_song.values() for r in rs})
    print(f"Reading {len(paths)} files with {a.workers} worker(s)... (first run is the slow one)")
    with ProcessPoolExecutor(a.workers) as ex:
        dur = dict(ex.map(features_job, [(p, cache) for p in paths]))

    # 2. choose references: the row marked reference, else the longest take
    refs = {}
    for song, rs in by_song.items():
        marked = [r for r in rs if yes(r["reference"])]
        if len(marked) > 1:
            sys.exit(f'"{song}": more than one take marked as reference ({", ".join(r["take"] for r in marked)}).')
        if marked:
            ref = marked[0]
        else:
            # longest take of normal length: a file much longer than the other long takes usually holds
            # extra material (a second run, talking), which makes a poor reference
            L = sorted((dur[r["_path"]] for r in rs), reverse=True)
            top = L[:max(2, (len(L) + 1) // 2)]
            cap = 1.25 * float(np.median(top))
            ref = max((r for r in rs if dur[r["_path"]] <= cap), key=lambda r: dur[r["_path"]])
            print(f'  "{song}": no reference marked, picked {ref["take"]} ({fmt(dur[ref["_path"]])}). '
                  "Mark a clean complete take in takes.csv if that's wrong.")
        refs[song] = ref["take"]
        if not marked:
            ref["reference"] = "yes"
    if not os.path.exists(tpath):
        write_takes(tpath, [r for rs in by_song.values() for r in rs])
        print(f"Wrote {tpath}. Check it: fix the reference choice, add measure numbers, then re-run.")

    # 3. align every take to its reference
    jobs, meta = [], {}
    for song, rs in by_song.items():
        refp = next(r["_path"] for r in rs if r["take"] == refs[song])
        for r in rs:
            meta[(song, r["take"])] = r
            jobs.append((song, r["take"], r["_path"], refp, cache))
    print(f"Aligning {len(jobs)} takes...")
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(align, jobs))
    R = {(r["song"], r["take"]): r for r in res}

    # 4. cross-check against a second full take
    alts, jobs2 = {}, []
    for song, rs in by_song.items():
        ref = R[(song, refs[song])]
        span = ref["end_ref"] - ref["start_ref"]
        for x in rs:
            r = R[(song, x["take"])]
            r["full"] = (r["end_ref"] - r["start_ref"]) >= 0.85 * span
        fulls = [R[(song, x["take"])] for x in rs if x["take"] != refs[song] and R[(song, x["take"])]["full"]]
        if fulls:
            alt = min(fulls, key=lambda r: r["cost"])
            alts[song] = alt["take"]
            ap_ = meta[(song, alt["take"])]["_path"]
            jobs2 += [(song, x["take"], x["_path"], ap_, cache) for x in rs if x["take"] not in (refs[song], alt["take"])]
    if jobs2:
        print(f"Cross-checking {len(jobs2)} takes...")
        with ProcessPoolExecutor(a.workers) as ex:
            for r2 in ex.map(align, jobs2):
                r = R[(r2["song"], r2["take"])]
                am = R[(r2["song"], alts[r2["song"]])]["map"]
                r["d_start"] = abs(via(am, r2["start_ref"]) - r["start_ref"])
                r["d_end"] = abs(via(am, r2["end_ref"]) - r["end_ref"])

    # 5. measures, confidence, output
    def num(v):
        try:
            return float(v)
        except ValueError:
            return None

    out_songs, report = [], []
    for song, rs in by_song.items():
        refr = R[(song, refs[song])]
        refrow = meta[(song, refs[song])]
        base = num(refrow["starts_at_measure"]) or 1.0
        A = [(R[(song, x["take"])]["start_ref"], num(x["starts_at_measure"])) for x in rs
             if x["take"] != refs[song] and num(x["starts_at_measure"]) is not None]
        T, M = measure_map(refr["start_ref"], base, A)
        takes = []
        for x in sorted(rs, key=lambda x: natkey(x["take"])):
            r = R[(song, x["take"])]
            est = est_measure(r["start_ref"], T, M)
            if x["take"] == refs[song]:
                conf, why = "ref", "reference"
            elif x["take"] == alts.get(song):
                conf, why = ("ok", "cross-check take") if r["cost"] < 0.3 else ("check", "high alignment cost")
            elif "d_start" in r:
                conf = "ok" if r["d_start"] <= 2.0 else "check"
                why = (f"start: 2nd route agrees within {r['d_start']:.1f} s" if conf == "ok"
                       else f"start: 2nd route differs by {r['d_start']:.1f} s")
                if r["d_end"] > 4.0:
                    why += f"; end differs by {r['d_end']:.0f} s (tail/extra material?)"
            else:
                conf, why = "unverified", "no second full take to cross-check against"
            rel = os.path.relpath(x["_path"], project)
            takes.append(dict(take=x["take"], take_label=x["take"], day=x["session"], partial=not r["full"],
                              src=urllib.parse.quote(rel.replace(os.sep, "/")), file=os.path.basename(x["_path"]),
                              start_take=round(r["start_take"], 2), start_ref=round(r["start_ref"], 2),
                              ref_lo=round(r["ref_lo"], 2), ref_hi=round(r["ref_hi"], 2), dur=round(r["dur"], 2),
                              est_measure=None if est is None else round(est, 1), label=x["note"], cost=r["cost"],
                              conf=conf, why=why, gain=r["gain"], is_ref=x["take"] == refs[song], map=r["map"]))
            report.append([song, x["take"], x["session"], "full" if r["full"] else "partial",
                           fmt(r["start_take"]), fmt(r["start_ref"]), fmt(r["end_ref"]),
                           "" if est is None else f"~{est:.0f}", x["note"], conf, why, r["cost"]])
        out_songs.append(dict(song=song, ref=refs[song], ref_dur=refr["dur"], measures=[T, M], takes=takes))

    with open(os.path.join(project, "sync_report.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["song", "take", "session", "kind", "music_starts_in_take_at", "starts_at_in_reference",
                    "ends_at_in_reference", "est_start_measure", "note", "confidence", "why", "align_cost"])
        w.writerows(report)
    tpl = open(os.path.join(HERE, "sync_template.html"), encoding="utf-8").read()
    data = json.dumps(dict(title=title, songs=out_songs), ensure_ascii=False).replace("</", "<\\/")
    out = os.path.join(project, "sync.html")
    open(out, "w", encoding="utf-8").write(tpl.replace("/*__DATA__*/null", data))
    checks = sum(1 for t in report if t[9] == "check")
    print(f"Done: {len(res)} takes aligned -> {out}")
    if checks:
        print(f"{checks} take(s) marked 'check' (striped bars): listen to those by ear. Details in sync_report.csv.")
    print("Open sync.html in Chrome or Safari. Keep it in this folder: it plays the audio from here.")


if __name__ == "__main__":
    main()
