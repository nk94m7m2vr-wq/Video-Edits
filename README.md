# Video-Edits

A video editing system you drive by chatting with Claude:

| Tool | Job in the pipeline | How Claude reaches it |
| --- | --- | --- |
| **Tella** | Record your screen and camera, trim, get transcripts, export MP4 | Tella MCP connector (`.mcp.json`) |
| **Epidemic Sound** | Find and download licensed music and sound effects | Epidemic Sound MCP connector (`.mcp.json`) |
| **HyperFrames** | Animated intros, outros, titles and lower-thirds written as HTML, rendered to MP4 | Claude Code plugin (`.claude/settings.json`) + `motion/` project |
| **FFmpeg** | Remove silence, add captions, join clips, duck music under speech, normalise loudness | `scripts/vedit.py` |

```
Tella recording ──► media/raw/ ──┐
Epidemic Sound track ─► media/music/ ──┤
HyperFrames intro/outro ─► media/work/ ──┤
                                     ▼
          scripts/vedit.py build project.json
  prep → cut silence → captions → intro+main+outro → music (ducked) → SFX → -14 LUFS
                                     ▼
                         output/<name>.mp4 + thumbnail
```

---

## Step-by-step setup

### Step 1: Install the tools (once per computer)

| | macOS | Windows | Linux |
| --- | --- | --- | --- |
| FFmpeg | `brew install ffmpeg` | `winget install Gyan.FFmpeg` | `sudo apt install ffmpeg` |
| Node.js 22+ | `brew install node` | `winget install OpenJS.NodeJS` | [nodejs.org](https://nodejs.org) |
| Python 3 | preinstalled / `brew install python` | `winget install Python.Python.3.12` | preinstalled |
| Claude Code | `npm install -g @anthropic-ai/claude-code` | same | same |

Then clone the repo and run the checker:

```bash
git clone https://github.com/nk94m7m2vr-wq/Video-Edits.git
cd Video-Edits
./scripts/setup.sh
```

On Windows, run commands in WSL or Git Bash.

### Step 2: Accounts you need

- **Tella:** any plan. You sign in through the browser in Step 3.
- **Epidemic Sound:** a paid subscription. The MCP server is in beta and doesn't change your licence.
  Create an API key under **Account settings → API keys**. Keys expire after one year.
- **HyperFrames:** no account needed. It's open source and renders on your computer.

### Step 3: Turn on the connectors

**In Claude Code (this repo):** the repo already includes the config:

- `.mcp.json` registers the **Tella** and **Epidemic Sound** MCP servers.
- `.claude/settings.json` pre-approves both servers and auto-installs the **HyperFrames** plugin from the `heygen-com/hyperframes` marketplace.

You only need to supply the credentials:

```bash
cp .env.example .env            # paste your Epidemic Sound key into .env
set -a; source .env; set +a     # export it to this shell
claude                          # start Claude Code in the repo
```

Inside Claude Code:

1. Type `/mcp`, select **tella**, choose **Authenticate**, and sign in to Tella in the browser.
2. In the same `/mcp` list, **epidemic-sound** should show *connected*. If it fails, the key isn't exported in this shell.
3. If Claude Code asks whether to trust the HyperFrames plugin, accept. To install it by hand instead:
   `claude plugin marketplace add heygen-com/hyperframes` then `claude plugin install hyperframes@hyperframes`.

**In the Claude app (claude.ai, desktop or mobile):** go to **Settings → Connectors → Browse**, then search for and connect
**Tella**, **Epidemic Sound** and **HyperFrames by HeyGen**. Each one opens its own sign-in window.
The HyperFrames connector renders in HeyGen's cloud. The `motion/` project here renders on your computer.

### Step 4: Make your branded intro and outro (HyperFrames)

```bash
cd motion
npm run dev       # live preview in the browser; edit index.html or compositions/outro.html
cd ..
python3 scripts/vedit.py render-motion media/work/intro.mp4 \
  --variables '{"title":"How I Edit Videos","subtitle":"Episode 01","accent":"#7c5cff"}'
python3 scripts/vedit.py render-motion media/work/outro.mp4 \
  --composition compositions/outro.html --variables '{"cta":"Subscribe for more"}'
```

You can also ask Claude: *"Using /hyperframes, make a 5-second kinetic title for 'How I Edit Videos' in motion/"*.
GSAP is bundled in `motion/assets/vendor/`, so renders work offline.

### Step 5: Record in Tella, then export

Record as usual. Then either export the MP4 from Tella yourself into `media/raw/`, or ask Claude:

> "Find my latest Tella video, remove filler words, and export it as 1080p. Also give me its transcript as an .srt in media/raw/."

### Step 6: Pick music from Epidemic Sound

Ask Claude:

> "Search Epidemic Sound for an upbeat, minimal lo-fi track around 100 BPM with no vocals, and download it to media/music/track.mp3."

Put sound effects (whooshes, clicks) in `media/sfx/`.

### Step 7: Build the final video (FFmpeg)

```bash
cp project.example.json project.json   # set source / music / captions paths
python3 scripts/vedit.py build project.json
```

The build writes `output/<name>.mp4` plus a `.jpg` thumbnail. Intermediate files go in `media/work/`.

**`project.json` fields**

| Field | Meaning |
| --- | --- |
| `source` | Your Tella export |
| `trim_start` / `trim_end` | Seconds to keep from the source (`null` keeps the whole recording) |
| `silence_cut` | Remove pauses: `threshold` sets what counts as quiet, `min` is the shortest pause to cut, `pad` is the breathing room kept |
| `captions` | `.srt`/`.vtt` to burn in (`null` to skip) |
| `intro` / `outro` | HyperFrames renders from Step 4 (`null` to skip) |
| `music` | `db` sets the bed volume. `duck: true` lowers the music when you speak |
| `sfx` | `[{"file": "media/sfx/whoosh.wav", "at": 4.0, "db": -6}]` |
| `lufs` | Loudness target: -14 for YouTube and social media, -16 for podcasts |

### Individual tools

```bash
python3 scripts/vedit.py probe  clip.mp4
python3 scripts/vedit.py prep   in.mp4 out.mp4 --start 3 --end 95
python3 scripts/vedit.py cut-silence in.mp4 out.mp4 --threshold -40dB --min 0.5
python3 scripts/vedit.py captions in.mp4 subs.srt out.mp4
python3 scripts/vedit.py concat out.mp4 intro.mp4 main.mp4 outro.mp4
python3 scripts/vedit.py music  in.mp4 track.mp3 out.mp4 --music-db -20
python3 scripts/vedit.py sfx    in.mp4 whoosh.wav out.mp4 --at 4.2
python3 scripts/vedit.py loudnorm in.mp4 out.mp4 --lufs -14
python3 scripts/vedit.py thumbnail in.mp4 thumb.jpg --at 6
```

---

## One-prompt workflow

Once the connectors are on, you can run the whole pipeline in one Claude Code message:

> "Pull my newest Tella video and its transcript into media/raw. Find a calm Epidemic Sound track that fits its tone.
> Render an intro titled after the video. Then build it with captions and save it to output/."

## Troubleshooting

- **Epidemic Sound 401:** the key isn't exported in the shell you started `claude` from, or the key has expired.
- **Tella tools missing:** run `/mcp`, choose **tella**, then **Authenticate** again.
- **HyperFrames render says GSAP failed:** keep the local `assets/vendor/gsap.min.js` script tag. Some networks block CDNs.
- **Silence cut removes too much or too little:** lower the threshold (`-40dB`) for quiet microphones, or raise `min` to keep short pauses.
- Footage, music and renders are git-ignored on purpose. They're large, and Epidemic Sound tracks are licensed to you, not to the repo.
