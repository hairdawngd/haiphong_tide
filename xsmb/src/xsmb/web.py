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
button{padding:8px 12px;border:0;border-radius:6px;background:#2563eb;color:#fff;font:inherit;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}#train-status{margin-left:8px;color:var(--mut)}
"""


def _n2(a):
    return " ".join(f"{x:02d}" for x in a)


def render():
    lg = engine.load_log()
    st, pend, hist = lg["stats"], lg.get("pending"), lg["history"]
    o = ["<h1>XSMB Tracker</h1>",
         "<p class='note'>Mỗi kỳ quay độc lập; mọi số có xác suất như nhau. Các số dưới đây là "
         "thống kê thử nghiệm, không phải dự báo.</p>",
         "<form action='train' method='post' id='train-form'>"
         "<button type='submit'>Huấn luyện lại toàn bộ</button>"
         "<span id='train-status' role='status'></span></form>"]
    if pend:
        o.append(f"<h2>Dự đoán cho kỳ sau {html.escape(pend['after_date'])}</h2>"
                 f"<p>Loto: <code>{_n2(pend['loto'])}</code><br>2 số cuối giải ĐB: <code>{_n2(pend['special'])}</code></p>")
    else:
        o.append("<p>Đang khởi tạo...</p>")
    training = lg.get("training")
    training_status = (
        "train lại toàn bộ"
        if training and training["full_retrain_this_cycle"]
        else "học tiếp"
    )
    o.append("<h2>Huấn luyện</h2>")
    if training:
        o.append(
            f"<p>Đã học {training['processed_draws']} kỳ · lịch sử "
            f"{html.escape(training['first_draw'])}–{html.escape(training['last_draw'])} · "
            f"học lại gần nhất {html.escape(training['last_full_retrain'])} · "
            f"· cập nhật gần nhất: {training_status}"
            f" · {training['scored_draws']} kỳ được chấm, warm-up {training['warmup_draws']} kỳ</p>"
        )
        for model_name, losses in training["expert_log_loss"].items():
            loss_text = " · ".join(
                f"{html.escape(name)}: {value if value is not None else 'chưa có'}"
                for name, value in losses.items()
            )
            weights = training["expert_weights"][model_name]
            weight_text = " · ".join(
                f"{html.escape(name)}: {value:.4f}" for name, value in weights.items()
            )
            o.append(
                f"<p><b>{html.escape(model_name.title())}</b> — log-loss bình quân: "
                f"{loss_text}<br>Trọng số mô hình: {weight_text}</p>"
            )
    else:
        o.append("<p>Chưa có dữ liệu huấn luyện.</p>")

    o.append("<h2>Bảng điểm tích lũy</h2><table><tr><th></th><th>Trúng</th><th>Tỉ lệ thực tế</th>"
             "<th>Lý thuyết</th><th>Xác suất do may rủi</th></tr>")
    for name, h, n, p in (("Loto (xuất hiện ≥1 lần)", st["loto_hits"], st["loto_picks"], P_LOTO),
                          ("2 số cuối ĐB", st["special_hits"], st["special_picks"], P_SPECIAL)):
        rate = h / n * 100 if n else 0
        o.append(f"<tr><td>{name}</td><td>{h}/{n}</td><td>{rate:.2f}%</td><td>{p * 100:.2f}%</td>"
                 f"<td>{p_value(h, n, p) * 100:.1f}%</td></tr>")
    o.append(f"</table><p class='note'>{st['draws']} kỳ đã đối chiếu (từ {html.escape(str(st['since'] or '-'))}). "
             "Cột cuối là xác suất đạt kết quả này (hoặc tốt hơn) chỉ nhờ may rủi; trên 5% nghĩa là chưa khác ngẫu nhiên.</p>")
    o.append("<h2>Đối chiếu dự đoán kỳ gần nhất</h2>")
    if hist:
        ev = hist[-1]
        o.append(
            f"<p>Kỳ {html.escape(ev['draw_id'])} · {html.escape(ev['date'])} · "
            f"Kết quả ĐB <code>{ev['prizes']['ĐB'][0]}</code>, G1 <code>{ev['prizes']['G1'][0]}</code> "
            f"· 2 số cuối ĐB <code>{ev['special_two']:02d}</code></p><ul>"
        )
        for item in ev["loto"]:
            classes = ", ".join(html.escape(value) for value in item["classes"]) or "không ra"
            o.append(
                f"<li>Loto <code>{item['number']:02d}</code> → ra {item['times']} lần "
                f"(giải: {classes})</li>"
            )
        for item in ev["special"]:
            outcome = "ĐÚNG" if item["hit"] else "sai"
            o.append(f"<li>2 số cuối ĐB <code>{item['number']:02d}</code> → {outcome}</li>")
        o.append("</ul>")
    else:
        o.append("<p>Chưa có kỳ nào được đối chiếu.</p>")
    o.append("<h2>Các kỳ gần đây</h2>")
    if not hist:
        o.append("<p>Kết quả sẽ hiện sau kỳ quay kế tiếp.</p>")
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
            + "".join(o)
            + "<script>"
            "document.getElementById('train-form').addEventListener('submit',async function(e){"
            "e.preventDefault();const b=this.querySelector('button'),s=document.getElementById('train-status');"
            "b.disabled=true;s.textContent='Đang gửi yêu cầu...';"
            "try{const r=await fetch(this.action,{method:'POST'});"
            "if(!r.ok)throw new Error(await r.text());"
            "s.textContent='Đã xếp hàng huấn luyện lại; trang sẽ tự cập nhật.';"
            "}catch(err){s.textContent='Không gửi được yêu cầu: '+err.message;b.disabled=false;}});"
            "</script></body></html>")


def start(port, on_train=None):
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

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/train":
                self.send_error(404)
                return
            if on_train is None:
                self.send_error(503, "Huấn luyện thủ công chưa khả dụng")
                return
            on_train()
            body = "Đã nhận yêu cầu huấn luyện lại.".encode("utf-8")
            self.send_response(202)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("Web UI đang chạy ở cổng %s", port)
    return srv
