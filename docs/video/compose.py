"""รวมเฟรม screencast + เสียงพากย์ทีละฉาก → MP4 (H.264/AAC) + ไฟล์คำบรรยาย .srt"""
import json, subprocess, sys
import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
tl = json.load(open("timeline.json", encoding="utf-8"))
rec0, end = tl["rec0"], tl["end"]
frames = tl["frames"]
AUDIO_LEAD = 0.35            # เริ่มพูดหลังเปลี่ยนฉากเล็กน้อย

lines = []
for i, (ts, name) in enumerate(frames):
    nxt = frames[i + 1][0] if i + 1 < len(frames) else end
    if i == 0 and ts > rec0:            # ช่วงก่อนเฟรมแรก ใช้เฟรมแรกแทน
        lines += [f"file 'frames/{name}'", f"duration {ts - rec0:.3f}"]
    lines += [f"file 'frames/{name}'", f"duration {max(nxt - ts, 0.001):.3f}"]
lines.append(f"file 'frames/{frames[-1][1]}'")
open("frames.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")

marks = tl["marks"]
cmd = [FF, "-y", "-f", "concat", "-safe", "0", "-i", "frames.txt"]
for m in marks:
    cmd += ["-i", m["audio"]]
fc = ["[0:v]fps=30,scale=1920:1080:flags=lanczos:out_range=tv,format=yuv420p[v]"]
for i, m in enumerate(marks, start=1):
    d = int((m["t"] - rec0 + AUDIO_LEAD) * 1000)
    fc.append(f"[{i}:a]adelay={d}|{d},aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")
fc.append("".join(f"[a{i}]" for i in range(1, len(marks) + 1)) +
          f"amix=inputs={len(marks)}:normalize=0:dropout_transition=0,alimiter=limit=0.95[a]")
total = end - rec0
cmd += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}", sys.argv[1]]
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stderr[-1200:])

def ts(sec):
    ms = int(round(sec * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
srt = []
for i, m in enumerate(marks, start=1):
    a = m["t"] - rec0 + AUDIO_LEAD
    srt += [str(i), f"{ts(a)} --> {ts(a + m['dur'])}", m["sub"], ""]
open(sys.argv[1].rsplit(".", 1)[0] + ".srt", "w", encoding="utf-8").write("\n".join(srt))
print("total", round(total, 1))
