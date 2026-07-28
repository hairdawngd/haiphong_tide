# Haiphong Tide Integration

[![Open Home Assistant and install with HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hairdawngd&repository=haiphong_tide)

## 🌊 Nguồn dữ liệu / Data Source

- Crawl bảng thủy triều Hải Phòng: [tide-forecast.com](https://tide-forecast.com/locations/Haiphong-Vietnam/tides/latest)

## 🚀 Cài đặt nhanh với HACS (khuyên dùng)

1. Nhấn badge đầu README hoặc HACS > Integrations > Custom repositories.
2. Dán repo: `https://github.com/hairdawngd/haiphong_tide` (loại Integration).
3. Search Haiphong Tide, cài đặt, restart Home Assistant.
4. Settings → Devices & Services → Add Integration → tìm "Haiphong Tide".

## 🛠️ Cài thủ công

1. Copy folder `custom_components/haiphong_tide` vào `config/custom_components/` của Home Assistant.
2. Restart HA, Add Integration như bình thường.

## ✅ Tính năng / Features

- Lấy/và cập nhật tự động dữ liệu thủy triều Đồ Sơn (1 tiếng/lần).
- Sinh ra sensor:
    - `sensor.haiphong_tide_current` — Mực nước hiện tại.
    - `sensor.haiphong_tide_next` — Lần triều tiếp theo.
    - `sensor.haiphong_tide_today_low` — Triều thấp nhất hôm nay.
    - `sensor.haiphong_tide_today_high` — Triều cao nhất hôm nay.
    - `sensor.haiphong_tide_schedule` — Toàn bộ bảng thủy triều hôm nay.
- Đầy đủ thuộc tính: thời gian - chiều cao - loại triều.

## 💡 Ví dụ sử dụng / Usage Example

**Tự động cảnh báo khi triều cao hơn X m:**
```yaml
automation:
  - alias: High Tide Alert
    trigger:
      - platform: numeric_state
        entity_id: sensor.haiphong_tide_today_high
        above: 3.5
    action:
      - service: notify.notify
        data:
          message: "Hôm nay triều cao nhất đạt {{ states('sensor.haiphong_tide_today_high') }} mét"
```

**Tạo sensor đếm giờ đến lần triều tiếp theo:**
```yaml
template:
  - sensor:
      - name: "Giờ tới triều kế"  # Hours until next tide
        unit_of_measurement: "h"
        state: >
          {% set t = state_attr('sensor.haiphong_tide_next', 'time') %}
          {% if t %}
            {{ ((as_timestamp(t) - now().timestamp()) / 3600) | round(1) }}
          {% else %}unknown{% endif %}
```

## 📝 FAQ

- Không thấy Sensor: Kiểm tra log, đảm bảo Home Assistant truy cập Internet, đúng repo, đã restart.
- Dữ liệu không cập nhật: Nguồn web có thể thay đổi, check lại sau, hoặc reload integration.
- "Add Integration" không có: Kiểm tra URL repo, repo phải public, xóa cache HACS nếu cần.

## 📢 Liên hệ - Góp ý

- Mở issue trực tiếp trên [GitHub](https://github.com/hairdawngd/haiphong_tide).

## 🪪 Giấy phép

Free, phi lợi nhuận, open source.