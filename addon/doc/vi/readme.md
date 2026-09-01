# Polyglot cho NVDA

Polyglot là một add-on toàn cục dành cho NVDA, tập trung vào khả năng dịch thuật đa ngôn ngữ nhanh chóng và linh hoạt. Add-on này có thể dịch văn bản đang được chọn, nội dung trong bộ nhớ tạm, đoạn văn bản được NVDA đọc gần nhất, và cũng có thể chặn nội dung giọng đọc để dịch tự động trực tiếp.

Add-on được xây dựng trên cấu trúc bộ dịch động. Các bộ dịch sẽ tự khai báo khả năng và sơ đồ cấu hình của riêng mình, từ đó giao diện cài đặt sẽ được tạo tự động dựa trên sơ đồ đó khi chạy ứng dụng. Điều này giúp cho phần cốt lõi của plugin luôn gọn nhẹ nhưng lại rất dễ dàng để tích hợp thêm các dịch vụ mới.

## Các tính năng chính

- Dịch văn bản đang chọn, văn bản trong bộ nhớ tạm và câu nói gần nhất của NVDA.
- Cung cấp một lớp lệnh dịch thuật qua tổ hợp `NVDA+Alt+Z`; nhấn `H` khi đang ở trong lớp lệnh để xem trợ giúp.
- Hỗ trợ dịch tự động trực tiếp nội dung giọng đọc của NVDA.
- Tích hợp bộ lọc giọng đọc thông minh giúp loại bỏ các thông tin gây nhiễu không cần dịch như vai trò, trạng thái và định dạng.
- Lưu bộ nhớ đệm dịch thuật để giảm các yêu cầu trùng lặp.
- Có thể tự động sao chép kết quả dịch thủ công vào bộ nhớ tạm.
- Cho phép chuyển đổi bộ dịch và ngôn ngữ ngay trên bàn phím mà không cần rời khỏi cửa sổ đang làm việc.
- Cung cấp một hộp thoại dịch thuật tương tác chuyên dụng dành cho các văn bản dài hoặc khi cần dịch lặp đi lặp lại.

## Cài đặt

Cách cài đặt được khuyến nghị là thông qua Cửa hàng Add-on của NVDA (NVDA Add-on Store). Bạn cũng có thể cài đặt thủ công bằng cách:

