"""Trang web nhỏ (Ingress): dự đoán, kết quả gần đây và bảng điểm."""
import html
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import engine
from .stats import P_LOTO, P_SPECIAL, p_value

log = logging.getLogger("xsmb.web")
CSS = """
:root{color-scheme:light dark;--fg:#1c1c1e;--bg:#fff;--mut:#6b7280;--line:#d1d5db;--win:#15803d}
@media (prefers-color-scheme:dark){:root{--fg:#e5e7eb;--bg:#111827;--mut:#9ca3af;--line:#374151;--win:#4ade80}}
body{font:15px/1.5 system-ui,sans-serif;color:var(--fg);background:var(--bg);margin:0;padding:16px;max-width:860px}
h1{font-size:20px}h2{margin-top:24px;border-bottom:1px solid var(--line);padding-bottom:4px;font-size:17px}
code{font-family:ui-monospace,monospace;background:rgba(127,127,127,.15);padding:1px 6px;border-radius:4px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid var(--line);padding:4px 8px;text-align:left}
.win{color:var(--win);font-weight:600}.note{color:var(--mut);font-size:13px}
"""


def _n2(a):
    return " ".join(f"{x:02d}" for x in a)


def render():
    lg = engine.load_log()
    st, pend, hist = lg["stats"], lg.get("pending"), lg["history"]
    o = ["<h1>XSMB Tracker</h1>",
         "<p class='note'>Mỗi kỳ quay độc lập; mọi số có xác suất như nhau. Các số dưới đây là "
         "thống kê thử nghiệm, không phải dự báo.</p>"]
    if pend:
        o.append(f"<h2>Dự đoán cho kỳ sau {html.escape(pend['after_date'])}</h2>"
                 f"<p>Loto: <code>{_n2(pend['loto'])}</code><br>2 số cuối giải ĐB: <code>{_n2(pend['special'])}</code></p>")
    else:
        o.append("<p>Đang khởi tạo...</p>")
    o.append("<h2>Bảng điểm tích lũy</h2><table><tr><th></th><th>Trúng</th><th>Tỉ lệ thực tế</th>"
             "<th>Lý thuyết</th><th>Xác suất do may rủi</th></tr>")
    for name, h, n, p in (("Loto (xuất hiện ≥1 lần)", st["loto_hits"], st["loto_picks"], P_LOTO),
                          ("2 số cuối ĐB", st["special_hits"], st["special_picks"], P_SPECIAL)):
        rate = h / n * 100 if n else 0
        o.append(f"<tr><td>{name}</td><td>{h}/{n}</td><td>{rate:.2f}%</td><td>{p * 100:.2f}%</td>"
                 f"<td>{p_value(h, n, p) * 100:.1f}%</td></tr>")
    o.append(f"</table><p class='note'>{st['draws']} kỳ đã đối chiếu (từ {html.escape(str(st['since'] or '-'))}). "
             "Cột cuối là xác suất đạt kết quả này (hoặc tốt hơn) chỉ nhờ may rủi; trên 5% nghĩa là chưa khác ngẫu nhiên.</p><h2>Các kỳ gần đây</h2>")
    if not hist:
        o.append("<p>Chưa có kỳ nào được đối chiếu. Kết quả sẽ hiện sau kỳ quay kế tiếp.</p>")
    for ev in reversed(hist[-8:]):
        p = ev["prizes"]
        o.append(f"<p><b>{html.escape(ev['date'])}</b> · ĐB <code>{p['ĐB'][0]}</code> · G1 <code>{p['G1'][0]}</code>"
                 f" · 2 số cuối ĐB <code>{ev['special_two']:02d}</code><br>")
        parts = []
        for r in ev["loto"]:
            cls = "win" if r["times"] else ""
            parts.append(f"<span class='{cls}'>{r['number']:02d}" + (f" (×{r['times']})" if r["times"] else "") + "</span>")
        o.append("Loto: " + " · ".join(parts) + "<br>ĐB: " + " · ".join(
            f"<span class='{'win' if r['hit'] else ''}'>{r['number']:02d}{' ✓' if r['hit'] else ''}</span>"
            for r in ev["special"]) + "</p>")
    return ("<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<meta http-equiv='refresh' content='120'><title>XSMB</title><style>{CSS}</style></head><body>"
            + "".join(o) + "</body></html>")


def start(port=8098):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                body, code = render().encode("utf-8"), 200
            except Exception:  # noqa: BLE001
                log.exception("Lỗi render")
                body, code = "Lỗi hiển thị".encode("utf-8"), 500
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("Web UI đang chạy ở cổng %s", port)
    return srv
