/* ค้นหา + เรียงลำดับคอลัมน์ของตาราง (ไม่ใช้ไลบรารีภายนอก)
 *
 * <table class="t sortable">         คลิกหัวคอลัมน์เพื่อเรียง (คลิกซ้ำ = กลับลำดับ)
 * <input data-search="#idตาราง">     พิมพ์เพื่อกรองแถวที่มีคำนั้น
 * <td data-v="123">                  ค่าที่ใช้เรียง (ถ้าไม่ใส่ ใช้ข้อความในช่อง; "–" อยู่ท้ายเสมอ)
 */
(function () {
  'use strict';

  function rowsOf(table) {
    var body = table.tBodies[0] || table;
    return Array.prototype.filter.call(body.rows, function (r) { return !r.querySelector('th'); });
  }

  function key(cell) {
    if (!cell) return null;
    var v = cell.getAttribute('data-v');
    if (v === null) v = cell.textContent.trim();
    if (v === '' || v === '–' || v === '-') return null;
    // ช่องที่ขึ้นต้นด้วยตัวเลข ("1,234 ราย", "45 นาที", "12.5%") เรียงแบบตัวเลข
    if (/^-?[\d,]+(\.\d+)?/.test(v)) return parseFloat(v.replace(/,/g, ''));
    return v.toLowerCase();
  }

  function sortBy(table, col, th) {
    var asc = th.getAttribute('aria-sort') !== 'ascending';
    table.querySelectorAll('th').forEach(function (h) { h.removeAttribute('aria-sort'); });
    th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
    var rows = rowsOf(table);
    var parent = rows.length ? rows[0].parentNode : null;
    rows.map(function (r, i) { return { r: r, k: key(r.cells[col]), i: i }; })
      .sort(function (a, b) {
        if (a.k === null && b.k === null) return a.i - b.i;
        if (a.k === null) return 1;            // ไม่มีค่าอยู่ท้ายเสมอ
        if (b.k === null) return -1;
        var c = typeof a.k === 'number' && typeof b.k === 'number'
          ? a.k - b.k : String(a.k).localeCompare(String(b.k), 'th');
        return (asc ? c : -c) || a.i - b.i;
      })
      .forEach(function (x) { parent.appendChild(x.r); });
  }

  document.querySelectorAll('table.sortable').forEach(function (table) {
    var head = table.querySelector('tr');
    if (!head) return;
    Array.prototype.forEach.call(head.cells, function (th, col) {
      if (th.hasAttribute('data-nosort')) return;
      th.classList.add('sort');
      th.title = 'คลิกเพื่อเรียงลำดับ';
      th.tabIndex = 0;
      th.addEventListener('click', function () { sortBy(table, col, th); });
      th.addEventListener('keydown', function (e) { if (e.key === 'Enter') sortBy(table, col, th); });
    });
  });

  document.querySelectorAll('input[data-search]').forEach(function (inp) {
    var table = document.querySelector(inp.getAttribute('data-search'));
    var count = document.querySelector(inp.getAttribute('data-count') || '#none');
    if (!table) return;
    function run() {
      var q = inp.value.trim().toLowerCase(), shown = 0, rows = rowsOf(table);
      rows.forEach(function (r) {
        var ok = !q || r.textContent.toLowerCase().indexOf(q) >= 0;
        r.style.display = ok ? '' : 'none';
        if (ok) shown++;
      });
      if (count) count.textContent = q ? 'พบ ' + shown + ' จาก ' + rows.length + ' แถว' : rows.length + ' แถว';
    }
    inp.addEventListener('input', run);
    run();
  });
})();
