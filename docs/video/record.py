"""อัดหน้าจอสาธิต Dashboard + Flow 3D จากเว็บจริง (ผ่านอินเทอร์เน็ต → ไม่มี HN)
ใช้ CDP screencast เก็บเฟรม JPEG พร้อมเวลา แล้วให้ compose.py รวมกับเสียงพากย์
"""
import base64
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
FR = HERE / "frames"
BASE = "https://wnkhos.go.th/opd"
DASH = BASE + "/?d1=2026-10-01&d2=2026-10-16"
FLOW = BASE + "/flow?d=2026-10-16&t=08:40"
CARD = (HERE / "card").resolve().as_uri()

scenes = {s["id"]: s for s in json.load(open(HERE / "durations.json", encoding="utf-8"))}
frames, marks = [], []

SUB_JS = """(t) => {
  let d = document.getElementById('vsub');
  if (!d) {
    d = document.createElement('div'); d.id = 'vsub';
    d.style.cssText = 'position:fixed;left:50%;bottom:34px;transform:translateX(-50%);z-index:99999;'
      + 'max-width:1500px;background:rgba(10,20,40,.82);color:#fff;padding:12px 28px;border-radius:14px;'
      + 'font:500 30px Kanit,Sarabun,sans-serif;line-height:1.45;text-align:center;pointer-events:none;'
      + 'box-shadow:0 6px 24px rgba(0,0,0,.3)';
    document.body.appendChild(d);
  }
  d.textContent = t; d.style.display = t ? '' : 'none';
}"""

SCROLL_JS = """(sel) => {
  let el = null;
  if (/^\\d+$/.test(sel)) {
    el = [...document.querySelectorAll('section.block')].find(s => {
      const n = s.querySelector('header .no'); return n && n.textContent.trim() === sel; });
  } else el = document.querySelector(sel);
  if (el) window.scrollTo({top: el.getBoundingClientRect().top + window.scrollY - 70, behavior: 'smooth'});
  return !!el;
}"""


