"""Trang web nhỏ (Ingress) hiển thị dự đoán, kết quả và bảng điểm."""
import html
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import engine, prizes

log = logging.getLogger("vietlott.web")
GAME_ORDER = ["power655", "mega645"]


def _nums(a):
    return " ".join(f"{x:02d}" for x in a)


def _game_section(game):
    cfg = prizes.GAMES[game]
    lg = engine.load_log(game)
    st, pend, hist = lg["stats"], lg.get("pending"), lg["history"]
    out = [f"<section><h2>{html.escape(cfg['name'])}</h2>"]
    if pend:
        out.append(f"<h3>Dự đoán cho kỳ sau kỳ {html.escape(pend['after_id'])} ({html.escape(pend['after_date'])})</h3><ul>")
        for i, s in enumerate(pend["sets"], 1):
            out.append(f"<li><b>Bộ {i}:</b> <code>{_nums(s)}</code></li>")
        out.append("</ul>")
    else:
        out.append("<p>Chưa có dự đoán (đang khởi tạo).</p>")

    exp_rate = prizes.win_prob(game) * 100
    obs_rate = (st["wins"] / st["sets"] * 100) if st["sets"] else 0
    out.append("<h3>Bảng điểm tích lũy</h3>")
    out.append(f"<p>{st['sets']} bộ / {st['draws']} kỳ (từ {html.escape(str(st['since'] or '-'))}) · "
               f"trúng thưởng <b>{st['wins']}</b> lần = <b>{obs_rate:.2f}%</b> "
               f"(lý thuyết {exp_rate:.2f}%) · tổng thưởng cố định {prizes.vnd(st['prize_total'])} "
               f"· chi phí vé {prizes.vnd(st['sets'] * prizes.TICKET_PRICE)}</p>")
    probs = prizes.tier_probs(game)
    out.append("<table><tr><th>Hạng giải</th><th>Số lần trúng</th><th>Kỳ vọng ngẫu nhiên</th><th>Xác suất / bộ</th></tr>")
    for key, name, _ in cfg["tiers"]:
        out.append(f"<tr><td>{name}</td><td>{st['tiers'].get(key, 0)}</td>"
                   f"<td>{probs[key] * st['sets']:.2f}</td><td>1/{1 / probs[key]:,.0f}</td></tr>".replace(",", "."))
    out.append("</table>")

    out.append("<h3>Các kỳ gần đây</h3>")
    if not hist:
        out.append("<p>Chưa có kỳ nào được chấm điểm. Kết quả sẽ hiện sau kỳ quay kế tiếp.</p>")
    for ev in reversed(hist[-8:]):
        bonus = f" + <code>{ev['bonus']:02d}</code>" if ev.get("bonus") else ""
        out.append(f"<div class='draw'><b>Kỳ {html.escape(ev['draw_id'])}</b> · {html.escape(ev['date'])}"
                   f" · <code>{_nums(ev['numbers'])}</code>{bonus}<ul>")
        for i, s in enumerate(ev["sets"], 1):
            tier = prizes.tier_name(game, s["tier"]) if s["tier"] else "không trúng"
            cls = "win" if s["tier"] else ""
            out.append(f"<li class='{cls}'>Bộ {i} <code>{_nums(s['numbers'])}</code> → trùng {s['matches']} số · {tier}</li>")
        out.append("</ul></div>")
    out.append("</section>")
    return "".join(out)


CSS = """
:root{color-scheme:light dark;--fg:#1c1c1e;--bg:#fff;--mut:#6b7280;--line:#d1d5db;--win:#15803d}
@media (prefers-color-scheme:dark){:root{--fg:#e5e7eb;--bg:#111827;--mut:#9ca3af;--line:#374151;--win:#4ade80}}
body{font:15px/1.5 system-ui,sans-serif;color:var(--fg);background:var(--bg);margin:0;padding:16px;max-width:860px}
h1{font-size:20px}h2{margin-top:28px;border-bottom:1px solid var(--line);padding-bottom:4px}h3{font-size:15px;margin:16px 0 4px}
code{font-family:ui-monospace,monospace;background:rgba(127,127,127,.15);padding:1px 6px;border-radius:4px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid var(--line);padding:4px 8px;text-align:left}
.win{color:var(--win);font-weight:600}.note{color:var(--mut);font-size:13px}.draw{margin:10px 0}
"""


def _odds(game):
    return f"{prizes.jackpot_odds(game):,}".replace(",", ".")


def render(games):
    body = "".join(_game_section(g) for g in GAME_ORDER if g in games)
    return (
        "<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<meta http-equiv='refresh' content='120'><title>Vietlott</title><style>{CSS}</style></head><body>"
        "<h1>Vietlott Tracker</h1>"
        "<p class='note'>Mỗi kỳ quay độc lập; mọi bộ số có xác suất trúng bằng nhau. "
        f"Jackpot Power 6/55: 1/{_odds('power655')} · Mega 6/45: 1/{_odds('mega645')}. "
        "Các bộ số ở đây là thử nghiệm thống kê, không làm tăng cơ hội trúng.</p>"
        f"{body}</body></html>"
    )


def start(games, port=8099):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                data = render(games).encode("utf-8")
                self.send_response(200)
            except Exception:  # noqa: BLE001
                log.exception("Lỗi render")
                data = "Lỗi hiển thị".encode("utf-8")
                self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("Web UI đang chạy ở cổng %s", port)
    return srv
