# Dự báo tỉ lệ đạt trophy GTA VI sau một tuần

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/thanhlamvd/makefun-gta6-trophy-rarity/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/thanhlamvd/makefun-gta6-trophy-rarity/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Bài dự thi cho bounty [Forecast how many GTA VI players earn each trophy in week one](https://make.fun/bounty/gta6-trophy-rarity-forecast-01) trên make.fun.

Grand Theft Auto VI ra mắt ngày 19/11/2026 (chỉ trên PS5 và Xbox Series X|S). Exophase theo dõi tỉ lệ người chơi đạt từng trophy của game trên PS5. Bài này dự báo, cho mỗi trophy trong số 55 trophy, tỉ lệ người chơi sẽ đạt được nó tới 00:00 UTC ngày 26/11/2026 — dưới dạng 5 phân vị (5%, 25%, 50%, 75%, 95%) cho mỗi trophy. Điểm số là pinball loss trên thang logit: dự báo có trung vị chính xác và khoảng tin cậy trung thực sẽ thắng.

## Cách chạy

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Chương trình đọc mọi file `<id>.in` trong thư mục input và ghi `<id>.out` tương ứng ra thư mục output. Chỉ dùng thư viện chuẩn Python 3.13, không mạng, không ngẫu nhiên, không đọc đồng hồ — cùng một input luôn cho ra đúng một output (đã kiểm tra byte-identical trên 2 lần chạy), thời gian chạy ~0,06 giây cho 2 case thực hành (giới hạn là 8 giây/case).

## Phương pháp

Tất cả tính toán đều làm trong không gian logit (vì điểm số là pinball loss trên thang logit).

1. **Gộp các lần đọc giống nhau.** Exophase chỉ làm mới số liệu sau mỗi vài giờ: trang đứng yên giữa các lần làm mới rồi nhảy vọt. Hai lần đọc liên tiếp giống hệt nhau (cùng số người chơi, cùng toàn bộ tỉ lệ) không mang thông tin mới nên bị loại trước khi fit.

2. **Xu hướng theo từng trophy.** Với mỗi trophy, fit đường thẳng của logit(tỉ lệ) theo `ln(1 + số giờ kể từ lúc ra mắt)` bằng bình phương tối thiểu có trọng số theo độ mới (trọng số giảm một nửa sau mỗi 12 giờ: diễn biến đêm ra mắt không giống diễn biến ngày thứ hai). Dự báo neo vào tỉ lệ quan sát cuối cùng và chỉ ngoại suy *mức thay đổi*: `logit(r_target) = logit(r_last) + b · (x_target − x_last)`, với mức thay đổi logit kẹp trong [−3,5; +3,5]. Phép biến đổi log-thời gian chính là sự bão hòa: tăng trưởng chậm dần khi game già đi, nên trophy cốt truyện đầu game có thể leo xa còn platinum thì gần như đứng yên.

3. **Co lại về trung vị của tier.** Hệ số góc của từng trophy được co về trung vị hệ số góc của tier của nó (platinum / gold / silver / bronze đi cùng nhau: bronze cốt truyện leo nhanh, platinum bò chậm). Trọng số cho hệ số góc riêng là `n / (n + 4)` theo số lần đọc khác nhau, nên fit 2 điểm gần như không có trọng lượng còn lịch sử dài thì tự nói lên.

4. **Lịch sử phẳng → prior làm mới (refresh catch-up).** Nếu toàn bộ lịch sử không hề nhúc nhích (như 2 case thực hành), trang đã không làm mới kể từ lần đọc đầu: lần làm mới tiếp theo sẽ phơi bày toàn bộ tăng trưởng người chơi tích lũy từ đó. Mô hình dùng prior: số người chơi được theo dõi tăng ~0,39/giờ ngay sau ra mắt (lần làm mới đầu tiên được công bố đã đưa số người chơi từ 638 lên 3.868 trong ~4,7 giờ), giảm dần với hằng số thời gian 24 giờ; người chơi mới chỉ giữ mỗi trophy ở một tỉ lệ biên rất nhỏ, trừ các trophy đầu game (trọng số theo bình phương tỉ lệ hiện tại). Trung vị là hỗn hợp sau pha loãng `(r + (g − 1)·m) / g`, với khoảng tin cậy rộng.

5. **Độ rộng khoảng tin cậy.** Độ lệch chuẩn logit bằng căn bậc hai tổng bình phương của: phần dư fit của trophy, sai số hệ số góc nhân với khoảng ngoại suy, mức bất đồng giữa các trophy, và hạng tử chân trời `0,35·√(số ngày)` cho các lần làm mới và sai số mô hình mà lịch sử không thấy được. Kẹp trong [0,45; 2,2] logit. Phân vị là các phân vị chuẩn tại các mức của case quanh trung vị trong không gian logit, làm tròn nửa lên tới 4 chữ số thập phân, kẹp trong [0,01; 100] và ép không giảm trong mỗi hàng.

6. **Trophy ở (gần như) 100% thì giữ nguyên:** các phân vị là [99,5; 99,9; 100; 100; 100]. Mọi người chơi được theo dõi đều giữ nó, và lần làm mới duy nhất nhà cái từng công bố đã để nó ở 100% dù số người chơi tăng 6 lần.

## Kiểm định offline

Đáp án của các case thực hành do máy chủ giữ nên không tự chấm practice trực tiếp được. Thay vào đó, hai kiểm định độc lập (xem `BUILD_NOTES.md`):

- **Đáp án proxy cho practice.** Dựng lại tỉ lệ đáp án 04:30 UTC từ các số tổng hợp được công bố trong luật (3.868 người chơi, 4.276 trophy đã đạt; mọi tỉ lệ trừ trophy 100% đều giảm), bằng 3 cách khác nhau. Cả 3 đều tái tạo đúng các con số đã công bố của house baseline (typical miss 0,68 điểm, coverage 0; loss 1,40–1,58 so với ~1,51 đã công bố). Trên các proxy này, mô hình đạt **loss 0,35–0,44** (trung bình 2 case), typical miss ~0,19 điểm, coverage 1,00 — so với baseline 1,40–1,58 / 0,68 / 0.
- **Final giả lập.** Mô phỏng lịch sử 2,5 ngày + đáp án ngày thứ 7 bằng một cơ chế khác hẳn mô hình dự báo (số người giữ trophy là tích chập của dòng người chơi mới với đường cong theo thời gian chơi của từng trophy, trang chỉ làm mới sau mỗi vài giờ). Trên 3 seed, mô hình đạt **loss 0,23–0,25**, so với baseline persistence 0,39–0,45 và baseline đường cong ~0,26–0,29.

## Giới hạn

- Dự báo chỉ tốt bằng xu hướng mà lịch sử 2,5 ngày cho thấy; nếu tuần đầu có biến động lớn ngoài lịch sử (ví dụ một đợt người chơi mới khổng lồ cuối tuần), trung vị sẽ trệch và chỉ có dải phân vị rộng cứu điểm.
- Trường hợp lịch sử phẳng, trung vị phụ thuộc vào prior tăng trưởng người chơi; prior này là ước lượng thô, được bù bằng khoảng tin cậy rộng.
- Không có practice score thật: máy chủ mới chấm được case thực hành, nên các con số trên là kiểm định trên đáp án proxy và final giả lập, không phải điểm practice.

## Giấy phép

MIT — xem [LICENSE](LICENSE).

---

<sub>Entered on [make.fun](https://make.fun/?ref=814bp22d&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
