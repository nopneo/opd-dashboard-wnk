"""สังเคราะห์เสียงพากย์ไทย (Neural) ทีละฉาก → audio/<id>.mp3 + durations.json
ส่งเฉพาะบทพากย์ไปที่บริการ TTS ของ Microsoft ไม่มีข้อมูลผู้ป่วย"""
import asyncio, json, re, subprocess
import edge_tts, imageio_ffmpeg

VOICE = "th-TH-NiwatNeural"
# คำที่ TTS อ่านเพี้ยน → คำอ่าน (บทบรรยายใต้ภาพยังแสดงตัวสะกดเดิม)
SAY = {"HOSxP": "ฮอส เอ็กซ์พี", "visit": "วิสิต"}
SHOW = {"โอพีดี แมเนจเมนต์ แดชบอร์ด": "OPD Management Dashboard", "เอสแอลเอ": "SLA",
        "พีดีเอฟ": "PDF"}
FF = imageio_ffmpeg.get_ffmpeg_exe()

def dur(path):
    err = subprocess.run([FF, "-i", path], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)

async def main():
    scenes = json.load(open("script.json", encoding="utf-8"))
    out = []
    for sc in scenes:
        say = sc["text"]
        for k, v in SAY.items():
            say = say.replace(k, v)
        show = sc["text"]
        for k, v in SHOW.items():
            show = show.replace(k, v)
        path = f"audio/{sc['id']}.mp3"
        for attempt in range(4):
            try:
                await edge_tts.Communicate(say, VOICE, rate="+0%").save(path)
                break
            except edge_tts.exceptions.NoAudioReceived:
                print("retry", sc["id"], attempt)
                await asyncio.sleep(2)
        else:
            raise SystemExit("TTS failed: " + sc["id"])
        out.append({"id": sc["id"], "audio": path, "dur": round(dur(path), 2), "sub": show})
        print(sc["id"], out[-1]["dur"])
    json.dump(out, open("durations.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("total", round(sum(x["dur"] for x in out), 1))

asyncio.run(main())
