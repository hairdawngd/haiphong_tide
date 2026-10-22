"""Giao tiếp với Home Assistant qua Supervisor proxy (thông báo, cảm biến, sự kiện)."""
import logging
import os

import requests

log = logging.getLogger("xsmb.ha")


class HA:
    def __init__(self):
        self.base = os.environ.get("HA_API_URL", "http://supervisor/core/api").rstrip("/")
        self.token = os.environ.get("SUPERVISOR_TOKEN", "")
        self.ok = bool(self.token)
        if not self.ok:
            log.warning("Không có SUPERVISOR_TOKEN: chỉ ghi log, không gửi tới Home Assistant.")

    def _post(self, path, payload):
        if not self.ok:
            return False
        try:
            r = requests.post(self.base + path, json=payload, timeout=15,
                              headers={"Authorization": f"Bearer {self.token}"})
            if r.status_code >= 300:
                log.warning("HA %s -> HTTP %s: %s", path, r.status_code, r.text[:200])
                return False
            return True
        except requests.RequestException as e:
            log.warning("Lỗi gọi HA %s: %s", path, e)
            return False

    def notify(self, title, message, notification_id, persistent=True, service=""):
        if persistent:
            self._post("/services/persistent_notification/create",
                       {"title": title, "message": message, "notification_id": notification_id})
        service = (service or "").strip()
        if service:
            service = service.removeprefix("notify.")
            self._post(f"/services/notify/{service}", {"title": title, "message": message})

    def set_state(self, entity_id, state, attributes):
        return self._post(f"/states/{entity_id}", {"state": str(state)[:250], "attributes": attributes})

    def fire_event(self, event, data):
        return self._post(f"/events/{event}", data)
