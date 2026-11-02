# CLAUDE.md — Live Shop Clip

This repo turns one raw vertical talking clip about a shop into a finished live-shopping style promo.
User docs are in README.md (Thai). Reply to the user in Thai, short and plain.

## When the user asks to cut a clip

1. `python3 make.py check` — if anything is ❌, run the installer for their OS (`bash setup.sh` on Mac/Linux,
   `powershell -ExecutionPolicy Bypass -File setup.ps1` on Windows). If `.env` has no `ELEVENLABS_API_KEY`, ask the
   user for it in chat (never invent one) and write it to `.env`.
2. Make sure `input/raw.mp4`, `input/logo.jpg` and the photos referenced in `project.json` exist.
3. `python3 make.py build` once — this transcribes, cuts and writes `work/transcript.txt` + `captions.json`.
4. Edit `project.json` to fit what is actually said in `work/transcript.txt`:
   - `shop` block: real shop facts only (look the page up if the user gives a name; never invent follower counts,
     hours or addresses — ask or leave the field out).
   - `scenes[].when` / `until`: short phrases copied from the transcript, in speaking order. Delete scenes the clip
     doesn't talk about. Every scene type and field is listed in README.md step 5.2.
   - `cut.remove`: phrases where the speaker stumbled and repeated themselves.
   - Product images that aren't the shop's real stock need a `note` saying they are examples.
5. `python3 make.py build` again and fix every `⚠️ ไม่ได้ยินคำว่า` warning.
6. Fix obvious transcription errors in `captions.json` (brand names, shop name), then `python3 make.py render`.
7. QA before handing over: extract a contact sheet of `output/<name>.mp4`
   (`ffmpeg -i output/X.mp4 -vf "fps=1/2.5,scale=216:-1,tile=5x4" -frames:v 1 work/qa.jpg`) and look at it —
   check nothing overlaps the face, captions are readable and every scene appears.

## Rules

- Do not rewrite `make.py` / `template.html` for a normal clip; everything per-clip lives in `project.json`
  and `captions.json`. Change the template only when the user asks for a new look.
- Never commit `input/`, `.env`, `output/` or `work/` (already gitignored).
- `python3 make.py` with no argument regenerates `captions.json` — use `render` after hand edits.
