#!/usr/bin/env python3
"""Live Shop Clip — ตัดคลิปรีวิวร้านแนวไลฟ์สดอัตโนมัติ

    python3 make.py              # ทำครบทุกขั้น: ตัด → ถอดเสียง → ซับ → ประกอบโมชั่น → เรนเดอร์
    python3 make.py render       # แก้ project.json / captions.json แล้วเรนเดอร์ใหม่ (ไม่ถอดเสียงซ้ำ)
    python3 make.py preview      # เปิดดูในเบราว์เซอร์ก่อนเรนเดอร์จริง
    python3 make.py check        # ตรวจว่าติดตั้งเครื่องมือครบ

ทุกอย่างของคลิปตั้งค่าใน project.json — ดู README.md
"""
import glob, html, json, os, re, shutil, subprocess, sys, unicodedata, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_VENV_PY = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
if _VENV_PY.exists() and Path(sys.executable).resolve() != _VENV_PY.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), __file__, *sys.argv[1:]])  # ใช้ Python ของโปรเจกต์ที่ตัวติดตั้งสร้างไว้
WORK = ROOT / 'work'                      # ไฟล์ระหว่างทำ (ลบทิ้งได้)
OUT = ROOT / 'output'
CAPS_FILE = ROOT / 'captions.json'        # ซับที่แก้มือได้
FPS = 30
END_SLATE = 4.0
FILLERS = ('นะคะ', 'นะค่ะ', 'นะครับ', 'นะคับ')
TRAIL = {'นะ', 'ค่ะ', 'คะ', 'ครับ', 'คับ', 'นะคะ', 'นะครับ'}


def die(msg):
    sys.exit(f'\n❌ {msg}\n')


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        die(f'คำสั่งล้มเหลว: {" ".join(map(str, cmd))[:200]}\n{r.stderr[-1500:]}')
    return r


def npx(*args):
    exe = shutil.which('npx') or shutil.which('npx.cmd')
    if not exe:
        die('ไม่พบ Node.js (npx) — รันตัวติดตั้งใน README ขั้นที่ 2 ก่อน')
    env = dict(os.environ)
    shells = glob.glob(str(ROOT / '.browsers' / 'chrome-headless-shell' / '*' / '*' / 'chrome-headless-shell*'))
    shells = [s for s in shells if not s.endswith('.zip')]
    if shells:  # ponytail: system Chrome crops the bottom 87px of a 1920 frame; headless shell doesn't
        env['PRODUCER_HEADLESS_SHELL_PATH'] = shells[0]
    return subprocess.run([exe, *args], cwd=ROOT, env=env)


def load_env():
    f = ROOT / '.env'
    if f.exists():
        for line in f.read_text(encoding='utf-8').splitlines():
            k, _, v = line.partition('=')
            if k.strip() and not k.startswith('#') and v.strip():
                os.environ.setdefault(k.strip(), v.strip())


def load_project():
    p = ROOT / 'project.json'
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        die(f'project.json เขียนผิดรูปแบบ (บรรทัด {e.lineno}): {e.msg}')


def path(p):
    return (ROOT / p).resolve()


def duration(f):
    return float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(f)]).stdout)


# ───────────────────────── 1. ถอดเสียง (ElevenLabs Scribe) ─────────────────────────

def transcribe(video):
    out = WORK / 'stt.json'
    if out.exists() and out.stat().st_mtime > video.stat().st_mtime:
        return json.loads(out.read_text(encoding='utf-8'))
    key = os.environ.get('ELEVENLABS_API_KEY')
    if not key:
        die('ยังไม่ได้ใส่ ELEVENLABS_API_KEY ในไฟล์ .env (README ขั้นที่ 3)')
    print('🎙  ถอดเสียงด้วย ElevenLabs …')
    audio = WORK / 'audio.mp3'
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-vn', '-ac', '1', '-ar', '16000', '-b:a', '64k', str(audio)])
    b = '----lsc' + os.urandom(8).hex()
    body = bytearray()
    for k, v in {'model_id': 'scribe_v2', 'timestamps_granularity': 'character', 'language_code': 'tha'}.items():
        body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    body += f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="audio.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n'.encode()
    body += audio.read_bytes() + f'\r\n--{b}--\r\n'.encode()
    req = urllib.request.Request('https://api.elevenlabs.io/v1/speech-to-text', data=bytes(body), method='POST',
                                 headers={'xi-api-key': key, 'Content-Type': f'multipart/form-data; boundary={b}'})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=600).read())
    except urllib.error.HTTPError as e:
        die(f'ElevenLabs ตอบกลับ {e.code}: {e.read().decode("utf-8", "replace")[:400]}\n'
            '→ เช็กว่าคีย์ถูก และมีเครดิตเหลือ')
    out.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return data


def chars_of(stt):
    """Per-character timeline: [{'c', 's', 'e', 'sp'}]; sp=True means a space came before it."""
    chars, gap = [], False
    for w in stt.get('words', []):
        t = w.get('text', '')
        if w.get('type') == 'spacing' or not t.strip():
            gap = True
            continue
        if w.get('type') == 'audio_event':
            continue
        s, e = float(w['start']), float(w['end'])
        n = len(t)
        for i, c in enumerate(t):  # m = syllable midpoint: a tone mark is never cut away from its letter
            chars.append({'c': c, 's': s + (e - s) * i / n, 'e': s + (e - s) * (i + 1) / n, 'm': (s + e) / 2,
                          'sp': gap and i == 0})
        gap = False
    return chars


def norm(s):
    return re.sub(r'\s+', '', s).lower()


def find(chars, text, after=0.0):
    """(start, end) of the first spoken occurrence of `text` at/after `after` seconds."""
    hay = ''.join(c['c'] for c in chars).lower()
    needle = norm(text)
    i = next((k for k, c in enumerate(chars) if c['s'] >= after - 0.05), len(chars))
    j = hay.find(needle, i)
    if j < 0:
        return None
    return chars[j]['s'], chars[j + len(needle) - 1]['e']


