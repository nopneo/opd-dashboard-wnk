สร้างคลิปสาธิตใหม่ (ต้องมี playwright, google-genai, imageio-ffmpeg):
1. คัดลอก static/fonts/Kanit-*.ttf, Sarabun-Regular.ttf, docs/brand/opd_logo_source.png (เป็น opd.png), static/img/hospital_logo.png (เป็น wnk.png) ลง card/
2. python tts_gemini.py  -> audio/*.mp3 + durations.json
   เสียง Gemini gemini-3.8-flash-tts "Charon" (เหมือนคลิป Sepsis Bundle) ส่งเฉพาะบทพากย์ไป Google
   คีย์อ่านจาก env ตามลำดับใน TTS_KEYS (ค่าเริ่มต้น GEMINI_API_KEY_PRO,GEMINI_API_KEY)
   โควตาฟรี 10 คำขอ/วัน/โมเดล จึงรวมบททีละคู่ (7 คำขอ) แล้วตัดแยกที่ช่วงเงียบ — สร้างใหม่บางฉาก: python tts_gemini.py kpi
   สำรอง: python tts.py (Microsoft Neural TTS เสียง Niwat)
3. python record.py   -> อัดจาก https://wnkhos.go.th/opd (ผ่านอินเทอร์เน็ต จึงไม่มี HN)
4. python compose.py ../../out/OPD_Dashboard_demo_TH.mp4
