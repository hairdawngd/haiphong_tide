# XSMB Tracker

Add-on tự lấy kết quả xổ số miền Bắc, tự học từng kỳ, ghi lại các số dự đoán **trước**
khi kết quả ra, rồi **thông báo kết quả đối chiếu**: số nào ra, ra mấy lần, ở giải nào.

> **Lưu ý:** mỗi kỳ quay độc lập và mọi số 00–99 có xác suất như nhau. Add-on này là công
> cụ thống kê để theo dõi và kiểm chứng, không phải công cụ dự báo. Bảng điểm sẽ cho bạn thấy
> tỉ lệ trúng thực tế so với tỉ lệ ngẫu nhiên. Add-on không tính tiền cược hay tiền thưởng.
> Vé XSKT chính thức là hình thức hợp pháp; đánh lô đề ngoài hệ thống vé chính thức thì
> không hợp pháp ở Việt Nam.

## Dữ liệu

Lấy từ [khiemdoan/vietnam-lottery-xsmb-analysis](https://github.com/khiemdoan/vietnam-lottery-xsmb-analysis)
(giấy phép MIT, cập nhật hằng ngày bằng GitHub Action): hơn 7.500 kỳ từ 2005-10-01, đủ 27 giải.
Thời điểm repo đó cập nhật sau kỳ quay (khoảng 18:15) không do add-on kiểm soát, nên thông báo
đến muộn hơn kỳ quay một khoảng thay đổi. Add-on kiểm tra mỗi `poll_minutes` phút và bỏ qua
rất nhanh khi chưa có kỳ mới.

## Dự đoán gì

Có hai mục tiêu, mỗi mục một mô hình học trực tuyến (EWMA + SGD logistic + Hedge):

1. **Loto**: số 2 chữ số (00–99) xuất hiện ít nhất một lần trong 27 giải. Xác suất ngẫu nhiên
   của một số là khoảng 23,8% (1 − 0,99²⁷).
2. **2 số cuối giải Đặc biệt**: xác suất ngẫu nhiên 1% cho mỗi số.

Mỗi kỳ add-on chọn `loto_per_draw` số loto và `special_per_draw` số cho giải ĐB có xác suất
mô hình cao nhất. Thực tế các xác suất này chỉ chênh vài phần nghìn so với mức nền.

## Cài đặt

1. Chép thư mục `xsmb` vào cùng chỗ với các add-on khác trong repo (ngang hàng `vietlott/`).
2. Đảm bảo `repository.yaml` ở gốc repo, rồi trong Home Assistant:
   **Cài đặt → Add-on → Cửa hàng add-on → ⋮ → Kiểm tra cập nhật**, cài *XSMB Tracker*.
3. Chỉnh cấu hình, bấm **Start**, bật *Hiển thị trên thanh bên*.

Hỗ trợ `amd64` và `aarch64`. Lần khởi động đầu mất vài giây để học toàn bộ lịch sử.

## Cấu hình

| Tùy chọn | Mặc định | Ý nghĩa |
|---|---|---|
| `poll_minutes` | 30 | Chu kỳ kiểm tra dữ liệu mới (5–240) |
| `loto_per_draw` | 5 | Số loto dự đoán mỗi kỳ (1–30) |
| `special_per_draw` | 3 | Số 2 chữ số cho giải ĐB mỗi kỳ (1–10) |
| `notify_persistent` | true | Thông báo trong Home Assistant |
| `notify_service` | rỗng | Dịch vụ notify bổ sung, ví dụ `mobile_app_iphone_cua_ban` |

Cổng Ingress được khai báo tại `ingress_port` trong `config.yaml`; service đọc cùng giá trị đó
để mở trang web, nên khi đổi cổng chỉ cần sửa trường này.

## Thực thể và sự kiện

- `sensor.xsmb_last_result`: ngày kỳ mới nhất; thuộc tính `special`, `first`, `prizes`, `loto`
- `sensor.xsmb_prediction`: các số dự đoán cho kỳ tới
- `sensor.xsmb_scoreboard`: số lần loto trúng; thuộc tính tỉ lệ thực tế, tỉ lệ lý thuyết và `*_p_value`
- Sự kiện `xsmb_new_result`: `date`, `special`, `first`, `special_two_digits`, `loto_hits`,
  `loto_picks`, `special_hit`

Cảm biến được tạo qua API trạng thái nên biến mất khi Home Assistant khởi động lại và được
tạo lại ở lần kiểm tra kế tiếp.

## Cách đọc bảng điểm

Cột "xác suất do may rủi" là xác suất đạt được kết quả này (hoặc tốt hơn) nếu chọn bừa, tính
chính xác theo phân phối nhị thức. Trên 5% nghĩa là chưa khác ngẫu nhiên. Vài kỳ đầu con số rất
dao động, nên chỉ nên kết luận sau hàng trăm kỳ, và chú ý rằng càng theo dõi nhiều chỉ số thì
càng dễ gặp một chỉ số "đẹp" chỉ do tình cờ.

## Lưu ý vận hành

- Nếu add-on tắt qua một hoặc nhiều kỳ quay, các số của kỳ bỏ lỡ không được chấm, vì dự đoán chỉ
  hợp lệ khi ghi trước kỳ đó.
- Thông báo trong Home Assistant dùng mã cố định nên thông báo mới thay thế thông báo cũ; lịch
  sử đầy đủ có ở trang XSMB trên thanh bên và ở `notify_service`.
- Dữ liệu và trạng thái mô hình lưu trong `/data` của add-on, được sao lưu cùng add-on.
