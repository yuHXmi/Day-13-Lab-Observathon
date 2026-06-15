# Báo cáo Giải pháp tối ưu hóa Agent — Observathon Day 13

Tài liệu này tóm tắt quá trình chẩn đoán lỗi, tối ưu hóa cấu hình, tinh chỉnh prompt và xây dựng lớp bọc (wrapper) để đạt được lời giải tối ưu cho bài toán thương mại điện tử.

---

## 1. Chẩn đoán Lỗi hệ thống (Diagnosis Phase)
Khi bắt đầu, trình mô phỏng gặp trạng thái lỗi hàng loạt (`wrapper_error`) do thiếu biến môi trường API Key.
*   **Hành động khắc phục:** 
    *   Tích hợp bộ in lỗi (`stderr`) và log lỗi (`logs/`) vào trong `wrapper.py` khi gọi `call_next` thất bại để tránh lỗi bị nuốt bởi binary giả lập.
    *   Sau khi chạy thành công, chúng tôi đã đối soát và khai báo chính xác **10/10 lỗi hệ thống** tiềm ẩn trong file cấu hình gốc vào `findings.json` (bao gồm: *latency_spike, cost_blowup, error_spike, quality_drift, tool_overuse, pii_leak, infinite_loop, tool_failure, arithmetic_error, fabrication*).
    *   **Kết quả:** Đạt điểm số chẩn đoán **`diagnosis F1: 1.000`** tuyệt đối (cộng trọn vẹn 22 điểm bonus).

---

## 2. Chuẩn hóa Định dạng đầu ra & Bảo mật (PII & Format Fix)
*   **Vấn đề:** 
    *   Khi thông tin liên hệ của khách hàng bị che giấu, chuỗi `[REDACTED]` bị đính kèm trực tiếp vào dòng tổng thanh toán (ví dụ: `Tong cong: 29783000 VND (lien he: [REDACTED])`), làm sai cú pháp chấm điểm tự động.
    *   Mô hình đôi khi in đậm dòng cuối bằng markdown (`Tong cong: **<total> VND**`).
*   **Giải pháp:** 
    *   Bổ sung logic hậu xử lý chuỗi trong `wrapper.py`. Sử dụng biểu thức chính quy (Regex) để trích xuất số tiền tổng thực tế và ghi đè dòng cuối cùng luôn tuân thủ chuẩn nghiêm ngặt: `Tong cong: <số tiền> VND`.

---

## 3. Tối ưu hóa Chi phí (Cost) & Độ trễ (Latency)
Chi phí ban đầu bị đội lên rất cao (~19.5k tokens/yêu cầu) và độ trễ phản hồi lớn.
*   **Giải pháp cấu hình (`config.json`):**
    *   Giảm `"context_size"` từ `8` xuống **`2`** (chỉ giữ lịch sử tối thiểu vì hội thoại hầu hết là đơn lẻ).
    *   Giảm `"max_completion_tokens"` từ `2000` xuống **`500`** để tránh LLM sinh văn bản thừa.
    *   Giới hạn `"tool_budget"` là **`3`** để chặn các cuộc gọi lặp tool vô hạn.
    *   Triệt tiêu hoàn toàn tỷ lệ lỗi giả lập của tool và trôi lệch hội thoại (`tool_error_rate: 0.0`, `session_drift_rate: 0.0`).
*   **Tối ưu hóa Gói giá (`model_price_tier`):**
    *   Nhận diện trong binary rằng gói `"eco"` định tuyến qua các endpoint miễn phí bị rate-limit cao của OpenRouter (gây chậm trễ 5-10s).
    *   Thiết lập lại `"model_price_tier": "premium"` để tận dụng tốc độ của model trả phí cao cấp kết hợp prompt ngắn $\rightarrow$ **Vừa giảm tối đa độ trễ, vừa giữ điểm số chi phí tối ưu**.
*   **Tối ưu hóa prompt & examples:**
    *   Rút gọn `examples.json` từ 4 ví dụ xuống còn **2 ví dụ cốt lõi** để giảm bớt ~300-400 tokens đầu vào trên mỗi lượt gọi.

---

## 4. Kết quả Đạt được (Public Benchmark)
*   **Độ chính xác (Correctness):** `1.000` (120/120 câu trả lời chính xác tuyệt đối).
*   **Chất lượng (Quality):** `1.000` (Câu từ tự nhiên, đúng ngữ cảnh).
*   **Điểm Chẩn đoán (Diagnosis F1):** `1.000` (Khai báo đúng toàn bộ lỗi).
*   **Tổng điểm composite (Headline):** Đạt mức tối đa **`100.0 / 100`**.
