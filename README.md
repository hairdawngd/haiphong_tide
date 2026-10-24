# hairdawngd hass add-ons

Kho add-on cho Home Assistant, hiện có:

- **Haiphong Tide** — dữ liệu thủy triều Hòn Dấu, Hải Phòng.
- **Vietlott Tracker** — theo dõi kết quả và dự đoán Vietlott.
- **XSMB Tracker** — theo dõi kết quả xổ số miền Bắc và đối chiếu dự đoán.

Lịch sử thay đổi và phiên bản add-on: [CHANGELOG.md](./CHANGELOG.md).

## Thêm kho vào Home Assistant

1. Mở **Cài đặt → Add-ons → Add-on Store**.
2. Mở menu **⋮ → Repositories**.
3. Thêm `https://github.com/hairdawngd/hass_addon`.
4. Chọn add-on cần cài trong cửa hàng, cài đặt và cấu hình trước khi khởi động.

## Haiphong Tide

Add-on tải bảng thủy triều Hòn Dấu từ
[thegioimoicau.com](https://thegioimoicau.com/dia-danh/hon-dau/trang-1) mỗi giờ
(có thể chỉnh chu kỳ trong cấu hình). Add-on dùng Home Assistant API để tạo/cập nhật
các sensor:

- `sensor.haiphong_tide_current` — mốc dữ liệu thủy triều hiện tại.
- `sensor.haiphong_tide_next` — mốc dữ liệu kế tiếp.
- `sensor.haiphong_tide_today_low` / `sensor.haiphong_tide_today_high`.
- `sensor.haiphong_tide_current_level_hourly` — mực nước nội suy theo giờ.
- `sensor.haiphong_tide_schedule` — lịch và các điểm đường cong thủy triều.

Yêu cầu kiến trúc `amd64` hoặc `aarch64` và quyền Home Assistant API được bật trong
cấu hình add-on.

## Vietlott Tracker

Xem hướng dẫn, cấu hình, các sensor và lưu ý xác suất trong
[vietlott/DOCS.md](./vietlott/DOCS.md). Add-on hỗ trợ `amd64` và `aarch64`.

## XSMB Tracker

Xem hướng dẫn, cấu hình, sensor và lưu ý thống kê trong
[xsmb/DOCS.md](./xsmb/DOCS.md). Add-on hỗ trợ `amd64` và `aarch64`.

## Phát triển

Mỗi thư mục add-on có `config.yaml`, `Dockerfile` và `requirements.txt`. Khi phát
hành phiên bản add-on mới, cập nhật cả trường `version` trong `config.yaml` và
`__version__` trong package Python tương ứng.