# ───────────────────────── 2. ตัดช่วงเงียบ + ช่วงพูดผิด ─────────────────────────

def plan_cut(video, chars, cut):
    total = duration(video)
    r = run(['ffmpeg', '-hide_banner', '-i', str(video), '-af',
             f'silencedetect=n={cut.get("silence_db", -32)}dB:d={cut.get("min_silence", 0.28)}', '-f', 'null', '-'])
    starts = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', r.stderr)]
    ends = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', r.stderr)]
    pad = cut.get('pad', 0.06)
    keep, cur = [], 0.0
    for s, e in zip(starts, ends + [total] * (len(starts) - len(ends))):
        if s - cur > 0.15:
            keep.append([max(0, cur - pad if cur else cur), s + pad])
        cur = e
    if total - cur > 0.15:
        keep.append([max(0, cur - pad), total])
    if not cut.get('auto_silence', True):
        keep = [[0, total]]
    drops = []
    for item in cut.get('remove', []):
        if isinstance(item, list):
            drops.append(item)
        else:
            hit = find(chars, item)
            if hit:
                drops.append([hit[0] - 0.08, hit[1] + 0.08])
                print(f'✂️  ตัดช่วงพูดผิด "{item}" ({hit[0]:.2f}–{hit[1]:.2f}s)')
            else:
                print(f'⚠️  หา "{item}" ในคลิปไม่เจอ — ข้าม (เช็กตัวสะกดใน work/transcript.txt)')
    for a, b in drops:
        nxt = []
        for s, e in keep:
            if b <= s or a >= e:
                nxt.append([s, e])
            else:
                if a - s > 0.15: nxt.append([s, a])
                if e - b > 0.15: nxt.append([b, e])
        keep = nxt
    return keep


def cut_video(video, segs):
    out = WORK / 'edit.mp4'
    f = []
    for i, (a, b) in enumerate(segs):
        f.append(f'[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}]')
        f.append(f'[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.02,'
                 f'afade=t=out:st={max(0, b - a - 0.03):.3f}:d=0.03[a{i}]')
    f.append(''.join(f'[v{i}][a{i}]' for i in range(len(segs))) + f'concat=n={len(segs)}:v=1:a=1[v][a]')
    print(f'✂️  ตัดต่อ {len(segs)} ช่วง …')
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-filter_complex', ';'.join(f),
         '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-crf', '16', '-preset', 'medium', '-r', str(FPS),
         '-fps_mode', 'cfr', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', str(out)])
    return out


def remap(chars, segs):
    """Move character times from the raw clip onto the cut timeline; drop what was cut away."""
    out, off = [], []
    t = 0.0
    for a, b in segs:
        off.append((a, b, t))
        t += b - a
    for c in chars:
        hit = next(((a, b, o) for a, b, o in off if a <= c['m'] <= b), None) \
            or next(((a, b, o) for a, b, o in off if c['s'] < b and c['e'] > a), None)  # drawn-out sound into a cut pause
        if hit:
            a, b, o = hit
            out.append({**c, 's': max(c['s'], a) - a + o, 'e': min(c['e'], b) - a + o})
    return out


# ───────────────────────── 3. ซับ ─────────────────────────

def glen(s):  # visible length: Thai combining marks don't count
    return sum(1 for ch in s if unicodedata.category(ch) != 'Mn')


def make_captions(chars, max_len=14):
    try:
        from pythainlp.tokenize import word_tokenize
    except ImportError:
        die('ยังไม่ได้ติดตั้ง pythainlp — รันตัวติดตั้งใน README ขั้นที่ 2')
    # phrases split where the speaker paused (ElevenLabs spaces), then Thai word-tokenized, keeping char times
    phrases, cur = [], []
    for c in chars:
        if cur and c['sp']:
            phrases.append(cur)
            cur = []
        cur.append(c)
    if cur:
        phrases.append(cur)
    toks = []
    for ph in phrases:
        k = 0
        for w in word_tokenize(''.join(c['c'] for c in ph), engine='newmm', keep_whitespace=False):
            seg = ph[k:k + len(w)]
            k += len(w)
            if seg:
                toks.append({'t': w, 's': seg[0]['s'], 'e': seg[-1]['e'], 'new': not toks or seg[0] is ph[0]})
    caps, cur = [], []
    def flush():
        if not cur:
            return
        words = list(cur)
        while words and words[-1]['t'] in TRAIL:   # ตัดคำลงท้าย นะ/ค่ะ/ครับ
            words.pop()
        while words and words[0]['t'] in TRAIL:
            words.pop(0)
        txt = ''
        for t in words:
            latin = (txt[-1:].isascii() and txt[-1:].isalnum()) or t['t'][:1].isascii()
            txt += (' ' if txt and t['new'] and latin else '') + t['t']
        for f in FILLERS:
            txt = txt.replace(f, '')
        txt = txt.strip()
        if txt:
            caps.append([round(cur[0]['s'], 2), round(cur[-1]['e'], 2), txt])
    for t in toks:
        joined = ''.join(x['t'] for x in cur) + t['t']
        latin_run = cur and cur[-1]['t'][:1].isascii() and t['t'][:1].isascii() and glen(joined) <= max_len * 1.5
        if cur and not latin_run and (glen(joined) > max_len or t['s'] - cur[-1]['e'] > 0.35
                                      or (t['new'] and glen(joined) - glen(t['t']) >= max_len * .6)):  # prefer breaking at pauses
            flush()
            cur = []
        cur.append(t)
    flush()
    for i in range(len(caps) - 1):  # hold each line until the next one starts
        caps[i][1] = round(min(caps[i + 1][0], caps[i][1] + 1.2), 2)
    return caps


def highlight(text, keywords):
    for k in sorted(keywords, key=len, reverse=True):
        text = re.sub(re.escape(k), lambda m: f'\x00{m.group(0)}\x01', text, flags=re.I)
    return text.replace('\x00', '<b>').replace('\x01', '</b>')


