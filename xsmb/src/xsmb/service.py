"""Dịch vụ chạy nền: định kỳ lấy dữ liệu, học, đối chiếu, thông báo."""
import json
import logging
import os
import signal
import threading
from pathlib import Path

from . import data, engine, web
from .ha import HA
from .stats import P_LOTO, P_SPECIAL, p_value

log = logging.getLogger("xsmb")
DEFAULTS = {"poll_minutes": 30, "loto_per_draw": 5, "special_per_draw": 3,
            "notify_persistent": True, "notify_service": ""}


def load_options(path="/data/options.json"):
    opts = dict(DEFAULTS)
    try:
        opts.update(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        log.warning("Không đọc được %s, dùng cấu hình mặc định.", path)
    return opts


def _n2(a):
    return " ".join(f"{x:02d}" for x in a)


def rates(st):
    lo = st["loto_hits"] / st["loto_picks"] * 100 if st["loto_picks"] else 0.0
    sp = st["special_hits"] / st["special_picks"] * 100 if st["special_picks"] else 0.0
    return lo, sp


def result_message(ev, pending, st):
    p = ev["prizes"]
    lines = [f"Kết quả XSMB {ev['date']}: ĐB {p['ĐB'][0]} · G1 {p['G1'][0]} "
             f"· 2 số cuối ĐB: {ev['special_two']:02d}", "", "Số 2 chữ số (loto) đã dự đoán:"]
    for r in ev["loto"]:
        if r["times"]:
            lines.append(f"  {r['number']:02d}: RA {r['times']} lần (giải {', '.join(r['classes'])})")
        else:
            lines.append(f"  {r['number']:02d}: không ra")
    lines.append(f"  → trúng {sum(1 for r in ev['loto'] if r['times'])}/{len(ev['loto'])} số")
    lines += ["", "2 số cuối giải ĐB đã dự đoán: " +
              " | ".join(f"{r['number']:02d} {'ĐÚNG' if r['hit'] else 'sai'}" for r in ev["special"])]
    lo, sp = rates(st)
    pl = p_value(st["loto_hits"], st["loto_picks"], P_LOTO) * 100
    ps = p_value(st["special_hits"], st["special_picks"], P_SPECIAL) * 100
    lines += ["", f"Tích lũy {st['draws']} kỳ: loto trúng {st['loto_hits']}/{st['loto_picks']} "
                  f"({lo:.1f}%, lý thuyết {P_LOTO * 100:.1f}%); 2 số cuối ĐB trúng "
                  f"{st['special_hits']}/{st['special_picks']} ({sp:.2f}%, lý thuyết {P_SPECIAL * 100:.2f}%).",
              f"Xác suất đạt kết quả này chỉ nhờ may rủi: loto {pl:.0f}%, ĐB {ps:.0f}% "
              "(dưới 1% mới đáng ngờ, và chỉ có nghĩa sau hàng trăm kỳ)."]
    if pending:
        lines.append(f"Dự đoán kỳ tới: loto {_n2(pending['loto'])} | 2 số cuối ĐB {_n2(pending['special'])}")
    lines.append("Lưu ý: mỗi kỳ quay độc lập, mọi số có xác suất như nhau. Đây chỉ là thống kê, "
                 "không phải dự báo.")
    return "\n".join(lines)


def publish_sensors(ha, res):
    latest, st, pend = res["latest"], res["stats"], res["pending"]
    p = latest["prizes"]
    ha.set_state("sensor.xsmb_last_result", latest["id"], {
        "friendly_name": "XSMB kết quả mới nhất", "icon": "mdi:ticket-confirmation",
        "date": latest["date"], "special": p["ĐB"][0], "first": p["G1"][0],
        "special_two_digits": latest["special"], "prizes": p, "loto": sorted(latest["loto"])})
    if pend:
        ha.set_state("sensor.xsmb_prediction", f"loto {_n2(pend['loto'])} | ĐB {_n2(pend['special'])}", {
            "friendly_name": "XSMB dự đoán kỳ tới", "icon": "mdi:crystal-ball",
            "loto": pend["loto"], "special_two_digits": pend["special"], "after_draw": pend["after_id"],
            "loto_probabilities": pend["loto_probs"], "special_probabilities": pend["special_probs"]})
    lo, sp = rates(st)
    ha.set_state("sensor.xsmb_scoreboard", st["loto_hits"], {
        "friendly_name": "XSMB số loto trúng", "icon": "mdi:trophy", "unit_of_measurement": "lần",
        "draws": st["draws"], "loto_picks": st["loto_picks"], "loto_rate_pct": round(lo, 2),
        "loto_expected_pct": round(P_LOTO * 100, 2),
        "loto_p_value": round(p_value(st["loto_hits"], st["loto_picks"], P_LOTO), 4),
        "special_picks": st["special_picks"], "special_hits": st["special_hits"],
        "special_rate_pct": round(sp, 2), "special_expected_pct": round(P_SPECIAL * 100, 2),
        "special_p_value": round(p_value(st["special_hits"], st["special_picks"], P_SPECIAL), 4)})


def run_cycle(opts, ha, loader=data.load):
    try:
        rows = loader()
        res = engine.update(rows, int(opts["loto_per_draw"]), int(opts["special_per_draw"]))
    except Exception:  # noqa: BLE001 - lỗi mạng không được làm sập vòng lặp
        log.exception("Lỗi khi xử lý XSMB")
        return
    if res["first_run"]:
        log.info("Khởi tạo xong với %d kỳ lịch sử", len(rows))
        p = res["pending"]
        ha.notify("XSMB: đã khởi động",
                  f"Đã học {len(rows)} kỳ (từ {rows[0]['date']}). Dự đoán kỳ tới: loto {_n2(p['loto'])} | "
                  f"2 số cuối ĐB {_n2(p['special'])}.\nKết quả sẽ được đối chiếu và thông báo khi có kỳ mới.",
                  "xsmb_start", opts["notify_persistent"], opts["notify_service"])
    for ev in res["events"]:
        hits = sum(1 for r in ev["loto"] if r["times"])
        sp_hit = any(r["hit"] for r in ev["special"])
        log.info("Kỳ %s: loto trúng %d/%d, 2 số cuối ĐB %s", ev["date"], hits, len(ev["loto"]), sp_hit)
        title = f"XSMB {ev['date']}: loto {hits}/{len(ev['loto'])}" + (" · ĐÚNG 2 số cuối ĐB!" if sp_hit else "")
        ha.notify(title, result_message(ev, res["pending"], res["stats"]),
                  "xsmb_result", opts["notify_persistent"], opts["notify_service"])
        ha.fire_event("xsmb_new_result", {
            "date": ev["date"], "special": ev["prizes"]["ĐB"][0], "first": ev["prizes"]["G1"][0],
            "special_two_digits": ev["special_two"], "loto_hits": hits, "loto_picks": len(ev["loto"]),
            "special_hit": sp_hit})
    publish_sensors(ha, res)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    opts = load_options()
    log.info("Cấu hình: %s", opts)
    ha = HA()
    web.start(int(os.environ.get("INGRESS_PORT", "8098")))
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        run_cycle(opts, ha)
        stop.wait(int(opts["poll_minutes"]) * 60)
    log.info("Đã dừng.")


if __name__ == "__main__":
    main()