1. Tải xuống gói `.nvda-addon` mới nhất từ [Trang phát hành](https://github.com/cary-rowen/polyglot/releases).
2. Mở tệp vừa tải xuống.
3. Xác nhận cài đặt trong NVDA.
4. Khởi động lại NVDA khi được yêu cầu.

## Khởi động nhanh

1. Mở `Trình đơn NVDA -> Tùy Chọn -> Cấu hình -> Polyglot`.
2. Chọn một bộ dịch và đảm bảo rằng bộ dịch đó đã được bật.
3. Cấu hình các thông tin xác thực cần thiết (nếu có) cho bộ dịch đó.
4. Thiết lập ngôn ngữ nguồn và ngôn ngữ đích.
5. Tùy chọn bật tính năng tự động sao chép vào bộ nhớ tạm và bộ lọc giọng đọc thông minh.
6. Nhấn `NVDA+Alt+Z`, sau đó sử dụng một trong các phím thuộc lớp lệnh bên dưới. Nhấn `H` trong lớp lệnh để xem trợ giúp.

## Lớp lệnh

Nhấn `NVDA+Alt+Z` để vào lớp lệnh. Một tiếng bíp ngắn sẽ phát ra để xác nhận lớp lệnh đang hoạt động. Nhấn `H` trong lớp lệnh để xem trợ giúp về lớp lệnh. Hầu hết các lệnh sẽ thực thi một lần rồi thoát khỏi lớp lệnh. Các lệnh chuyển đổi ngôn ngữ và bộ dịch sẽ giữ bạn ở lại trong lớp lệnh để bạn có thể tiếp tục xoay vòng chuyển đổi. Việc chuyển đổi bộ dịch sẽ chỉ xoay vòng qua các bộ dịch đã được bật.

| Phím | Hành động |
| --- | --- |
| `T` | Dịch nội dung đang chọn. |
| `Shift+T` | Dịch nội dung đang chọn theo chiều ngược lại. |
| `B` | Dịch văn bản trong bộ nhớ tạm. |
| `Shift+B` | Dịch văn bản trong bộ nhớ tạm theo chiều ngược lại. |
| `L` | Dịch nội dung văn bản vừa được NVDA đọc gần nhất. |
| `Shift+L` | Dịch nội dung văn bản vừa được NVDA đọc gần nhất theo chiều ngược lại. |
| `S` | Ngôn ngữ nguồn tiếp theo. |
| `Shift+S` | Ngôn ngữ nguồn trước đó. |
| `G` | Ngôn ngữ đích tiếp theo. |
| `Shift+G` | Ngôn ngữ đích trước đó. |
| `E` | Bộ dịch đã bật tiếp theo. |
| `Shift+E` | Bộ dịch đã bật trước đó. |
| `W` | Hoán đổi ngôn ngữ nguồn và ngôn ngữ đích. |
| `A` | Đọc bộ dịch và cặp ngôn ngữ hiện tại. |
| `C` | Sao chép kết quả dịch gần nhất. |
| `V` | Bật/tắt dịch tự động. |
| `I` | Mở hộp thoại dịch thuật tương tác. |
| `O` | Mở cài đặt Polyglot. |
| `X` | Xóa bộ nhớ đệm dịch thuật. |
| `H` | Hiển thị trợ giúp về lớp lệnh. |

## Hộp thoại dịch thuật tương tác

Hộp thoại tương tác được thiết kế dành cho các văn bản dài và công việc dịch thuật cần chỉnh sửa nhiều lần.

- Mở hộp thoại từ lớp lệnh bằng phím `I`.
- Chọn bộ dịch đã bật, ngôn ngữ nguồn và ngôn ngữ đích ngay trong hộp thoại mà không cần thoát ra ngoài.
- Các bộ dịch bị tắt vẫn có thể cấu hình được trong phần cài đặt chung, nhưng sẽ không hiển thị trong hộp thoại này.
- Đối với các bộ dịch dạng mô hình ngôn ngữ lớn (LLM), bạn có thể điều chỉnh mô hình và mẫu lời nhắc trực tiếp ngay trong hộp thoại.
- Nhấn `Ctrl+Enter` tại ô văn bản nguồn để thực hiện dịch.
- Sao chép kết quả hoặc xóa trống cả hai ô mà không cần phải mở lại cửa sổ.

## Hướng dẫn cài đặt

### Cài đặt chung

- `Sao chép kết quả dịch thủ công vào bộ nhớ tạm`: Tự động sao chép kết quả dịch thủ công sau khi yêu cầu dịch thành công.
- `Bật bộ lọc giọng đọc thông minh`: Khi dịch nội dung nói của NVDA, bộ lọc sẽ bỏ qua các lời thoại không phải nội dung chính như vai trò, trạng thái, vị trí và chi tiết định dạng nếu có thể.
- `Xóa bộ nhớ đệm`: Xóa bộ nhớ đệm dịch thuật đã lưu và hiển thị số lượng mục hiện tại ngay trên nhãn của nút bấm.

### Cài đặt dùng chung cho các bộ dịch

Hầu hết các bộ dịch đều kế thừa một tập hợp các cài đặt chung:

- `Bật bộ dịch này`: Kiểm soát việc bộ dịch này có sẵn sàng cho các yêu cầu dịch, chuyển đổi bộ dịch trong lớp lệnh và hiển thị trong hộp thoại tương tác hay không. Các bộ dịch bị tắt vẫn sẽ hiển thị và có thể cấu hình được trong phần cài đặt.
- `Ngôn ngữ nguồn` và `Ngôn ngữ đích`
- `Chế độ Proxy`: Sử dụng cài đặt proxy của hệ thống hoặc tắt tính năng sử dụng proxy.
- `Thời gian chờ yêu cầu`

Nếu bộ dịch có hỗ trợ báo cáo ngôn ngữ nguồn phát hiện được, Polyglot cũng sẽ cung cấp thêm:

- `Tự động hoán đổi nếu nguồn phát hiện trùng với đích`: Rất hữu ích khi ngôn ngữ nguồn được đặt là tự động phát hiện.
- `Ngôn ngữ hoán đổi sang`: Ngôn ngữ đích thay thế được sử dụng trong quá trình tự động hoán đổi.

### Hành vi dịch tự động

- Tính năng dịch tự động sẽ tác động lên nội dung nói của NVDA được thu thập từ quy trình xử lý giọng đọc.
- Add-on sẽ tự động chặn các thông báo giọng đọc của chính nó để tránh rơi vào vòng lặp dịch thuật vô hạn.
- Nếu tính năng dịch tự động bị lỗi 3 lần liên tiếp, nó sẽ tự động tắt.
- Bộ lọc giọng đọc thông minh chủ yếu ảnh hưởng đến việc dịch nội dung giọng đọc phát ra, không ảnh hưởng đến việc dịch văn bản thủ công tiêu chuẩn.

### Các tùy chọn dành riêng cho LLM và Polyglot

Một số bộ dịch sẽ hiển thị thêm các trình điều khiển bổ sung:

- `Ollama 1` và `Ollama 2` cung cấp hai cấu hình lưu trữ riêng biệt cho các thiết lập Ollama cục bộ hoặc từ xa khác nhau.
- `OpenRouter` hiển thị các trường API URL, khóa API, mô hình đặt trước, tên mô hình tùy chỉnh, mẫu lời nhắc và các lời nhắc tùy chỉnh.
- Các bộ dịch `Ollama` hiển thị API URL, tên mô hình, khóa API tùy chọn, mẫu lời nhắc và các lời nhắc tùy chỉnh.
- `Google Translate (Polyglot)` hiển thị một trường API URL endpoint và trường khóa API có thể cấu hình.
- `Google Translate (key-free)` cung cấp một nút công tắc bật/tắt máy chủ dự phòng tùy chọn.

## Dịch ngoại tuyến bằng Chrome AI

Polyglot có thể sử dụng API dịch thuật tích hợp sẵn của Chrome để dịch ngoại tuyến. Quá trình dịch thuật được xử lý bởi một tiến trình Chrome cục bộ lập riêng biệt, vì vậy văn bản sẽ không bị gửi đến bất kỳ dịch vụ dịch thuật bên thứ ba nào.

### Yêu cầu hệ thống

- Máy tính phải được cài đặt Google Chrome.
- Khuyến nghị sử dụng Chrome phiên bản 138 trở lên.
- Lần đầu tiên sử dụng một chiều ngôn ngữ nào đó, mô hình dịch thuật cục bộ cần phải được chuẩn bị trước. Polyglot có thể tải xuống mô hình này thông qua trình quản lý mô hình của nó, hoặc bạn có thể để Chrome tự tải xuống.

### Cách sử dụng

Chọn `Chrome AI (Offline)` trong phần cài đặt Polyglot, sau đó chọn ngôn ngữ nguồn và ngôn ngữ đích. Chrome AI yêu cầu phải có ngôn ngữ nguồn rõ ràng; tùy chọn `Tự động phát hiện` không khả dụng cho bộ dịch này, nhờ đó Polyglot có thể kiểm tra mô hình cần thiết trước khi khởi chạy Chrome.

Trong lần đầu sử dụng, nếu mô hình cần thiết chưa được cài đặt, Polyglot sẽ hỏi bạn muốn tiếp tục như thế nào. Chọn Có để tải xuống và cài đặt mô hình bằng trình quản lý mô hình của Polyglot; hãy dùng cách này nếu dịch vụ tải mô hình của Chrome quá chậm, bị chặn hoặc không ổn định trên mạng của bạn. Chọn Không để Chrome tự tải xuống mô hình. Chọn Hủy bỏ để hủy lượt dịch hiện tại. Sau khi mô hình đã sẵn sàng, quá trình dịch sẽ tự động tiếp tục.

### Mạng và Mô hình

Quá trình dịch thuật diễn ra hoàn toàn cục bộ. Các mô hình có thể được cài đặt bởi trình quản lý mô hình của Polyglot hoặc được tải xuống bởi Chrome. Nếu dịch vụ tải mô hình của Chrome quá chậm hoặc không khả dụng trên mạng của bạn, hãy chọn Có khi có hộp thoại nhắc, hoặc mở Trình quản lý mô hình ChromeAI Polyglot từ menu Công cụ (Tools) của NVDA để cài đặt hoặc gỡ bỏ các mô hình ngoại tuyến trước.

### Quyền riêng tư và Dữ liệu

Polyglot sử dụng một thư mục dữ liệu Chrome tách biệt dành cho Chrome AI, vì vậy nó không ảnh hưởng đến hồ sơ (profile) Chrome thông thường của bạn. Các mô hình, dữ liệu bộ nhớ đệm và dữ liệu thực thi được lưu giữ để tránh việc phải tải xuống lại nhiều lần.

Đường dẫn mặc định là:

```text
%LOCALAPPDATA%\Polyglot\ChromeAI
```

Nếu biến môi trường `LOCALAPPDATA` không khả dụng, Polyglot sẽ dùng thư mục tạm thời `polyglot_chrome_ai` nằm dưới thư mục cấu hình của NVDA.

Khi NVDA thoát, Polyglot sẽ đóng tiến trình Chrome mà nó đã khởi chạy.

### Hạn chế

- Các ngôn ngữ và cặp ngôn ngữ được hỗ trợ sẽ do API dịch thuật của Chrome quyết định.
- Chrome AI yêu cầu phải có ngôn ngữ nguồn rõ ràng; không hỗ trợ tính năng `Tự động phát hiện`.
- Lần đầu sử dụng yêu cầu mô hình phải được chuẩn bị sẵn; việc tải xuống mô hình có thể bị ảnh hưởng bởi điều kiện mạng.
- Nếu API dịch thuật không khả dụng, hãy cập nhật Chrome hoặc đảm bảo rằng tính năng liên quan của Chrome đã được bật.

## Tổng quan về các bộ dịch

Kho lưu trữ hiện tại bao gồm các bộ dịch sau:

| Bộ dịch | Thông tin xác thực | Ghi chú |
| --- | --- | --- |
| `Baidu Translate` | Baidu app ID và secret | Tích hợp API chuẩn của nhà cung cấp. |
| `Caiyun` | Caiyun token | Tích hợp API chuẩn của nhà cung cấp. |
| `Chrome AI (Offline)` | Không có | Sử dụng API dịch thuật tích hợp sẵn của Chrome với các mô hình cục bộ; yêu cầu chọn rõ ràng ngôn ngữ nguồn. |
| `DeepL` | DeepL API key | Tích hợp API chuẩn của nhà cung cấp. |
| `Google Translate (key-free)` | Không có | Hỗ trợ nút bật/tắt chuyển đổi sang máy chủ dự phòng tùy chọn. |
| `Google Translate (Polyglot)` | Khóa API và endpoint có thể cấu hình | Đi kèm với các giá trị endpoint mặc định trong mã nguồn; tính khả dụng tùy thuộc vào trạng thái dịch vụ. |
| `Microsoft Translator (key-free)` | Không có | Tự động lấy mã token tạm thời. |
| `Niutrans` | Niutrans API key | Tích hợp API chuẩn của nhà cung cấp. |
| `Ollama 1` | Ollama URL, tên mô hình, khóa tùy chọn | Cấu hình hồ sơ Ollama đã lưu thứ nhất. |
| `Ollama 2` | Ollama URL, tên mô hình, khóa tùy chọn | Cấu hình hồ sơ Ollama đã lưu thứ hai. |
| `OpenRouter` | OpenRouter API key | Hỗ trợ các mô hình đặt trước và mẫu lời nhắc có thể chỉnh sửa. |
| `Tencent Translate` | Tencent secret ID và secret key | Tích hợp API chuẩn của nhà cung cấp. |
| `Tencent Translate (Polyglot)` | Tên người dùng và mật khẩu NVDACN | Tuyến đường Tencent được hỗ trợ bởi Polyglot. |
| `VIVO Translate` | Tên người dùng và mật khẩu NVDACN | Tập hợp ngôn ngữ hạn chế, không có tính năng tự động phát hiện ngôn ngữ nguồn. |
| `Volcengine (Polyglot)` | Tên người dùng và mật khẩu NVDACN | Tuyến đường Volcengine được hỗ trợ bởi Polyglot. |
| `Yandex Translate` | Không có | Endpoint dạng công cộng, không có báo cáo ngôn ngữ phát hiện được. |

## Đóng góp phát triển

Mọi đóng góp luôn được chào đón từ mã nguồn, tài liệu, bản dịch ngôn ngữ, kiểm thử cho đến tích hợp các bộ dịch mới.

- Báo cáo lỗi: [GitHub Issues](https://github.com/cary-rowen/polyglot/issues)
- Các bản phát hành: [GitHub Releases](https://github.com/cary-rowen/polyglot/releases)

Khi thêm một bộ dịch mới:

1. Tạo một module tại thư mục `addon/globalPlugins/polyglot/services/engines/`.
2. Triển khai lớp `TranslationEngine` hoặc đối với các bộ dịch HTTP, mở rộng từ lớp `BaseHttpEngine`.
3. Trả về một đặc tả cấu hình (config spec) từ hàm `getConfigSpec()` nếu bộ dịch đó cần các cài đặt.
4. Sử dụng các loại trình điều khiển được hỗ trợ từ `views/factory.py`: `choice`, `text`, `password`, `checkbox`, và `spinctrl`.
5. Xác minh bộ dịch hiển thị chính xác trong bảng cài đặt động, và khi được bật, kiểm tra hoạt động chuyển đổi trong lớp lệnh cũng như trong hộp thoại tương tác.

## Giấy phép

Bản quyền (C) 2025-2026 cary-rowen.

Dự án này được cấp phép theo Giấy phép Công cộng GNU phiên bản 3 hoặc bất kỳ phiên bản nào sau đó
(`GPL-3.0-or-later`). Giấy phép được kèm theo gói tiện ích; xem thêm [COPYING.txt](https://github.com/cary-rowen/polyglot/blob/master/COPYING.txt) trong kho mã nguồn.
