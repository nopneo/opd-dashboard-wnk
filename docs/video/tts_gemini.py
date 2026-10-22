"""สังเคราะห์เสียงพากย์ไทยด้วย Gemini TTS ทีละฉาก → audio/<id>.mp3 + durations.json

ตั้งค่าเดียวกับวิดีโอ Sepsis Bundle: โมเดล gemini-3.8-flash-tts เสียง Charon ส่งบทล้วน (ไม่มีคำสั่งสไตล์
เพราะโมเดลอ่านคำสั่งออกเสียงปนไปด้วย) · ตรวจความยาวแล้วสร้างใหม่ถ้ายาวผิดปกติ
· ตัดเสียงซ่าท้ายไฟล์ที่ช่วงเงียบสุดท้าย + fade · ปรับความดัง loudnorm -16 LUFS
ส่งเฉพาะบทพากย์ไปที่ Google ไม่มีข้อมูลผู้ป่วย
คีย์: GEMINI_API_KEY_PRO ก่อน แล้วค่อย GEMINI_API_KEY (env หรือ HKCU\\Environment)
"""
import json, os, re, subprocess, sys, tempfile, time, wave

import imageio_ffmpeg
from google import genai
from google.genai import types

MODEL = "gemini-3.8-flash-tts"
VOICE = "Charon"
# คำที่ TTS อ่านเพี้ยน → คำอ่าน (คำบรรยายใต้ภาพยังแสดงตัวสะกดเดิม)
SAY = {"HOSxP": "ฮอสเอ็กพี่", "visit": "วิสิต"}
SHOW = {"โอพีดี แมเนจเมนต์ แดชบอร์ด": "OPD Management Dashboard", "เอสแอลเอ": "SLA", "พีดีเอฟ": "PDF"}
FF = imageio_ffmpeg.get_ffmpeg_exe()


def api_key():
    for name in os.getenv("TTS_KEYS", "GEMINI_API_KEY_PRO,GEMINI_API_KEY").split(","):
        k = os.environ.get(name)
        if not k and sys.platform == "win32":
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as r:
                    k = winreg.QueryValueEx(r, name)[0]
            except OSError:
                pass
        if k:
            print("ใช้คีย์", name)
            return k
    raise SystemExit("ไม่พบ GEMINI_API_KEY_PRO หรือ GEMINI_API_KEY")


def synth(client, text):
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE))))
    for attempt in range(5):
        try:
            r = client.models.generate_content(model=MODEL, contents=text, config=cfg)
            return r.candidates[0].content.parts[0].inline_data.data
        except Exception as e:
            print("  retry", attempt, str(e)[:120])
            time.sleep(10 * (attempt + 1))
    raise SystemExit("TTS failed")


def synth_checked(client, text):
    """เสียงยาวผิดปกติ = โมเดลอ่านอะไรเกินบท → สร้างใหม่ (เก็บไฟล์ที่สั้นที่สุดไว้)"""
    limit = len(text) / 7 + 3.5
    best = None
    for attempt in range(2):                      # โควตาน้อย — สร้างซ้ำได้ครั้งเดียว
        pcm = synth(client, text)
        sec = len(pcm) / (24000 * 2)
        print(f"  ครั้งที่ {attempt + 1}: {sec:.1f} วิ (ไม่เกิน {limit:.1f})")
        if best is None or len(pcm) < len(best):
            best = pcm
        if sec <= limit:
            return pcm
    print("  !! ยาวเกินเกณฑ์ — ใช้ไฟล์ที่สั้นที่สุด ควรฟังตรวจ")
    return best


def speech_end(path):
    """เวลาที่พูดจบจริง — ตัดเสียงซ่า ~0.3 วิ ที่ Gemini แถมหลังช่วงเงียบท้ายไฟล์"""
    r = subprocess.run([FF, "-hide_banner", "-i", path, "-af", "silencedetect=n=-45dB:d=0.12", "-f", "null", "-"],
                       capture_output=True, text=True, errors="ignore")
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr).groups()
    dur = int(h) * 3600 + int(m) * 60 + float(s)
    sil = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    sil = [x for x in sil if x > dur - 1.5]
    return (sil[-1] + 0.08) if sil else dur