# ───────────────────────── 4. ประกอบโมชั่น ─────────────────────────

SFX = {}   # time -> [(file, vol)]


def sfx(t, name, vol=.4):
    SFX.setdefault(round(t, 2), []).append((name, vol))


class Timeline:
    def __init__(self, chars, main):
        self.chars, self.main, self.cursor = chars, main, 0.0

    def at(self, spec, after=None, label=''):
        """spec = seconds (number) or words the speaker says (string)."""
        if spec is None:
            return None
        if isinstance(spec, (int, float)):
            return float(spec)
        hit = find(self.chars, spec, self.cursor if after is None else after)
        if not hit:
            print(f'⚠️  ไม่ได้ยินคำว่า "{spec}" {label} — ข้ามฉากนี้ (แก้คำใน project.json ให้ตรงกับ work/transcript.txt)')
            return None
        return hit[0]

    def span(self, sc, dur):
        t = self.at(sc.get('at', sc.get('when')), label=f'(ฉาก {sc["type"]})')
        if t is None:
            return None, None
        self.cursor = t
        end = self.at(sc['until'], after=t + .3) if 'until' in sc else None
        e = end - .05 if end else t + sc.get('dur', dur)
        return t, min(e, self.main)


def esc(s):
    return html.escape(str(s))


def asset(src, name=None):
    """Copy an input file into work/ and return its name for the HTML."""
    p = path(src)
    if not p.exists():
        die(f'ไม่พบไฟล์ {src} (ตั้งไว้ใน project.json)')
    dst = WORK / (name or p.name)
    if not dst.exists() or dst.stat().st_mtime < p.stat().st_mtime:
        shutil.copy2(p, dst)
    return dst.name


