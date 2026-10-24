# Vietlott Tracker

Add-on tự lấy kết quả Vietlott (Power 6/55, Mega 6/45), tự học từng kỳ, ghi lại các
bộ số dự đoán **trước** khi kết quả ra, rồi **thông báo kết quả và hạng giải** của từng
bộ khi có kỳ mới.

> **Lưu ý quan trọng:** mỗi kỳ quay độc lập và mọi bộ số có xác suất trúng bằng nhau
> (Jackpot Power 6/55: 1/28.989.675; Mega 6/45: 1/8.145.060). Add-on này là công cụ
> thống kê để theo dõi và kiểm chứng; nó không làm tăng cơ hội trúng. Bảng điểm sẽ cho
> bạn thấy tỉ lệ trúng thực tế so với tỉ lệ lý thuyết.

## Cách hoạt động

1. Mỗi `poll_minutes` phút, add-on tải dữ liệu từ repo
   [vietvudanh/vietlott-data](https://github.com/vietvudanh/vietlott-data).
   Repo này cập nhật mỗi ngày khoảng 19:00 (giờ Việt Nam), tức khoảng 1 giờ sau kỳ quay,
   nên thông báo đến muộn hơn kỳ quay chừng đó.
2. Khi có kỳ mới: chấm điểm các bộ số đã dự đoán trước đó, học thêm kỳ mới, tạo dự đoán
   mới cho kỳ kế tiếp, gửi thông báo.
3. Mỗi ngày một lần, mô hình được khởi tạo lại và học tuần tự toàn bộ lịch sử từ kỳ đầu
   đến kỳ mới nhất. Những lần kiểm tra tiếp theo trong ngày chỉ học thêm nếu có kỳ mới;
   việc học lại không làm mất hoặc chấm lặp lịch sử dự đoán.
4. Mô hình: học trực tuyến (EWMA + SGD logistic + Hedge tổ hợp). Bộ 1 là top-6 theo
   mô hình; các bộ còn lại lấy mẫu có trọng số theo xác suất mô hình.

## Cài đặt (add-on cục bộ)

1. Chép thư mục `vietlott` vào thư mục `/addons/` của Home Assistant
   (qua add-on Samba hoặc SSH), ví dụ `/addons/vietlott/config.yaml`.
2. **Cài đặt → Add-on → Cửa hàng add-on → ⋮ → Kiểm tra cập nhật**, rồi mở mục
   **Local add-ons** và cài *Vietlott Tracker*.
3. Chỉnh cấu hình, bấm **Start**. Bật *Hiển thị trên thanh bên* để mở trang Vietlott.

Hỗ trợ kiến trúc `amd64` và `aarch64` (Raspberry Pi 4/5 bản 64-bit, HA Green/Yellow/Blue).
Phiên bản NumPy được giới hạn dưới 2.3 để tương thích với các CPU amd64 không hỗ trợ
tập lệnh x86-64-v2.

## Cấu hình

| Tùy chọn | Mặc định | Ý nghĩa |
|---|---|---|
| `games` | power655, mega645 | Sản phẩm theo dõi |
| `poll_minutes` | 30 | Chu kỳ kiểm tra dữ liệu mới (5–240) |
| `sets_per_draw` | 3 | Số bộ số dự đoán cho mỗi kỳ (1–10) |
| `notify_persistent` | true | Tạo thông báo trong Home Assistant |
| `notify_service` | rỗng | Dịch vụ notify bổ sung, ví dụ `mobile_app_iphone_cua_ban` |

Muốn nhận thông báo đẩy trên điện thoại, điền tên dịch vụ của app Home Assistant
(xem **Công cụ nhà phát triển → Hành động**, tìm `notify.mobile_app_...`).

## Thực thể được tạo (theo từng game, ví dụ `power655`)

- `sensor.vietlott_power655_last_result`: mã kỳ mới nhất; thuộc tính `numbers`, `bonus`, `date`
- `sensor.vietlott_power655_prediction`: bộ 1 dự đoán; thuộc tính `sets` (tất cả các bộ)
- `sensor.vietlott_power655_scoreboard`: số lần trúng thưởng; thuộc tính `win_rate_pct`,
  `expected_win_rate_pct`, `tiers`, `fixed_prize_total_vnd`, `ticket_cost_vnd`
- `sensor.vietlott_power655_training`: số kỳ đã học; thuộc tính `last_full_retrain`,
  `training_from`, `training_through`, `scored_draws`, `expert_log_loss` và `expert_weights`
- `sensor.vietlott_power655_yesterday_prediction`: chi tiết các bộ đã dự đoán và kết quả
  đối chiếu của kỳ gần nhất; `is_yesterday` cho biết kỳ đó có đúng ngày hôm qua hay không
- Trang Ingress cũng hiển thị trạng thái/metric huấn luyện và chi tiết đối chiếu dự đoán
  gần nhất. Nút **Huấn luyện lại toàn bộ** sẽ xếp hàng train lại tất cả game đang bật.

Các sensor tương ứng cũng được tạo cho `mega645`. Điểm log-loss chỉ tính trên phần kỳ
được chấm sau giai đoạn khởi động (`warmup_draws`).

Các thực thể được tạo qua API trạng thái nên sẽ biến mất khi Home Assistant khởi động lại,
và add-on tạo lại chúng ở lần kiểm tra kế tiếp (tối đa `poll_minutes` phút).

## Sự kiện cho tự động hóa

Mỗi khi chấm xong một kỳ, add-on phát sự kiện `vietlott_new_result` với dữ liệu:
`game`, `draw_id`, `date`, `numbers`, `bonus`, `best_matches`, `tiers_won`, `fixed_prize_vnd`.

```yaml
automation:
  - alias: Báo khi trúng thưởng Vietlott
    trigger:
      - platform: event
        event_type: vietlott_new_result
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.tiers_won | length > 0 }}"
    action:
      - service: notify.mobile_app_iphone_cua_ban
        data:
          title: "Trúng thưởng Vietlott!"
          message: "{{ trigger.event.data.game }} kỳ {{ trigger.event.data.draw_id }}: {{ trigger.event.data.tiers_won }}"
```

## Hạng giải

| Game | Hạng giải | Điều kiện | Giá trị |
|---|---|---|---|
| Power 6/55 | Jackpot 1 | 6 số | Tích lũy |
| | Jackpot 2 | 5 số + số phụ | Tích lũy |
| | Giải Nhất | 5 số | 40.000.000đ |
| | Giải Nhì | 4 số | 500.000đ |
| | Giải Ba | 3 số | 50.000đ |
| Mega 6/45 | Jackpot | 6 số | Tích lũy |
| | Giải Nhất / Nhì / Ba | 5 / 4 / 3 số | 10.000.000đ / 300.000đ / 30.000đ |

Giá trị Jackpot phụ thuộc mức tích lũy nên add-on không tự cộng vào tổng tiền thưởng.
Giá vé tính 10.000đ/bộ.

## Dữ liệu và riêng tư

Trạng thái mô hình và nhật ký dự đoán lưu trong `/data` của add-on (được sao lưu cùng
add-on). Add-on chỉ gọi ra ngoài tới `raw.githubusercontent.com` để lấy dữ liệu kết quả.

## Lưu ý vận hành

- Nếu add-on tắt qua một hoặc nhiều kỳ quay, bộ số của kỳ bỏ lỡ không được chấm, vì
  dự đoán chỉ hợp lệ khi được ghi trước kỳ đó. Add-on tiếp tục bình thường từ kỳ kế tiếp.
- Thông báo trong Home Assistant dùng mã cố định cho mỗi game nên thông báo mới thay thế
  thông báo cũ; lịch sử đầy đủ có ở trang Vietlott trên thanh bên và ở `notify_service`.
