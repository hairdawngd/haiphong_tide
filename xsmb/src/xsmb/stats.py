"""Xác suất lý thuyết và kiểm định cho bảng điểm."""
import math

N_RESULTS = 27
P_LOTO = 1 - 0.99 ** N_RESULTS   # một số 2 chữ số bất kỳ xuất hiện ít nhất 1 lần trong 27 giải
P_SPECIAL = 0.01                 # một số 2 chữ số trùng 2 số cuối giải Đặc biệt


def p_value(hits, n, p):
    """P(X >= hits) với X ~ Binomial(n, p): xác suất đạt được kết quả này (hoặc tốt hơn) chỉ nhờ may rủi.

    Chính xác ở mọi cỡ mẫu (xấp xỉ z sai khi n*p nhỏ). Các số chọn trong cùng một kỳ không hoàn
    toàn độc lập nên đây là giá trị gần đúng.
    """
    if n <= 0 or hits <= 0:
        return 1.0
    if hits > n:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    total = 0.0
    for k in range(hits, n + 1):
        t = math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq)
        total += t
        if k > n * p and t < 1e-15 * total:
            break
    return min(total, 1.0)