def build(cfg, chars, caps, main):
    shop, style = cfg['shop'], cfg.get('style', {})
    tl = Timeline(chars, main)
    H, J = [], []           # html, js
    track = iter(range(10, 2000))
    def clip(id_, t, d, inner='', cls='', tag='div', extra=''):
        return (f'<{tag} id="{id_}" class="clip {cls}" data-start="{t:.2f}" data-duration="{max(d, .05):.2f}" '
                f'data-track-index="{next(track)}" {extra}>{inner}</{tag}>')
    hits = {'shake': [], 'flash': [], 'punch': []}
    pip = []
    logo = asset(shop['logo'], 'logo' + Path(shop['logo']).suffix)
    behind = None

    for sc in cfg.get('scenes', []):
        typ = sc['type']
        if typ == 'hook':
            t, e = tl.span({**sc, 'at': sc.get('at', 0.1)}, 3.6)
            l = sc['lines'] + ['']
            H += [clip('hook1', t, e - t, esc(l[0])), clip('hook2', t + .25, e - t - .25, esc(l[1]))]
            J.append(f'''tl.fromTo("#cam", {{ scale: 1.12, x: -64.8, y: -96 }}, {{ scale: 1, x: 0, y: 0, duration: {e:.2f}, ease: "power2.out" }}, 0);
tl.from("#hook1", {{ y: -60, opacity: 0, duration: .45, ease: "expo.out" }}, {t:.2f});
tl.from("#hook2", {{ scale: 2.2, opacity: 0, duration: .5, ease: "back.out(2.2)" }}, {t + .25:.2f});
tl.to("#hook2", {{ rotation: -3, duration: .12, yoyo: true, repeat: 3, ease: "sine.inOut" }}, {t + .9:.2f});
tl.to("#hook2", {{ x: 14, duration: .05, yoyo: true, repeat: 9, ease: "steps(1)" }}, {t + .8:.2f});
tl.to(["#hook1", "#hook2"], {{ y: -40, opacity: 0, duration: .25, ease: "power2.in" }}, {e - .25:.2f});''')
            sfx(0, 'boom', .5); sfx(0, 'glitch', .3); sfx(t + .3, 'boom', .35)
            hits['shake'] += [t, t + .3]; hits['flash'].append(0); hits['punch'] += [0, t + .3]

        elif typ == 'stamp':
            t, e = tl.span(sc, 1.75)
            if t is None: continue
            title = '<br>'.join(f'<em>{esc(x)}</em>' if i else esc(x) for i, x in enumerate(sc.get('title', [shop['name']])))
            H.append(clip('stamp', t, e - t, f'<img src="{logo}"><div class="n">{title}</div><div class="s">{esc(sc.get("sub", shop.get("tagline", "")))}</div>'))
            J.append(f'''tl.fromTo("#stamp", {{ scale: 2.2, rotation: -12, opacity: 0 }}, {{ scale: 1, rotation: -3, opacity: 1, duration: .35, ease: "back.out(1.8)" }}, {t:.2f});
tl.from("#stamp img", {{ rotation: -200, scale: .3, duration: .6, ease: "back.out(1.6)" }}, {t + .07:.2f});
tl.to("#stamp", {{ y: -40, opacity: 0, scale: .9, duration: .25, ease: "power2.in" }}, {e - .25:.2f});''')
            sfx(t, 'stamp', .5); sfx(t + .02, 'chime', .25)
            hits['shake'].append(t); hits['flash'].append(t); hits['punch'].append(t)

        elif typ == 'chips':
            items = [(tl.at(it.get('at', it.get('when')), after=tl.cursor, label='(ป้าย)'), it['text']) for it in sc['items']]
            items = [x for x in items if x[0] is not None]
            if not items: continue
            t = items[0][0]
            tl.cursor = t
            end = tl.at(sc['until'], after=items[-1][0] + .3) if 'until' in sc else None
            e = min(end - .05 if end else items[-1][0] + sc.get('dur', 1.6), main)
            for i, (ti, txt) in enumerate(items):
                H.append(clip(f'chip{i}', ti, e - ti, esc(txt), 'chip', extra=f'style="top:{290 + i * 120}px"'))
                J.append(f'tl.from("#chip{i}", {{ x: -560, rotation: -8, duration: .45, ease: "back.out(1.6)" }}, {ti:.2f});')
                sfx(ti, 'pop', .35)
            J.append(f'tl.to(".chip", {{ opacity: 0, duration: .2 }}, {e - .2:.2f});')
            if sc.get('flag', True):
                H.append(clip('flag', t, e - t))
                J.append(f'''tl.fromTo("#flag", {{ scale: 0, rotation: 20 }}, {{ scale: 1, rotation: 6, duration: .5, ease: "back.out(1.6)" }}, {t:.2f});
tl.to("#flag", {{ rotation: -4, duration: .6, yoyo: true, repeat: 3, ease: "sine.inOut" }}, {t + .5:.2f});
tl.to("#flag", {{ opacity: 0, duration: .2 }}, {e - .2:.2f});''')

        elif typ == 'page':
            t, e = tl.span(sc, 2.85)
            if t is None: continue
            photos = ''.join(f'<img src="{asset(p)}">' for p in sc.get('photos', [])[:4])
            H.append(clip('phone', t, e - t, f'''<div class="scr"><div class="cover"></div><div class="isl"></div><img class="av" src="{logo}">
<div class="nm">{esc(shop['name'])}</div><div class="meta">{esc(shop.get('category', ''))}</div>
<div class="fol">{esc(shop.get('followers', ''))}</div><div class="btn">ติดตามเพจ</div>
<div class="lv">{esc(shop.get('live', ''))}</div><div class="grid">{photos}</div></div>'''))
            H.append(clip('phone-lbl', t + .2, e - t - .2, esc(sc.get('label', f'ค้นหาเพจ “{shop["name"]}”'))))
            J.append(f'''tl.from("#phone", {{ x: -560, rotation: -14, duration: .55, ease: "back.out(1.4)" }}, {t:.2f});
tl.from("#phone .grid img", {{ scale: 0, duration: .3, stagger: .1, ease: "back.out(2)" }}, {t + .5:.2f});
tl.from("#phone-lbl", {{ y: 20, opacity: 0, duration: .3 }}, {t + .3:.2f});
tl.to("#phone .btn", {{ scale: .94, duration: .12, yoyo: true, repeat: 1 }}, {t + 1.5:.2f});
tl.to(["#phone", "#phone-lbl"], {{ x: -600, rotation: -10, duration: .35, ease: "power3.in" }}, {e - .35:.2f});''')
            sfx(t, 'whoosh', .45); sfx(t + .4, 'shutter', .3)

        elif typ == 'gallery':
            t, e = tl.span(sc, 4.2)
            if t is None: continue
            pip.append((t, e))
            H.append(clip('gallery', t, e - t + .6, f'<div class="dots"></div><div class="eyebrow">{esc(sc.get("eyebrow", ""))}</div><div class="title">{esc(sc.get("title", ""))}</div>', 'bgscene'))
            for i, ph in enumerate(sc.get('photos', [])[:3]):
                H.append(clip(f'pol{i}', t, e - t + .6, f'<img src="{asset(ph["src"])}"><b>{esc(ph.get("label", ""))}</b>', 'pol', extra=f'style="left:{[60, 390, 720][i]}px;top:{[560, 520, 560][i]}px"'))
                J.append(f'tl.fromTo("#pol{i}", {{ y: 900, rotation: {[-32, 16, 36][i]} }}, {{ y: 0, rotation: {[-8, 4, 9][i]}, duration: .6, ease: "back.out(1.3)" }}, {t + .45 + i * .15:.2f});')
            for i, tg in enumerate(sc.get('tags', [])[:3]):
                ti = tl.at(tg.get('at', tg.get('when')), after=t, label='(ป้ายหมวด)')
                if ti is None: continue
                H.append(clip(f'tag{i}', ti, e - ti + .6, esc(tg['text']), 'cchip', extra=f'style="left:{[60, 390, 700][i]}px"'))
                J.append(f'tl.from("#tag{i}", {{ scale: 0, rotation: -12, duration: .35, ease: "back.out(2.4)" }}, {ti:.2f});')
                sfx(ti, 'pop', .35)
            J.append(f'tl.from("#gallery .eyebrow, #gallery .title", {{ x: -40, opacity: 0, duration: .4, stagger: .1, ease: "power3.out" }}, {t + .35:.2f});')
            sfx(t, 'whoosh', .4); sfx(t + .05, 'boom', .35); sfx(e, 'whoosh', .3)
            hits['shake'].append(t); hits['flash'].append(t)

        elif typ == 'zoom':
            t, e = tl.span(sc, 1.85)
            if t is None: continue
            fx, fy = style.get('face', [520, 800])
            H += [clip('vf', t, e - t, '<i></i><i></i><i></i><i></i>'), clip('zchip', t + .04, e - t - .04, esc(sc.get('text', '')))]
            J.append(f'''tl.to("#cam", {{ scale: 1.24, x: {-.24 * fx:.1f}, y: {-.24 * fy:.1f}, duration: .3, ease: "power4.out" }}, {t + .5:.2f});
tl.from("#vf", {{ scale: 1.35, opacity: 0, duration: .3, ease: "power3.out" }}, {t:.2f});
tl.from("#zchip", {{ scale: .6, opacity: 0, duration: .35, ease: "back.out(2)" }}, {t + .04:.2f});
tl.to(["#barT", "#barB"], {{ height: 170, duration: .22, ease: "power3.out" }}, {t:.2f});
tl.to(["#barT", "#barB"], {{ height: 0, duration: .3, ease: "power2.in" }}, {e - .3:.2f});
tl.to("#cam", {{ scale: 1, x: 0, y: 0, duration: .25, ease: "power2.out" }}, {e - .25:.2f});''')
            sfx(t + .5, 'scan', .3); hits['shake'].append(t + .5)

        elif typ == 'behind':
            t, e = tl.span(sc, 2.6)
            if t is None: continue
            behind = (t - .1, e - t + .2)
            spans = ''.join(f'<span>{esc(ch)}</span>' for ch in sc.get('text', 'SALE'))
            H.append(('CAM', clip('tb-text', t, e - t, spans)))
            H.append(('CAM', clip('v-cut', behind[0], behind[1], '', '', 'video', 'src="cutout.webm" muted playsinline')))
            J.append(f'''tl.from("#tb-text span", {{ y: -420, scale: 1.8, opacity: 0, duration: .32, stagger: .11, ease: "power4.in" }}, {t:.2f});
tl.to("#tb-text", {{ y: -30, duration: {e - t - .5:.2f}, ease: "sine.inOut" }}, {t + .5:.2f});''')
            sfx(t, 'boom', .45); sfx(t + .1, 'glitch', .25)
            hits['shake'].append(t); hits['punch'].append(t)

        elif typ == 'products':
            t, e = tl.span(sc, 6)
            if t is None: continue
            pip.append((t, e))
            snow = ''.join(f'<i style="left:{(i * 97) % 1060}px;font-size:{18 + (i * 7) % 26}px">❄</i>' for i in range(40)) if sc.get('snow', True) else ''
            H.append(clip('products', t, e - t + .6, f'<div class="eyebrow">{esc(sc.get("eyebrow", ""))}</div><div class="title">{esc(sc.get("title", ""))}</div><div id="snow">{snow}</div>', 'bgscene'))
            if sc.get('note'):
                H.append(clip('pnote', t, e - t + .6, esc(sc['note'])))
            J.append(f'tl.from("#products .eyebrow, #products .title, #pnote", {{ x: -40, opacity: 0, duration: .4, stagger: .1, ease: "power3.out" }}, {t + .3:.2f});')
            J.append(f'document.querySelectorAll("#snow i").forEach((el, i) => tl.fromTo(el, {{ y: 0, x: 0, rotation: 0 }}, {{ y: 2000, x: ((i * 71) % 160) - 80, rotation: 180, duration: 4 + (i % 5) * .6, ease: "none" }}, {t:.2f} + (i * .17) % 3));')
            pos = [(60, 470), (555, 470), (60, 870), (555, 870)]
            for i, it in enumerate(sc.get('items', [])[:4]):
                ti = tl.at(it.get('at', it.get('when')), after=t, label='(สินค้า)') if it.get('at', it.get('when')) is not None else t + .6 + i * .4
                if ti is None: ti = t + .6 + i * .4
                H.append(clip(f'pc{i}', ti, e - ti + .6, f'<img src="{asset(it["img"])}"><div class="lb">{esc(it.get("label", ""))}</div><div class="tg">{esc(it.get("tag", ""))}</div>', 'pc', extra=f'style="left:{pos[i][0]}px;top:{pos[i][1]}px"'))
                J.append(f'tl.from("#pc{i}", {{ rotationY: 90, scale: .6, opacity: 0, transformPerspective: 1400, duration: .4, ease: "back.out(1.6)" }}, {ti:.2f});')
                sfx(ti, 'shutter', .3)
                if i == 0: sfx(ti, 'boom', .4); hits['shake'].append(ti); hits['punch'].append(ti)
            tr = sc.get('trip')
            if tr:
                ti = tl.at(tr.get('at', tr.get('when')), after=t, label='(ป้ายเที่ยว)')
                if ti is not None and ti < e:
                    H += [clip('trip', ti + .15, e - ti - .15 + .6, esc(tr['text'])), clip('plane', ti, 1.6, '✈️')]
                    J.append(f'''tl.to(".pc", {{ opacity: .35, duration: .3 }}, {ti:.2f});
tl.fromTo("#plane", {{ x: -200, y: 80, rotation: -10 }}, {{ x: 1200, y: -120, rotation: -18, duration: 1.6, ease: "power1.inOut" }}, {ti:.2f});
tl.from("#trip", {{ scale: .4, opacity: 0, rotation: -6, duration: .4, ease: "back.out(2)" }}, {ti + .15:.2f});''')
                    sfx(ti, 'whoosh', .45)
            sfx(t, 'riser', .25); sfx(t, 'whoosh', .4); sfx(e, 'whoosh', .3)
            hits['flash'].append(t)

        elif typ == 'map':
            t, e = tl.span(sc, 8)
            if t is None: continue
            pip.append((t, e))
            H.append(clip('map', t, e - t + .6, f'<div class="eyebrow">{esc(sc.get("eyebrow", ""))}</div><div class="title">{esc(sc.get("title", ""))}</div>', 'bgscene'))
            H.append(clip('mapbox', t, e - t + .6, MAP_SVG))
            H += [clip('pin-pulse', t + .3, e - t + .3), clip('pin', t + .3, e - t + .3, PIN_SVG, '', 'div'),
                  clip('tag-shop', t + .65, e - t - .05, esc(sc.get('pin', shop['name'])), 'mtag')]
            J.append(f'''tl.from("#map .eyebrow, #map .title", {{ x: -40, opacity: 0, duration: .4, stagger: .1, ease: "power3.out" }}, {t + .25:.2f});
tl.from("#mapbox", {{ y: 120, opacity: 0, duration: .5, ease: "expo.out" }}, {t + .05:.2f});
tl.from("#pin", {{ y: -500, duration: .45, ease: "bounce.out" }}, {t + .3:.2f});
tl.fromTo("#pin-pulse", {{ scale: .3, opacity: 1 }}, {{ scale: 2.6, opacity: 0, duration: 1, repeat: {int(e - t)}, ease: "power2.out" }}, {t + .65:.2f});
tl.from("#tag-shop", {{ scale: 0, duration: .3, ease: "back.out(2.4)" }}, {t + .65:.2f});''')
            sfx(t, 'whoosh', .4); sfx(t + .3, 'stamp', .45); hits['shake'].append(t + .3); hits['flash'].append(t)
            for key, tag_id, path_id in (('road', 'tag-road', 'roadhl'), ('train', 'tag-mrt', 'mrtline')):
                it = sc.get(key)
                if not it: continue
                ti = tl.at(it.get('at', it.get('when')), after=t, label=f'(แผนที่ {key})')
                if ti is None or ti > e: continue
                H.append(clip(tag_id, ti + .05, e - ti - .05, esc(it['label']), 'mtag'))
                J.append(f'tl.to("#{path_id}", {{ strokeDashoffset: 0, duration: 1.2, ease: "power2.inOut" }}, {ti:.2f});')
                J.append(f'tl.from("#{tag_id}", {{ scale: 0, duration: .35, ease: "back.out(2.4)" }}, {ti + .05:.2f});')
                if key == 'train':
                    J.append(f'tl.to("#stn", {{ opacity: 1, duration: .2 }}, {ti + 1:.2f});')
                sfx(ti, 'scan' if key == 'road' else 'whoosh', .3)
            if sc.get('parking', True):
                J.append(f'tl.to("#parkicon", {{ opacity: 1, duration: .3 }}, {e - .7:.2f});')
            sfx(e, 'whoosh', .3)

        elif typ == 'badge':
            t, e = tl.span(sc, 2.8)
            if t is None: continue
            H.append(clip('badge', t, e - t, f'<div class="p" style="background:{esc(sc.get("color", "#1f5fd1"))}">{esc(sc.get("icon", "P"))}</div><div class="t">{esc(sc.get("text", ""))}</div>'))
            J.append(f'''tl.from("#badge .p", {{ scale: 3, rotation: 20, opacity: 0, duration: .4, ease: "back.out(1.8)" }}, {t:.2f});
tl.from("#badge .t", {{ y: 40, opacity: 0, duration: .3, ease: "power3.out" }}, {t + .25:.2f});
tl.to("#badge", {{ opacity: 0, y: -30, duration: .25 }}, {e - .25:.2f});''')
            sfx(t, 'stamp', .45); sfx(t, 'boom', .3); hits['shake'].append(t); hits['punch'].append(t)

        elif typ == 'hours':
            t, e = tl.span(sc, 2.2)
            if t is None: continue
            H.append(clip('hours', t, e - t, f'<div class="d"><span class="clk"><i></i></span>{esc(sc.get("day", "เปิดทุกวัน"))}</div><div class="h">{esc(sc.get("time", shop.get("hours", "")))}</div>'))
            J.append(f'''tl.from("#hours", {{ y: -80, opacity: 0, scale: .9, duration: .45, ease: "back.out(1.6)" }}, {t:.2f});
tl.from("#hours .h", {{ scale: 2, opacity: 0, duration: .35, ease: "back.out(2)" }}, {t + .7:.2f});
tl.to("#hours .clk i", {{ rotation: 720, duration: {e - t:.2f}, ease: "power2.inOut" }}, {t:.2f});
tl.to("#hours", {{ opacity: 0, duration: .2 }}, {e - .2:.2f});''')
            sfx(t, 'whoosh', .35); sfx(t + .7, 'check', .4)

        elif typ == 'cta':
            t, e = tl.span(sc, main)
            if t is None: continue
            e = main
            typed = ''.join(f'<span class="ch">{esc(c)}</span>' for c in re.findall(r'.[ัิ-ฺ็-๎]*', shop.get('search', shop['name'])))
            soc = ''.join(f'<span style="background:{esc(s["color"])}">{esc(s["name"])}</span>' for s in shop.get('socials', [])[:4])
            H.append(clip('cta', t, e - t, f'<img src="{logo}"><div class="n">{esc(shop["name"])}</div><div class="s">{esc(shop.get("location", ""))}</div><div class="bar"><span class="q">🔍</span><span class="tx">{typed}<i class="caret"></i></span></div><div class="soc">{soc}</div>'))
            J.append(f'''tl.from("#cta", {{ y: -60, opacity: 0, scale: .9, duration: .45, ease: "back.out(1.6)" }}, {t:.2f});
tl.from("#cta .ch", {{ opacity: 0, duration: .01, stagger: .07 }}, {t + .35:.2f});
tl.from("#cta .soc span", {{ y: 40, opacity: 0, duration: .3, stagger: .1, ease: "back.out(2)" }}, {t + 1:.2f});''')
            sfx(t, 'boom', .4); sfx(t + .05, 'chime', .25); sfx(t + .4, 'pop', .25); sfx(t + .9, 'pop', .25)
            hits['shake'].append(t); hits['flash'].append(t); hits['punch'].append(t)
        else:
            print(f'⚠️  ไม่รู้จักฉากชนิด "{typ}" — ข้าม')

    # PiP in/out for scenes that sit behind the shrunken camera
    for t, e in pip:
        J.append(f'pipIn({t:.2f}); pipOut({e:.2f});')

    # captions
    kw = cfg.get('keywords', [])
    for i, (s, e, txt) in enumerate(caps):
        parts = []
        for p in re.findall(r'<b>.*?</b>|[^<]+', highlight(txt, kw)):
            parts += [f'<b>{w}</b>' for w in p[3:-4].split()] if p.startswith('<b>') else p.split()
        H.append(clip(f'c{i}', s, max(e - s, .3), '<span>' + ' '.join(f'<i class="w">{w}</i>' for w in parts) + '</span>', 'cap'))

    # live layer
    hearts = ''.join(f'<i class="ht" style="left:{(i * 37) % 90}px">{["❤️", "💗", "🧡", "💖", "🛍️", "❤️", "😍", "💕"][i % 8]}</i>' for i in range(int(main / .43)))
    H.append(clip('live', .3, main - .3, f'<div class="pill"><i></i>LIVE</div><img src="{logo}"><span>{esc(shop["name"])}</span>'))
    H.append(clip('hearts', .3, main - .3, hearts))

    # end slate + explosion
    total = main + END_SLATE
    lines = '<br>'.join(esc(x) for x in shop.get('info', []))
    follow = '<br>'.join(esc(x) for x in shop.get('follow', []))
    H.append(('TOP', clip('outro', main, END_SLATE, f'<img src="{logo}"><div class="n">{esc(shop["name"])}</div><div class="tag">{esc(shop.get("tagline", ""))}</div><div class="info">{lines}</div><div class="box"><small>ติดตามได้ที่ ↗</small><b>{follow}</b></div>')))
    debris = ''.join(f'<i style="background:{["#fff2a8", "#ffcf3a", "#ff8a1f", "#e5322d", "#ffe066"][i % 5]};width:{10 + (i * 7) % 22}px;height:{8 + (i * 5) % 18}px"></i>' for i in range(36))
    H += [('TOP', clip('ex-core', main - .03, 1, '', 'ex')), ('TOP', clip('ex-ring1', main - .03, .9, '', 'ex ex-ring')),
          ('TOP', clip('ex-ring2', main + .07, .9, '', 'ex ex-ring')), ('TOP', clip('ex-debris', main - .03, 1.3, debris, 'ex'))]
    sfx(main - .9, 'riser', .35); sfx(main - .03, 'boom', .8); sfx(main + .1, 'glitch', .2); sfx(main + .5, 'chime', .4)

    # sfx clips
    for t in sorted(SFX):
        for name, vol in SFX[t]:
            f = ROOT / 'assets' / 'sfx' / f'{name}.mp3'
            H.append(clip(f'sfx{next(track)}', t, min(duration(f), 1.6), '', '', 'audio', f'src="sfx/{name}.mp3" data-volume="{vol}"'))

    cam = '\n'.join(h for k, h in (x for x in H if isinstance(x, tuple)) if k == 'CAM')
    top = '\n'.join(h for k, h in (x for x in H if isinstance(x, tuple)) if k == 'TOP')
    body = '\n'.join(x for x in H if isinstance(x, str))
    bgm = asset(cfg.get('bgm', 'assets/bgm.mp3'), 'bgm' + Path(cfg.get('bgm', 'assets/bgm.mp3')).suffix)
    page = (ROOT / 'template.html').read_text(encoding='utf-8')
    for k, v in {'%%TOTAL%%': f'{total:.2f}', '%%MAIN%%': f'{main:.2f}', '%%CAM%%': cam, '%%BODY%%': body, '%%TOP%%': top,
                 '%%JS%%': '\n'.join(J), '%%CAPS%%': json.dumps([c[0] for c in caps]), '%%BGM%%': bgm,
                 '%%BGMVOL%%': str(cfg.get('bgm_volume', 0.09)), '%%PIPCROP%%': style.get('pip_crop', '18% 12% 34% 12%'),
                 '%%CAPBOTTOM%%': str(style.get('caption_bottom', 520)), '%%FX%%': json.dumps(hits),
                 '%%TITLE%%': esc(shop['name'])}.items():
        page = page.replace(k, v)
    (WORK / 'index.html').write_text(page, encoding='utf-8')
    gsap = sorted(glob.glob(str(ROOT / 'node_modules' / 'hyperframes' / 'dist' / 'vendor' / 'npm' / 'gsap@*' / 'dist' / 'gsap.min.js')))
    if not gsap:
        die('ไม่พบ GSAP ใน node_modules — รัน npm install ก่อน')
    shutil.copy2(gsap[-1], WORK / 'gsap.min.js')  # ponytail: bundled locally so render works offline
    sfx_dir = WORK / 'sfx'
    sfx_dir.mkdir(exist_ok=True)
    for f in (ROOT / 'assets' / 'sfx').glob('*.mp3'):
        shutil.copy2(f, sfx_dir / f.name)
    return behind