def main():
    FR.mkdir(exist_ok=True)
    for f in FR.glob("*.jpg"):
        f.unlink()
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True)
        ctx = br.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1, locale="th-TH")
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)

        def on_frame(ev):
            n = len(frames)
            path = FR / f"f{n:05d}.jpg"
            path.write_bytes(base64.b64decode(ev["data"]))
            frames.append((ev["metadata"]["timestamp"], path.name))
            try:
                cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", on_frame)

        def wait(sec):
            page.wait_for_timeout(int(sec * 1000))

        def sub(text):
            try:
                page.evaluate(SUB_JS, text)
            except Exception:
                pass

        def goto(url):
            page.goto(url, wait_until="networkidle", timeout=60000)

        def scene(sid, actions, extra=0.9):
            sc = scenes[sid]
            t0 = time.time()
            marks.append({"id": sid, "t": t0, "audio": sc["audio"], "dur": sc["dur"], "sub": sc["sub"]})
            sub(sc["sub"])
            actions(t0, sub_text=sc["sub"])
            left = t0 + sc["dur"] + extra - time.time()
            if left > 0:
                wait(left)

        def at(t0, sec):
            left = t0 + sec - time.time()
            if left > 0:
                wait(left)

        # อุ่นแคชฝั่งเซิร์ฟเวอร์ก่อนเริ่มอัด (ช่วงครึ่งเดือนใช้เวลาโหลดหลายวินาที)
        goto(DASH)
        goto(FLOW)
        goto(CARD + "/intro.html")
        wait(0.5)

        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88,
                                          "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
        global REC0
        REC0 = time.time()

        # 1. intro
        scene("intro", lambda t0, sub_text: None, extra=1.2)

        # 2. KPI
        def kpi(t0, sub_text):
            goto(DASH); sub(sub_text)
            at(t0, 7.5)
            q = page.locator(".quick a").nth(1)
            if q.count():
                q.hover()
            at(t0, 10.5)
            q2 = page.locator(".quick a").nth(2)
            if q2.count():
                q2.hover()
        scene("kpi", kpi)

        # 3. blocks 2-10
        def blocks(t0, sub_text):
            page.mouse.move(1900, 500)
            page.evaluate(SCROLL_JS, "2"); at(t0, 4)
            page.evaluate(SCROLL_JS, "5"); at(t0, 8.5)
            page.evaluate(SCROLL_JS, "8")
        scene("blocks", blocks)

        # 4. bottleneck 11-15
        def bn(t0, sub_text):
            page.evaluate(SCROLL_JS, "11"); at(t0, 5.5)
            page.evaluate(SCROLL_JS, "13")
        scene("bottleneck", bn)

        # 5. ตารางรายแผนก + ดูรายเคส
        def table(t0, sub_text):
            page.evaluate(SCROLL_JS, "#dept-table"); at(t0, 1.6)
            th = page.locator("#deps th").nth(3)
            th.click(); at(t0, 2.4); th.click(); at(t0, 3.6)
            box = page.locator('#dept-table input.search')
            box.click(); box.type("OPD", delay=140); at(t0, 5.6)
            box.fill(""); at(t0, 6.3)
            link = page.locator("#deps tr", has_text="OPD จุดซักประวัติ").locator("a.drill").first
            href = link.get_attribute("href")
            link.hover(); at(t0, 7.0)
            goto(BASE + href[len("/opd"):] if href.startswith("/opd") else href)
            sub(sub_text); at(t0, 9.5)
            page.mouse.wheel(0, 380)
        scene("table", table, extra=2.5)

        # 6. แนวทางลดระยะเวลารอคอย
        def recs(t0, sub_text):
            goto(DASH); sub(sub_text)
            page.evaluate(SCROLL_JS, "#recs"); at(t0, 7)
            page.mouse.move(960, 600); page.mouse.wheel(0, 420)
        scene("recs", recs)

        # 7. Flow 3D
        def flow(t0, sub_text):
            goto(FLOW); sub(sub_text)
        scene("flow", flow)

        # 8. หุ่น + แผงขวา
        def figures(t0, sub_text):
            row = page.locator(".arow", has_text="หน้าห้องตรวจ").first
            row.click(); at(t0, 7.5)
            page.locator(".arow", has_text="รอผลแล็บ").first.hover()
        scene("figures", figures)

        # 9. ชี้ที่ผู้ป่วย
        def hover(t0, sub_text):
            page.click("#btnPlay")               # หยุดก่อน หาตำแหน่งหุ่นได้นิ่ง
            found = False
            for y in range(380, 760, 18):
                for x in range(560, 1240, 22):
                    page.mouse.move(x, y)
                    if page.evaluate("!document.getElementById('tip').hidden"):
                        found = True
                        break
                if found:
                    break
            at(t0, 6.5)
            page.click("#btnPlay")
        scene("hover", hover)

        # 10. ลากเส้นเวลา
        def timeline(t0, sub_text):
            page.mouse.move(1900, 300)
            page.click("#zFit"); at(t0, 0.8)
            bb = page.locator("#timeline").bounding_box()
            y = bb["y"] + bb["height"] * 0.4
            page.mouse.move(bb["x"] + bb["width"] * 0.30, y)
            page.mouse.down()
            for i in range(30):
                page.mouse.move(bb["x"] + bb["width"] * (0.30 + i * 0.0045), y)
                wait(0.07)
            page.mouse.up()
            page.locator("#speeds button", has_text="×120").click()
        scene("timeline", timeline, extra=2.5)

        # 11. outro
        def outro(t0, sub_text):
            goto(CARD + "/outro.html"); sub(sub_text)
        scene("outro", outro, extra=2.0)

        cdp.send("Page.stopScreencast")
        wait(0.3)
        br.close()

    json.dump({"rec0": REC0, "end": time.time(), "frames": frames, "marks": marks},
              open(HERE / "timeline.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("frames", len(frames), "duration", round(time.time() - REC0, 1))


if __name__ == "__main__":
    main()
