# HVHN — Cài thanh toán QR tự động PayOS (60.000đ → Discord)

Tài liệu này là checklist triển khai duy nhất cho luồng thanh toán mới. Làm lần lượt từ trên xuống; không bỏ qua bước kiểm thử.

## 1. Kết quả sau khi cài xong

Khách điền Form → nhận email lịch sự chứa **mã QR riêng** và nút mở trang PayOS → thanh toán đúng **60.000đ** → PayOS gửi webhook đã ký → Apps Script kiểm tra chữ ký, `orderCode` và số tiền → bot tạo link Discord một lần → khách nhận email link Discord.

Hệ thống **không còn dùng SePay, không dò nội dung chuyển khoản**. Việc ngân hàng chèn mã vào nội dung CK không ảnh hưởng đến việc xác nhận đơn.

Mỗi QR chỉ có hiệu lực **30 phút**. Khách quá hạn chỉ cần điền Form lại để có QR mới.

## 2. Những việc Codex đã làm sẵn

- Đổi code Apps Script trong `phanphoi.gs` sang PayOS.
- Khóa giá trong code là `60.000đ`; không có ô cài đặt để vô tình đổi giá.
- Tạo QR/link PayOS khác nhau cho từng đơn, lưu `PayOS orderCode`, `Payment link ID`, link thanh toán, QR raw và hạn trong tab `_don_dat_mua`.
- Xác thực webhook bằng HMAC-SHA256 với `Checksum Key` của PayOS; không dùng token bí mật nằm trên URL.
- Kiểm tra đồng thời: chữ ký hợp lệ, `orderCode` thuộc đúng đơn và số tiền đúng 60.000đ.
- Email thanh toán và email Discord đã viết lại theo mẫu HTML chuyên nghiệp; có bản chữ thuần để không lỗi ở ứng dụng mail chặn HTML.
- Có menu **HVHN → 💳 Thanh toán tự động → 🔗 Kết nối/kiểm tra webhook PayOS** để PayOS tự kiểm tra URL webhook.

## 3. Việc bạn phải làm một lần

Các bước này cần đăng nhập tài khoản của bạn nên Codex không thể tự làm thay.

### A. Đẩy code mới lên Google Apps Script

1. Mở file `D:\Bothvhn\phanphoi.gs` trên máy hoặc trong VS Code.
2. Mở Google Sheet **Phân phối - HVHN** → **Tiện ích mở rộng** → **Apps Script**.
3. Trong file code Apps Script hiện có, chọn toàn bộ nội dung rồi dán đè bằng toàn bộ nội dung `phanphoi.gs` mới.
4. Bấm **Save**.
5. Bấm **Deploy** → **Manage deployments** → bấm biểu tượng bút chì của Web app hiện có.
6. Ở **Version**, chọn **New version**.
7. Xác nhận:
   - **Execute as:** Me.
   - **Who has access:** Anyone.
8. Bấm **Deploy**, rồi copy chính xác **Web app URL** dạng `https://script.google.com/macros/s/.../exec`.
9. Tải lại Google Sheet (F5). Menu **HVHN → 💳 Thanh toán tự động** phải có dòng **“Cài đặt PayOS QR”** và **“Kết nối/kiểm tra webhook PayOS”**.

> Mỗi lần sau này thay đổi `phanphoi.gs`, phải Deploy **New version**; chỉ bấm Save thì webhook bên ngoài vẫn chạy bản cũ.

### B. Cấu hình secret cấp invite trên Render