MAP_SVG = '''<svg width="960" height="740" viewBox="0 0 960 740"><g fill="#ddd5c6">
<rect x="40" y="40" width="230" height="170" rx="18"/><rect x="300" y="40" width="200" height="120" rx="18"/>
<rect x="640" y="200" width="260" height="160" rx="18"/><rect x="60" y="420" width="200" height="140" rx="18"/>
<rect x="560" y="430" width="180" height="120" rx="18"/><rect x="770" y="470" width="150" height="200" rx="18"/>
<rect x="300" y="560" width="220" height="140" rx="18"/></g><rect x="610" y="30" width="300" height="140" rx="22" fill="#cfe7c4"/>
<path d="M -20 640 C 240 520, 420 420, 980 300" stroke="#fff" stroke-width="70" fill="none"/>
<path id="roadhl" d="M -20 640 C 240 520, 420 420, 980 300" stroke="#f4c20f" stroke-width="22" fill="none" stroke-linecap="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>
<path d="M 520 -20 C 520 160, 470 300, 420 760" stroke="#c9bfae" stroke-width="30" fill="none"/>
<path id="mrtline" d="M 980 120 C 760 140, 560 170, 380 120 S 120 60, -20 90" stroke="#7b3fb8" stroke-width="20" fill="none" stroke-linecap="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>
<circle id="stn" cx="560" cy="160" r="22" fill="#fff" stroke="#7b3fb8" stroke-width="10" opacity="0"/>
<g id="parkicon" opacity="0"><rect x="610" y="250" width="70" height="70" rx="14" fill="#1f5fd1"/><text x="645" y="303" text-anchor="middle" font-family="Inter" font-weight="900" font-size="50" fill="#fff">P</text></g></svg>'''
PIN_SVG = '<svg viewBox="0 0 90 120" width="90" height="120"><path d="M45 4C22 4 6 21 6 42c0 28 39 72 39 72s39-44 39-72C84 21 68 4 45 4z" fill="#e5322d" stroke="#fff" stroke-width="5"/><circle cx="45" cy="42" r="15" fill="#fff"/></svg>'


