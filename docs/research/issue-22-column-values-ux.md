# Nghiên cứu UX: giá trị nghiệp vụ trong Bảng & cột

## Đề xuất

Đặt mục **Giá trị nghiệp vụ** ngay bên dưới thông tin mỗi cột trong tab **Bảng & cột**, mặc định thu gọn. Nút mở hiển thị số giá trị đã duyệt và số giá trị đang chờ. Người dùng mở mục tại đúng cột cần cấu hình, nhập nhiều cặp giá trị DB và ý nghĩa nghiệp vụ, rồi lưu và duyệt theo quyền. Bỏ ô nhập mảng JSON cũ để tránh hai cách sửa cùng dữ liệu.

```text
orders
  order_status · TEXT                 Đã duyệt cột
  Tên nghiệp vụ [Trạng thái đơn]   Mô tả [...]  [Lưu cột]
  ▸ Giá trị nghiệp vụ · 2 đã duyệt · 1 chờ duyệt

  Khi mở:
  Giá trị trong DB        Giá trị nghiệp vụ             Trạng thái
  [pending          ]     [Chờ xử lý              ]     Đã duyệt  [Xóa]
  [processing       ]     [Đang xử lý             ]     Chờ duyệt [Xóa]
  [+ Thêm giá trị]
  Phạm vi: (•) Tham khảo  ( ) Đầy đủ
  Danh sách tham khảo có thể chưa chứa mọi giá trị trong DB.
  [Lưu thay đổi]  [Duyệt các giá trị đang chờ]
```

Đây là đề xuất cần thử với người dùng thực tế, chưa phải kết quả kiểm chứng tính dễ dùng.

## Cơ sở thiết kế

- [Carbon Data Table](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines) dùng phần mở rộng của hàng để hiện thông tin bổ sung và cho phép trì hoãn tải dữ liệu. Nếu phần chỉnh sửa trở nên chật, Carbon khuyến nghị cân nhắc side panel hoặc trang riêng. Vì bảng đã có phần mở, đề xuất thêm một nút mở rõ tên dưới mỗi cột và chỉ tải mapping khi mở.
- [W3C WAI Accordion](https://www.w3.org/WAI/ARIA/apg/patterns/accordion/) mô tả nút mở bằng Enter/Space, trạng thái `aria-expanded`, quan hệ `aria-controls` và thứ tự Tab. Nếu chỉ có một nút mở vùng giá trị, có thể theo [Disclosure Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/) thay vì thêm landmark cho mọi cột.
- [W3C WAI Labels](https://www.w3.org/WAI/tutorials/forms/labels/) yêu cầu nhãn xác định mục đích của từng điều khiển. Nhãn cần gắn với từng ô, kể cả khi giao diện hiển thị tiêu đề chung; nút xóa phải gọi rõ dòng hoặc giá trị đang xóa.
- [W3C WAI Notifications](https://www.w3.org/WAI/tutorials/forms/notifications/) khuyến nghị thông báo lỗi nêu trường liên quan và cách sửa; giữ nguyên dữ liệu các dòng khi lưu lỗi theo [WAI Easy Checks](https://www.w3.org/WAI/test-evaluate/preliminary/).
- [GOV.UK Check Answers](https://design-system.service.gov.uk/patterns/check-answers/) đặt thao tác thay đổi cạnh nội dung cần sửa. Áp dụng ở đây bằng việc giữ lưu/duyệt ngay tại cột và hiện trạng thái cạnh từng cặp, để người duyệt thấy rõ phạm vi thao tác.

## Hành vi cần thống nhất khi triển khai

- Mỗi dòng giữ nguyên kiểu và giá trị DB, bao gồm phân biệt chuỗi `"1"`, số `1` và boolean. Báo lỗi gần dòng cho giá trị trùng hoặc trường bắt buộc thiếu; thêm dòng bằng nút bên dưới danh sách, xóa bằng nút rõ nhãn.
- Mặc định **Tham khảo**: không từ chối giá trị ngoài danh sách. **Đầy đủ** chỉ được chọn khi người dùng xác nhận danh sách bao phủ toàn bộ miền giá trị; hiển thị rõ hệ quả. Không tự quét dữ liệu để suy luận độ đầy đủ.
- Nhãn **Đã duyệt**, **Chờ duyệt**, **Đã bỏ qua** thể hiện bằng chữ. Lưu mới/sửa đổi tạo trạng thái chờ; duyệt giá trị là thao tác riêng với duyệt tên và mô tả bảng/cột. Chỉ hiện hoặc bật thao tác theo quyền; thông báo rõ khi người dùng không có quyền duyệt.
- Cần bảo vệ bản sửa chưa lưu khi đóng vùng, đổi tab hoặc dữ liệu nền được tải lại. Không cho duyệt dữ liệu đang sửa chưa lưu; thao tác duyệt chỉ áp dụng các dòng chờ đã lưu, hiển thị số dòng được duyệt.
- Desktop bố trí hai ô theo hàng; màn hình hẹp xếp dọc từng cặp, giữ nhãn và nút xóa theo từng dòng. Tập trung vào ô đầu tiên sau khi thêm; sau khi xóa chuyển focus hợp lý. Có trạng thái tải, rỗng, lỗi, lưu thành công và có thể thử lại.
- Bảo đảm các đường ghi cũ không ghi đè hoặc đưa dữ liệu chưa duyệt vào consumer. Cần kiểm tra riêng quyền, độ đầy đủ, cập nhật đồng thời, dữ liệu `allowed_values` cũ và consumer của metric/query compiler khi thực hiện.

## Giới hạn

Chưa khảo sát Data Engineer/Data Lead hoặc thử prototype trên desktop, di động và công nghệ hỗ trợ. Nên kiểm tra các nhiệm vụ thêm hai giá trị, sửa giá trị đã duyệt, xác định danh sách đầy đủ và phân biệt duyệt cột với duyệt giá trị trước khi chốt chi tiết.
