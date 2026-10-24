"""Dịch vụ chạy nền của add-on: định kỳ lấy dữ liệu, học, chấm điểm, thông báo."""
import json
import logging
import math
import os
import signal
import threading
from datetime import date, timedelta
from pathlib import Path

from . import data, engine, prizes, web
from .ha import HA

log = logging.getLogger("vietlott")

DEFAULTS = {"games": ["power655", "mega645"], "poll_minutes": 30, "sets_per_draw": 3,
            "notify_persistent": True, "notify_service": ""}


def load_options(path="/data/options.json"):
    opts = dict(DEFAULTS)
    try:
        opts.update(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        log.warning("Không đọc được %s, dùng cấu hình mặc định.", path)
    return opts


def _nums(a):
    return " ".join(f"{x:02d}" for x in a)


def win_rates(game, stats):
    obs = stats["wins"] / stats["sets"] * 100 if stats["sets"] else 0.0
    return obs, prizes.win_prob(game) * 100


def result_message(game, ev, pending, stats):
    name = prizes.GAMES[game]["name"]
    bonus = f" + {ev['bonus']:02d}" if ev.get("bonus") else ""
    lines = [f"Kết quả {name} kỳ {ev['draw_id']} ({ev['date']}): {_nums(ev['numbers'])}{bonus}", ""]
    for i, s in enumerate(ev["sets"], 1):
        if s["tier"]:
            tier = prizes.tier_name(game, s["tier"])
            val = f" ({prizes.vnd(s['prize'])})" if s["prize"] else " (giá trị tích lũy)"
            lines.append(f"Bộ {i}: {_nums(s['numbers'])} → trùng {s['matches']} số: TRÚNG {tier}{val}")
        else:
            lines.append(f"Bộ {i}: {_nums(s['numbers'])} → trùng {s['matches']} số, không trúng giải")
    if ev["prize"]:
        lines.append(f"Tổng thưởng giải cố định kỳ này: {prizes.vnd(ev['prize'])}")
    obs, exp = win_rates(game, stats)
    lines += ["", f"Tích lũy: {stats['sets']} bộ / {stats['draws']} kỳ, trúng thưởng {stats['wins']} lần "
                  f"({obs:.2f}%, lý thuyết {exp:.2f}%)."]
    if pending:
        lines.append("Dự đoán kỳ tới: " + " | ".join(_nums(s) for s in pending["sets"]))
    odds = f"{prizes.jackpot_odds(game):,}".replace(",", ".")
    lines.append(f"Lưu ý: mọi bộ số có xác suất Jackpot như nhau, 1/{odds}.")
    return "\n".join(lines)


def publish_sensors(ha, game, res):
    cfg = prizes.GAMES[game]
    key = f"sensor.vietlott_{game}"
    latest, stats, pend, training = (
        res["latest"], res["stats"], res["pending"], res["training"]
    )
    obs, exp = win_rates(game, stats)
    ha.set_state(
        f"{key}_last_result", latest["id"],
        {
            "friendly_name": f"{cfg['name']} kết quả mới nhất",
            "icon": "mdi:ticket-confirmation",
            "date": latest["date"],
            "numbers": latest["numbers"],
            "bonus": latest.get("bonus")
        }
    )
    ha.set_state(
        f"{key}_training", training["processed_draws"], {
            "friendly_name": f"{cfg['name']} tiến độ huấn luyện",
            "icon": "mdi:brain",
            "unit_of_measurement": "kỳ",
            "last_full_retrain": training["last_full_retrain"],
            "full_retrain_this_cycle": training["full_retrain_this_cycle"],
            "training_from": training["first_draw"],
            "training_through": training["last_draw"],
            "scored_draws": training["scored_draws"],
            "warmup_draws": training["warmup_draws"],
            "top_six_hits": training["top_six_hits"],
            "expert_log_loss": training["expert_log_loss"],
            "expert_weights": training["expert_weights"],
        }
    )
    history = res["history"]
    if history:
        ev = history[-1]
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        ha.set_state(
            f"{key}_yesterday_prediction", ev["date"], {
                "friendly_name": f"{cfg['name']} đối chiếu dự đoán hôm qua/kỳ gần nhất",
                "icon": "mdi:clipboard-check",
                "is_yesterday": ev["date"] == yesterday,
                "draw_id": ev["draw_id"],
                "draw_date": ev["date"],
                "predicted_sets": [
                    {
                        "numbers": _nums(s["numbers"]),
                        "matches": s["matches"],
                        "bonus_hit": s["bonus_hit"],
                        "tier": s["tier"],
                        "prize_vnd": s["prize"],
                    }
                    for s in ev["sets"]
                ],
                "actual_numbers": _nums(ev["numbers"]),
                "actual_bonus": ev.get("bonus"),
                "total_fixed_prize_vnd": ev["prize"],
            }
        )
    if pend:
        ha.set_state(
            f"{key}_prediction",
            _nums(pend["sets"][0]),
            {
                "friendly_name": f"{cfg['name']} dự đoán kỳ tới",
                "icon": "mdi:crystal-ball",
                "sets": [_nums(s) for s in pend["sets"]],
                "after_draw": pend["after_id"],
                "top_probabilities": pend["top_probs"],
                "base_probability": pend["base"]
            }
        )
    ha.set_state(
        f"{key}_scoreboard",
        stats["wins"],
        {
            "friendly_name": f"{cfg['name']} số lần trúng thưởng",
            "icon": "mdi:trophy",
            "unit_of_measurement": "lần",
            "draws": stats["draws"],
            "sets": stats["sets"],
            "win_rate_pct": round(obs, 3),
            "expected_win_rate_pct": round(exp, 3),
            "tiers": stats["tiers"],
            "match_histogram": stats["match_hist"],
            "fixed_prize_total_vnd": stats["prize_total"],
            "ticket_cost_vnd": stats["sets"] * prizes.TICKET_PRICE
        }
    )


def run_cycle(opts, ha, loader=data.load, force_retrain=False):
    for game in opts["games"]:
        try:
            rows, n = loader(game)
            res = engine.update(
                game, rows, n, int(opts["sets_per_draw"]), force_retrain=force_retrain
            )
        except Exception:  # noqa: BLE001 - không để một lỗi mạng làm sập vòng lặp
            log.exception("Lỗi khi xử lý %s", game)
            continue

        name = prizes.GAMES[game]["name"]
        if res["first_run"]:
            log.info("%s: khởi tạo xong với %d kỳ lịch sử", game, len(rows))
            msg = (f"Đã học {len(rows)} kỳ lịch sử. Dự đoán cho kỳ tới: "
                   + " | ".join(_nums(s) for s in res["pending"]["sets"])
                   + ".\nKết quả sẽ được chấm điểm và thông báo khi có kỳ mới.")
            ha.notify(f"Vietlott {name}: đã khởi động", msg, f"vietlott_{game}_start",
                      opts["notify_persistent"], opts["notify_service"])
        for ev in res["events"]:
            log.info("%s kỳ %s: %s", game, ev["draw_id"],
                     [(s["matches"], s["tier"]) for s in ev["sets"]])
            best = max(ev["sets"], key=lambda s: s["matches"])
            title = f"Vietlott {name} kỳ {ev['draw_id']}" + (
                " – CÓ BỘ TRÚNG THƯỞNG!" if any(s["tier"] for s in ev["sets"]) else "")
            ha.notify(title, result_message(game, ev, res["pending"], res["stats"]),
                      f"vietlott_{game}_result", opts["notify_persistent"], opts["notify_service"])
            ha.fire_event("vietlott_new_result", {
                "game": game, "draw_id": ev["draw_id"], "date": ev["date"],
                "numbers": ev["numbers"], "bonus": ev.get("bonus"),
                "best_matches": best["matches"],
                "tiers_won": [s["tier"] for s in ev["sets"] if s["tier"]],
                "fixed_prize_vnd": ev["prize"]})
        publish_sensors(ha, game, res)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    opts = load_options()
    log.info("Cấu hình: %s", opts)
    ha = HA()
    stop = threading.Event()
    train_requested = threading.Event()
    web.start(
        opts["games"], int(os.environ.get("INGRESS_PORT", "8099")),
        on_train=train_requested.set,
    )

    def request_stop(*_):
        stop.set()
        train_requested.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, request_stop)

    first_cycle = True
    while not stop.is_set():
        force_retrain = False
        if not first_cycle:
            force_retrain = train_requested.wait(int(opts["poll_minutes"]) * 60)
        if stop.is_set():
            break
        if force_retrain:
            train_requested.clear()
            log.info("Đã nhận yêu cầu huấn luyện lại thủ công.")
        run_cycle(opts, ha, force_retrain=force_retrain)
        first_cycle = False
    log.info("Đã dừng.")


if __name__ == "__main__":
    main()