# ───────────────────────── 5. ตัดตัวคนออกจากพื้นหลัง (ตัวหนังสือหลังคน) ─────────────────────────

def cutout(behind):
    out = WORK / 'cutout.webm'
    stamp = WORK / 'cutout.txt'
    key = f'{behind[0]:.2f},{behind[1]:.2f}'
    if out.exists() and stamp.exists() and stamp.read_text() == key and out.stat().st_mtime > (WORK / 'edit.mp4').stat().st_mtime:
        return True
    print('🧍 แยกตัวคนออกจากพื้นหลัง (ครั้งแรกจะโหลดโมเดล ~1-2 นาที) …')
    seg = WORK / 'behind.mp4'
    run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{behind[0]:.2f}', '-t', f'{behind[1]:.2f}', '-i', str(WORK / 'edit.mp4'),
         '-an', '-c:v', 'libx264', '-crf', '16', str(seg)])
    r = npx('hyperframes', 'remove-background', str(seg), '-o', str(out), '--quality', 'best')
    if r.returncode or not out.exists():
        print('⚠️  แยกพื้นหลังไม่สำเร็จ — ข้ามเอฟเฟกต์ตัวหนังสือหลังคน')
        return False
    stamp.write_text(key)
    return True


# ───────────────────────── 6. เรนเดอร์ + ปรับเสียง ─────────────────────────