1. Vào [Render Dashboard](https://dashboard.render.com/) → dịch vụ bot HVHN → **Environment**.
2. Thêm hoặc kiểm tra biến `HVHN_MINT_SECRET`.
3. Giá trị là một chuỗi ngẫu nhiên dài, ví dụ: `hvhn_4mQ9rT2sL8vX7kP5nC3dW6zA`.
4. Bấm **Save Changes** và đợi Render deploy xong.
5. Copy URL dịch vụ, ví dụ `https://ten-bot.onrender.com`. Không thêm `/mint-invite` vào cuối.

### C. Tạo và lấy khóa PayOS

1. Vào [PayOS](https://my.payos.vn/) và hoàn tất đăng ký/xác thực theo yêu cầu hiện hành của PayOS.
2. Tạo **Kênh thanh toán** gắn với tài khoản ngân hàng nhận tiền của bạn.
3. Trong kênh thanh toán, mở **Thông tin tích hợp** và lấy ba giá trị sau:
   - `Client ID`
   - `API Key`
   - `Checksum Key`
4. Không gửi ba khóa này qua Discord, chat nhóm hoặc commit vào GitHub. Chúng chỉ được dán vào hộp thoại cài đặt của Sheet ở bước D.

PayOS yêu cầu `Client ID` + `API Key` để tạo link và `Checksum Key` để ký/xác thực dữ liệu. Tài liệu chính thức: [PayOS API](https://payos.vn/docs/api/) và [kiểm tra webhook bằng signature](https://payos.vn/docs/tich-hop-webhook/kiem-tra-du-lieu-voi-signature/).

### D. Điền cấu hình vào Sheet

1. Mở Google Sheet → **HVHN** → **💳 Thanh toán tự động** → **⚙️ Cài đặt PayOS QR**.
2. Trả lời lần lượt 7 hộp thoại:

| Hộp | Dán/gõ chính xác |
|---|---|
| 1 | URL bot Render, ví dụ `https://ten-bot.onrender.com` |
| 2 | Giá trị `HVHN_MINT_SECRET` ở Render |
| 3 | PayOS `Client ID` |
| 4 | PayOS `API Key` |
| 5 | PayOS `Checksum Key` |
| 6 | `30` (hoặc số ngày truy cập bạn muốn bán) |
| 7 | Web app URL Apps Script đã copy ở bước A8 |

3. Khi hộp thoại báo thành công, vào **👀 Xem cài đặt hiện tại**. Tất cả các khóa phải hiện `(đã đặt)`, Web app URL phải đủ.
4. Giá luôn là **60.000đ**. Không thể đổi bằng hộp thoại; nếu sau này thực sự cần đổi giá, yêu cầu sửa hằng `PMT_FIXED_AMOUNT` trong code rồi deploy bản mới và test lại.

### E. Kết nối webhook PayOS

1. Trong Sheet, bấm **HVHN → 💳 Thanh toán tự động → 🔗 Kết nối/kiểm tra webhook PayOS**.
2. Chờ hộp thoại báo: **“PayOS đã xác thực webhook thành công.”**
3. Nếu báo lỗi, chưa được bán thật. Đọc nguyên văn lỗi ở tab **Nhật ký**, rồi kiểm tra theo thứ tự:
   - Web app URL có đúng hậu tố `/exec`, không phải `/dev`.
   - Bản Apps Script đã Deploy **New version** và quyền là **Anyone**.
   - `Client ID`, `API Key`, `Checksum Key` được dán đúng kênh PayOS.
   - Kênh thanh toán PayOS đang hoạt động.

Bạn **không cần tạo webhook trong SePay**. Nút này gọi endpoint chính thức `confirm-webhook` của PayOS để đăng ký và kiểm tra URL.

### F. Tạo Form để khách đăng ký

1. Trong Sheet: **HVHN → 💳 Thanh toán tự động → 📱 Tạo/lấy lại Form đặt mua**.
2. Copy link Form xuất hiện.
3. Mở link bằng trình duyệt ẩn danh kiểm tra hai trường: **Họ và tên** và **Email nhận link Discord**.
4. Chỉ đăng link này cho khách sau khi hoàn tất phần kiểm thử dưới đây.

## 4. Kiểm thử bắt buộc trước khi bán thật

Chuẩn bị một email phụ mà bạn có thể mở được. Không dùng email khách thật.

1. Điền Form bằng email phụ.
2. Kiểm tra email:
   - Tiêu đề phải là **[HVHN] Mã QR thanh toán 60.000đ**.
   - Có QR, mã tham chiếu `HVxxxxxxx`, nút **Mở trang thanh toán an toàn**.
   - Mở nút đó: trang PayOS phải hiện đúng 60.000đ và QR.
3. Thực hiện một giao dịch test đúng 60.000đ trên QR vừa nhận. Không sửa nội dung chuyển khoản; kể cả bị ngân hàng chèn mã, luồng vẫn phải nhận được.
4. Trong tối đa vài phút, email phụ phải nhận thư **[HVHN] Thanh toán thành công – link Discord của bạn**.
5. Mở tab `_don_dat_mua` trong Sheet, xác nhận dòng test có:
   - `Trạng thái = da_xu_ly`
   - Có `Invite URL`
   - Có `Thanh toán lúc` và `Gửi mail lúc`
   - Có `PayOS orderCode`, `Payment link ID`, `Link thanh toán`.
6. Vào Discord bằng link rồi bấm **Kích hoạt trải nghiệm**. Xác nhận role/quyền và tài liệu được xử lý đúng.
7. Kiểm tra tab **Nhật ký** có các dòng: `Đơn PayOS QR mới`, `Đã kết nối webhook PayOS`, `Đã cấp link Discord`.

Chỉ sau khi cả 7 bước đều đúng mới công khai Form.

## 5. Vận hành thường ngày

- Khách chỉ cần điền Form và quét QR trong email; quản lý không cần dò giao dịch hay ghi mã đơn thủ công.
- Tab `_don_dat_mua` là nơi theo dõi. Không sửa cột `PayOS orderCode`, `Payment link ID`, `Dữ liệu QR`.
- Nếu khách nói không thấy email QR: bảo họ kiểm tra Spam, rồi cho điền Form lại nếu QR đã quá 30 phút.
- Nếu khách đã trả tiền nhưng không nhận Discord: kiểm tra tab `Nhật ký` trước, sau đó chọn đúng dòng tại `_don_dat_mua` và dùng **🔁 Gửi lại link Discord cho đơn đang chọn**.
- Nút **🧪 Test webhook bằng mã đơn đang chọn** là thao tác thật: nó cấp invite và gửi email thật. Chỉ dùng với đơn test hoặc khi hiểu rõ hậu quả.

## 6. Các trạng thái cần hiểu

| Trạng thái | Ý nghĩa | Bạn làm gì |
|---|---|---|
| `dang_tao_qr` | Trigger đang gọi PayOS | Chờ ngắn; nếu kẹt, xem Nhật ký. |
| `cho_thanh_toan` | QR/link đã gửi, chưa có webhook thanh toán | Không cần làm gì. |
| `da_xu_ly` | Đã xác nhận tiền, đã xin invite và gửi mail | Hoàn tất. |
| `loi_tao_qr` | Không tạo được link PayOS | Xem Ghi chú + Nhật ký; kiểm tra ba khóa và kênh PayOS. |
| `mint_loi` | PayOS đã báo tiền nhưng bot chưa tạo được invite | Kiểm tra Render/`HVHN_MINT_SECRET`; sau đó dùng nút gửi lại link. |

## 7. An toàn và các giới hạn thực tế

- Không dùng lại SePay cho luồng mới. Có thể giữ tài khoản SePay cho mục đích khác, nhưng không cần webhook SePay.
- PayOS/đơn vị cung cấp QR có điều khoản, xác thực và biểu phí riêng theo tài khoản/kênh; kiểm tra trực tiếp trong dashboard PayOS trước khi mở bán.
- QR hình trong email được tạo để tiện quét; nút **Mở trang thanh toán an toàn** vẫn là đường chính thức và là phương án dự phòng khi ứng dụng mail chặn ảnh.
- Webhook PayOS không cấp quyền chỉ vì khách mở trang “thành công”; chỉ webhook có HMAC hợp lệ, đúng `orderCode` và đúng 60.000đ mới cấp Discord.
- Không bao giờ dán `API Key`, `Checksum Key` hay `HVHN_MINT_SECRET` vào `phanphoi.gs`, `.env` commit, ảnh chụp màn hình hay chat công khai.

## 8. Khi cần hỗ trợ

Gửi cho người sửa hệ thống ba thứ, không gửi secret:

1. Ảnh/copy nguyên văn dòng lỗi trong tab `Nhật ký`.
2. Ảnh dòng đơn đã che email và link Discord.
3. Thời điểm phát sinh lỗi (giờ/phút, múi giờ Việt Nam).

Không gửi `Client ID`, `API Key`, `Checksum Key` hoặc `HVHN_MINT_SECRET`.
