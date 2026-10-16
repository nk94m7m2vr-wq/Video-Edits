#!/usr/bin/env python3
"""vedit — FFmpeg toolkit for the Video-Edits pipeline.

Tella recording -> prep -> silence cut -> Epidemic Sound music bed (ducked)
-> HyperFrames intro/outro -> loudness-normalised final MP4.

Run `python3 scripts/vedit.py -h` for the subcommands, or
`python3 scripts/vedit.py build project.json` for the whole pipeline.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "media" / "work"

# Every clip is conformed to this before it is combined with anything else.
DEFAULT_FORMAT = {"width": 1920, "height": 1080, "fps": 30, "sample_rate": 48000}


def run(cmd):
    print("+ " + " ".join(str(c) for c in cmd), file=sys.stderr)
    subprocess.run([str(c) for c in cmd], check=True)


def ffmpeg(*args):
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y", *args])


def duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True).stdout.strip()
    return float(out)


def has_audio(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True).stdout.strip()
    return bool(out)


def encode_args(crf=18):
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart"]


# --- subcommands -----------------------------------------------------------

def cmd_probe(a):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
         "-of", "json", a.input], check=True, capture_output=True, text=True).stdout
    print(out)


def cmd_prep(a, fmt=DEFAULT_FORMAT):
    """Conform any clip to a common size/fps/audio layout (letterboxed, never stretched)."""
    w, h, fps, sr = fmt["width"], fmt["height"], fmt["fps"], fmt["sample_rate"]
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}")
    args = []
    if a.start is not None:
        args += ["-ss", str(a.start)]
    if a.end is not None:
        args += ["-to", str(a.end)]
    args += ["-i", a.input]
    if has_audio(a.input):
        args += ["-map", "0:v:0", "-map", "0:a:0"]
    else:
        # Silent source (e.g. a HyperFrames render): add a silent track so concat works.
        args += ["-f", "lavfi", "-i", f"anullsrc=r={sr}:cl=stereo",
                 "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    ffmpeg(*args, "-vf", vf, "-ar", str(sr), "-ac", "2", *encode_args(), a.output)


def detect_silence(path, threshold, min_len):
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af",
         f"silencedetect=noise={threshold}:d={min_len}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def cmd_cut_silence(a):
    """Remove pauses longer than --min seconds, keeping --pad seconds either side of speech."""
    total = duration(a.input)
    silences = detect_silence(a.input, a.threshold, a.min)
    keep, cursor = [], 0.0
    for start, end in silences:
        end = total if end is None else end
        cut_from, cut_to = max(start + a.pad, 0), min(end - a.pad, total)
        if cut_to - cut_from <= 0.05:
            continue
        if cut_from > cursor:
            keep.append((cursor, cut_from))
        cursor = cut_to
    if cursor < total:
        keep.append((cursor, total))
    if not keep:
        sys.exit("Everything is silent — lower --threshold (e.g. -45dB).")
    removed = total - sum(e - s for s, e in keep)
    print(f"Keeping {len(keep)} segments, removing {removed:.1f}s of {total:.1f}s", file=sys.stderr)

    # Select the kept ranges and rebuild timestamps; one pass, frame-accurate.
    expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in keep)
    script = WORK / (Path(a.output).stem + ".silencecut.txt")
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v];"
        f"[0:a]aselect='{expr}',asetpts=N/SR/TB[a]")
    ffmpeg("-i", a.input, "-filter_complex_script", script,
           "-map", "[v]", "-map", "[a]", *encode_args(), a.output)


def cmd_music(a):
    """Lay a looped music bed under the voice, ducked whenever someone speaks."""
    length = duration(a.input)
    fade_out = min(a.fade, length / 2)
    graph = (
        f"[1:a]volume={a.music_db}dB,atrim=0:{length:.3f},"
        f"afade=t=in:d={min(1.0, length / 4):.2f},"
        f"afade=t=out:st={length - fade_out:.3f}:d={fade_out:.2f}[bed];"
        "[0:a]asplit=2[voice][key];"
    )
    if a.no_duck:
        graph += "[bed]anull[ducked];"
    else:
        graph += ("[bed][key]sidechaincompress=threshold=0.03:ratio=8:"
                  "attack=20:release=400[ducked];")
    graph += "[voice][ducked]amix=inputs=2:duration=first:normalize=0[a]"
    ffmpeg("-i", a.input, "-stream_loop", "-1", "-i", a.music,
           "-filter_complex", graph, "-map", "0:v", "-map", "[a]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
           a.output)


def cmd_sfx(a):
    """Drop a sound effect in at --at seconds."""
    delay = int(a.at * 1000)
    graph = (f"[1:a]volume={a.db}dB,adelay={delay}|{delay}[fx];"
             "[0:a][fx]amix=inputs=2:duration=first:normalize=0[a]")
    ffmpeg("-i", a.input, "-i", a.sfx, "-filter_complex", graph,
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           a.output)


def cmd_concat(a, fmt=DEFAULT_FORMAT):
    """Join clips (each is conformed first, so mixed sources are fine)."""
    WORK.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, clip in enumerate(a.inputs):
        part = WORK / f"concat_{i:02d}_{Path(clip).stem}.mp4"
        cmd_prep(argparse.Namespace(input=clip, output=str(part), start=None, end=None), fmt)
        parts.append(part)
    args, streams = [], ""
    for i, p in enumerate(parts):
        args += ["-i", p]
        streams += f"[{i}:v][{i}:a]"
    graph = f"{streams}concat=n={len(parts)}:v=1:a=1[v][a]"
    ffmpeg(*args, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
           *encode_args(), a.output)


def cmd_loudnorm(a):
    """Two-pass EBU R128 loudness normalisation (-14 LUFS suits YouTube/socials)."""
    target = f"I={a.lufs}:TP=-1.5:LRA=11"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", a.input, "-af",
         f"loudnorm={target}:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    m = json.loads(proc.stderr[proc.stderr.rindex("{"):proc.stderr.rindex("}") + 1])
    second = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
              f"offset={m['target_offset']}:linear=true")
    ffmpeg("-i", a.input, "-af", second, "-ar", "48000", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", a.output)


def cmd_captions(a):
    """Burn an .srt/.vtt (e.g. exported from Tella) into the video."""
    sub = Path(a.subtitles).resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    style = f"FontName=Inter,FontSize={a.size},Outline=2,Shadow=0,MarginV=60"
    ffmpeg("-i", a.input, "-vf", f"subtitles='{sub}':force_style='{style}'",
           *encode_args(), a.output)


def cmd_thumbnail(a):
    ffmpeg("-ss", str(a.at), "-i", a.input, "-frames:v", "1", "-q:v", "2", a.output)


def cmd_render_motion(a):
    """Render the HyperFrames project in motion/ to an MP4."""
    out = Path(a.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["npx", "--yes", "hyperframes@0.8.163", "render", "--output", str(out)]
    if a.composition:
        cmd += ["--composition", a.composition]
    if a.variables:
        cmd += ["--variables", a.variables]
    subprocess.run(cmd, cwd=ROOT / a.project, check=True)


def cmd_build(a):
    """Run the whole pipeline from a project JSON file (see project.example.json)."""
    cfg = json.loads(Path(a.config).read_text())
    base = Path(a.config).resolve().parent
    rel = lambda p: str((base / p).resolve()) if p else None
    fmt = {**DEFAULT_FORMAT, **cfg.get("format", {})}
    name = cfg.get("name", "video")
    WORK.mkdir(parents=True, exist_ok=True)
    step = lambda s: str(WORK / f"{name}.{s}.mp4")

    src = rel(cfg["source"])
    current = step("01-prep")
    cmd_prep(argparse.Namespace(input=src, output=current, start=cfg.get("trim_start"),
                                end=cfg.get("trim_end")), fmt)

    sc = cfg.get("silence_cut")
    if sc and sc.get("enabled", True):
        nxt = step("02-cut")
        cmd_cut_silence(argparse.Namespace(input=current, output=nxt,
                                           threshold=sc.get("threshold", "-35dB"),
                                           min=sc.get("min", 0.6), pad=sc.get("pad", 0.15)))
        current = nxt

    if cfg.get("captions"):
        nxt = step("03-captions")
        cmd_captions(argparse.Namespace(input=current, output=nxt,
                                        subtitles=rel(cfg["captions"]), size=22))
        current = nxt

    if cfg.get("intro") or cfg.get("outro"):
        nxt = step("04-joined")
        clips = [rel(c) for c in (cfg.get("intro"), current, cfg.get("outro")) if c]
        cmd_concat(argparse.Namespace(inputs=clips, output=nxt), fmt)
        current = nxt

    music = cfg.get("music")
    if music and music.get("file"):
        nxt = step("05-music")
        cmd_music(argparse.Namespace(input=current, music=rel(music["file"]), output=nxt,
                                     music_db=music.get("db", -18), fade=music.get("fade", 2.0),
                                     no_duck=not music.get("duck", True)))
        current = nxt

    for i, fx in enumerate(cfg.get("sfx", [])):
        nxt = step(f"06-sfx{i}")
        cmd_sfx(argparse.Namespace(input=current, sfx=rel(fx["file"]), at=fx["at"],
                                   db=fx.get("db", -6), output=nxt))
        current = nxt

    final = rel(cfg.get("output", f"output/{name}.mp4"))
    Path(final).parent.mkdir(parents=True, exist_ok=True)
    cmd_loudnorm(argparse.Namespace(input=current, output=final, lufs=cfg.get("lufs", -14)))
    if cfg.get("thumbnail_at") is not None:
        cmd_thumbnail(argparse.Namespace(input=final, at=cfg["thumbnail_at"],
                                         output=str(Path(final).with_suffix(".jpg"))))
    print(f"\nDone: {final} ({duration(final):.1f}s)")


def main():
    if not shutil.which("ffmpeg"):
        sys.exit("FFmpeg not found — see README step 1.")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("probe", help="show streams/duration"); s.add_argument("input")
    s.set_defaults(fn=cmd_probe)

    s = sub.add_parser("prep", help="conform to 1080p30 H.264/AAC, optional trim")
    s.add_argument("input"); s.add_argument("output")
    s.add_argument("--start", type=float); s.add_argument("--end", type=float)
    s.set_defaults(fn=cmd_prep)

    s = sub.add_parser("cut-silence", help="remove dead air")
    s.add_argument("input"); s.add_argument("output")
    s.add_argument("--threshold", default="-35dB")
    s.add_argument("--min", type=float, default=0.6, help="shortest pause to cut (s)")
    s.add_argument("--pad", type=float, default=0.15, help="breathing room kept (s)")
    s.set_defaults(fn=cmd_cut_silence)

    s = sub.add_parser("music", help="add a ducked music bed")
    s.add_argument("input"); s.add_argument("music"); s.add_argument("output")
    s.add_argument("--music-db", type=float, default=-18)
    s.add_argument("--fade", type=float, default=2.0)
    s.add_argument("--no-duck", action="store_true")
    s.set_defaults(fn=cmd_music)

    s = sub.add_parser("sfx", help="drop a sound effect at a timestamp")
    s.add_argument("input"); s.add_argument("sfx"); s.add_argument("output")
    s.add_argument("--at", type=float, required=True); s.add_argument("--db", type=float, default=-6)
    s.set_defaults(fn=cmd_sfx)

    s = sub.add_parser("concat", help="join clips (intro, main, outro…)")
    s.add_argument("output"); s.add_argument("inputs", nargs="+")
    s.set_defaults(fn=cmd_concat)

    s = sub.add_parser("loudnorm", help="normalise loudness")
    s.add_argument("input"); s.add_argument("output"); s.add_argument("--lufs", type=float, default=-14)
    s.set_defaults(fn=cmd_loudnorm)

    s = sub.add_parser("captions", help="burn in .srt/.vtt subtitles")
    s.add_argument("input"); s.add_argument("subtitles"); s.add_argument("output")
    s.add_argument("--size", type=int, default=22)
    s.set_defaults(fn=cmd_captions)

    s = sub.add_parser("thumbnail", help="grab a still frame")
    s.add_argument("input"); s.add_argument("output"); s.add_argument("--at", type=float, default=1.0)
    s.set_defaults(fn=cmd_thumbnail)

    s = sub.add_parser("render-motion", help="render a HyperFrames project to MP4")
    s.add_argument("output"); s.add_argument("--project", default="motion")
    s.add_argument("--composition", help="e.g. compositions/outro.html (default: index.html intro)")
    s.add_argument("--variables", help='JSON, e.g. \'{"title":"My Video"}\'')
    s.set_defaults(fn=cmd_render_motion)

    s = sub.add_parser("build", help="run the full pipeline from a project JSON")
    s.add_argument("config"); s.set_defaults(fn=cmd_build)

    a = p.parse_args()
    try:
        a.fn(a)
    except subprocess.CalledProcessError as e:
        sys.exit(f"Command failed ({e.returncode}). See FFmpeg output above.")


if __name__ == "__main__":
    main()