def render(name):
    OUT.mkdir(exist_ok=True)
    raw = WORK / 'render.mp4'
    print('🎬 เรนเดอร์วิดีโอ (ประมาณ 3-6 นาที) …')
    if npx('hyperframes', 'render', str(WORK), '-o', str(raw)).returncode or not raw.exists():
        die('เรนเดอร์ไม่สำเร็จ — ดูข้อความด้านบน หรือรัน python3 make.py check')
    final = OUT / f'{name}.mp4'
    print('🔊 ปรับระดับเสียงให้ดังมาตรฐานโซเชียล …')
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(raw), '-c:v', 'copy', '-af',
         'loudnorm=I=-14:TP=-2:LRA=11,alimiter=limit=0.79:level=disabled:attack=2:release=50',
         '-ar', '48000', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(final)])
    small = OUT / f'{name}-small.mp4'
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(final), '-vf', 'scale=720:-2', '-c:v', 'libx264', '-crf', '26',
         '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(small)])
    raw.unlink()
    return final, small


# ───────────────────────── main ─────────────────────────

def check():
    ok = True
    for tool, hint in (('ffmpeg', 'ffmpeg'), ('ffprobe', 'ffmpeg'), ('node', 'Node.js')):
        found = shutil.which(tool) or shutil.which(tool + '.exe')
        print(('✅' if found else '❌'), tool, '' if found else f'— ยังไม่ได้ติดตั้ง {hint}')
        ok &= bool(found)
    try:
        import pythainlp  # noqa
        print('✅ pythainlp')
    except ImportError:
        print('❌ pythainlp — pip install pythainlp'); ok = False
    hf = (ROOT / 'node_modules' / 'hyperframes').exists()
    print(('✅' if hf else '❌'), 'hyperframes', '' if hf else '— รัน npm install')
    ok &= hf
    load_env()
    k = bool(os.environ.get('ELEVENLABS_API_KEY'))
    print(('✅' if k else '❌'), 'ELEVENLABS_API_KEY ใน .env')
    ok &= k
    print('\nพร้อมใช้งาน 🎉' if ok else '\nยังติดตั้งไม่ครบ — ทำตาม README ขั้นที่ 2-3')
    return ok


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if cmd == 'check':
        sys.exit(0 if check() else 1)
    if cmd not in ('all', 'render', 'preview', 'build'):
        die(__doc__)
    load_env()
    cfg = load_project()
    WORK.mkdir(exist_ok=True)
    video = path(cfg['video'])
    if not video.exists():
        die(f'ไม่พบวิดีโอ {cfg["video"]} — เอาคลิปไปวางไว้ที่ input/ แล้วตั้งชื่อให้ตรงกับ project.json')

    raw_chars = chars_of(transcribe(video))
    (WORK / 'transcript.txt').write_text('\n'.join(
        f'{c["s"]:7.2f}  ' + ''.join(x['c'] for x in raw_chars[i:i + 40])
        for i, c in list(enumerate(raw_chars))[::40]), encoding='utf-8')
    segs = plan_cut(video, raw_chars, cfg.get('cut', {}))
    plan_key = json.dumps(segs)
    edit = WORK / 'edit.mp4'
    cutf = WORK / 'cut.json'
    if not edit.exists() or not cutf.exists() or cutf.read_text() != plan_key:
        cut_video(video, segs)
        cutf.write_text(plan_key)
    chars = remap(raw_chars, segs)
    main_dur = round(duration(edit), 2)

    if cmd == 'all' or not CAPS_FILE.exists():
        caps = make_captions(chars, cfg.get('caption_max_chars', 14))
        CAPS_FILE.write_text('[\n' + ',\n'.join(json.dumps(c, ensure_ascii=False) for c in caps) + '\n]\n', encoding='utf-8')
        print(f'💬 สร้างซับ {len(caps)} บรรทัด → captions.json (แก้คำผิดได้ แล้วรัน python3 make.py render)')
    caps = json.loads(CAPS_FILE.read_text(encoding='utf-8'))

    SFX.clear()
    behind = build(cfg, chars, caps, main_dur)
    if behind and not cutout(behind):
        page = (WORK / 'index.html').read_text(encoding='utf-8')
        page = re.sub(r'<(div|video) id="(tb-text|v-cut)".*?</\1>', '', page, flags=re.S)
        (WORK / 'index.html').write_text(page, encoding='utf-8')
    print(f'🧩 ประกอบโมชั่นเสร็จ ({main_dur + END_SLATE:.1f} วินาที)')

    if cmd == 'build':
        return
    if cmd == 'preview':
        npx('hyperframes', 'preview', str(WORK))
        return
    final, small = render(cfg.get('output_name', 'final'))
    print(f'\n✅ เสร็จแล้ว!\n   คลิปเต็ม : {final}\n   ไฟล์เล็ก : {small}  (ส่งทางไลน์/ดูบนมือถือ)\n')


if __name__ == '__main__':
    main()