#: รวมบททีละคู่ในคำขอเดียว (ประหยัดโควตา 10 ครั้ง/วัน) แล้วตัดแยกที่ช่วงเงียบระหว่างบท
GROUPS = [("intro", "kpi"), ("blocks", "bottleneck"), ("table", "recs"), ("flow", "figures"),
          ("hover",), ("timeline",), ("outro",)]


def silences(path, d=0.3):
    r = subprocess.run([FF, "-hide_banner", "-i", path, "-af", f"silencedetect=n=-40dB:d={d}", "-f", "null", "-"],
                       capture_output=True, text=True, errors="ignore")
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(st, en))


def dur(path):
    err = subprocess.run([FF, "-i", path], capture_output=True, text=True, errors="ignore").stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def finish(src, path, t0=None, t1=None):
    """ตัดช่วง [t0, t1] (หรือทั้งไฟล์) ตัดเสียงซ่าท้าย + fade + loudnorm → mp3"""
    tmp = path + ".cut.wav"
    trim = [] if t0 is None else ["-ss", f"{t0:.3f}", "-to", f"{t1:.3f}"]
    subprocess.run([FF, "-loglevel", "error", "-y", "-i", src] + trim + [tmp], check=True)
    end = speech_end(tmp)
    subprocess.run([FF, "-loglevel", "error", "-y", "-i", tmp, "-af",
                    f"atrim=0:{end:.3f},highpass=f=70,afade=t=in:d=0.04,"
                    f"afade=t=out:st={max(end - 0.12, 0):.3f}:d=0.12,loudnorm=I=-16:TP=-1.5",
                    "-ar", "44100", "-b:a", "160k", path], check=True)
    os.remove(tmp)


def main():
    only = set(sys.argv[1:])                      # ระบุ id ฉากเพื่อสร้างใหม่เฉพาะกลุ่มนั้น
    scenes = {sc["id"]: sc for sc in json.load(open("script.json", encoding="utf-8"))}
    say, show = {}, {}
    for i, sc in scenes.items():
        a, b = sc["text"], sc["text"]
        for k, v in SAY.items():
            a = a.replace(k, v)
        for k, v in SHOW.items():
            b = b.replace(k, v)
        say[i], show[i] = a, b
    client = genai.Client(api_key=api_key())
    print("model", MODEL, "voice", VOICE)
    os.makedirs("audio", exist_ok=True)
    tmp = tempfile.mkdtemp()
    for g in GROUPS:
        if only and not (only & set(g)):
            continue
        print(" + ".join(g))
        wav = os.path.join(tmp, g[0] + ".wav")
        with wave.open(wav, "wb") as w:              # Gemini ส่ง PCM 16-bit 24 kHz mono
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(synth_checked(client, "\n\n".join(say[i] for i in g)))
        if len(g) == 1:
            finish(wav, f"audio/{g[0]}.mp3")
            continue
        total = dur(wav)
        expect = total * len(say[g[0]]) / (len(say[g[0]]) + len(say[g[1]]))
        cand = [(st, en) for st, en in silences(wav) if 1.5 < st < total - 1.5]
        st, en = min(cand, key=lambda x: abs((x[0] + x[1]) / 2 - expect) - 0.8 * (x[1] - x[0]))
        print(f"  ตัดที่ {st:.2f}-{en:.2f} วิ (คาด {expect:.1f}, ช่วงเงียบ {en - st:.2f} วิ)")
        finish(wav, f"audio/{g[0]}.mp3", 0, st + 0.1)
        finish(wav, f"audio/{g[1]}.mp3", max(en - 0.1, 0), total)
    out = [{"id": i, "audio": f"audio/{i}.mp3", "dur": round(dur(f"audio/{i}.mp3"), 2), "sub": show[i]}
           for i in scenes]
    for x in out:
        print("  ", x["id"], x["dur"], "วิ")
    json.dump(out, open("durations.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("total", round(sum(x["dur"] for x in out), 1))


main()
