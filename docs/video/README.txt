สร้างคลิปสาธิตใหม่ (ต้องมี playwright, edge-tts, imageio-ffmpeg):
1. คัดลอก static/fonts/Kanit-*.ttf, Sarabun-Regular.ttf, docs/brand/opd_logo_source.png (เป็น opd.png), static/img/hospital_logo.png (เป็น wnk.png) ลง card/
2. python tts.py      -> audio/*.mp3 + durations.json (ส่งเฉพาะบทพากย์ไป Microsoft Neural TTS)
3. python record.py   -> อัดจาก https://wnkhos.go.th/opd (ผ่านอินเทอร์เน็ต จึงไม่มี HN)
4. python compose.py ../../out/OPD_Dashboard_demo_TH.mp4
