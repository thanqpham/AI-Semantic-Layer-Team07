# Hỗ trợ nguồn dữ liệu EAV

Hướng dẫn khai báo và truy vấn nguồn EAV (Entity–Attribute–Value). Áp dụng cho cả
Flow 1 (khai báo / duyệt cấu hình, tạo metric) và Flow 2 (truy vấn chỉ đọc qua
`SemanticQueryCompiler`).

## Tổng quan

Một nguồn EAV lưu giá trị thuộc tính theo dòng thay theo cột: mỗi dòng là một
cặp (thực thể, thuộc tính, giá trị). Để truy vấn được, hệ thống cần biết:

- **Bảng entity** chứa các dòng EAV và **cột định danh thực thể** (`entity_id_column`).
- Cách nhận diện **thuộc tính của mỗi dòng** — mã trực tiếp (`direct`) hoặc qua bảng từ điển (`dictionary`).
- **Cột giá trị** theo kiểu dữ liệu (`value_columns`, ví dụ `{"number": "value_num", "string": "value_str"}`). Mỗi thuộc tính có thể **ghi đè** bằng `value_column` riêng (ví dụ thuộc tính có cột giá trị chuyên biệt của nó); nếu để trống, dùng cột mặc định theo kiểu dữ liệu.

Quy trình: khai báo cấu hình (chờ duyệt) → Data Lead duyệt → tạo metric từ thuộc
tính → duyệt metric → truy vấn.

> EAV chỉ hỗ trợ nguồn **Live DB**. SQL Dump không hỗ trợ khai báo EAV (409).

## Biến thể schema

### Direct — mã thuộc tính nằm ngay trên dòng

```json
{
  "name": "EAV chính",
  "entity_table": "entity_eav",
  "entity_id_column": "entity_id",
  "attribute_mode": "direct",
  "attribute_column": "attr_code",
  "value_columns": {"number": "value_num", "string": "value_str"},
  "attributes": [
    {"attribute_key": "revenue", "label": "Doanh thu", "data_type": "number", "multi_value_rule": "reject"},
    {"attribute_key": "region", "label": "Khu vực", "data_type": "string", "multi_value_rule": "reject"}
  ]
}
```

Mỗi dòng có `attr_code = 'revenue'` là một giá trị doanh thu của thực thể.

### Dictionary — mã thuộc tính là FK sang bảng từ điển

Dùng khi dòng chỉ chứa mã (FK) và tên hiển thị nằm ở bảng từ điển:

```json
{
  "attribute_mode": "dictionary",
  "attribute_column": "attr_fk",
  "dict_table": "attr_dict",
  "dict_key_column": "dict_code",
  "dict_label_column": "dict_label"
}
```

Khi truy vấn, thuộc tính được đối chiếu theo **nhãn** (`dict_label`), hệ thống tự
dịch sang mã qua bảng từ điển.

## Quy tắc đa giá trị (`multi_value_rule`)

Một thực thể có thể có nhiều dòng cho cùng một thuộc tính. Quy tắc quyết định
cách xử lý khi biên dịch:

| Quy tắc | Ý nghĩa | Cách SQL biên dịch |
|---------|---------|--------------------|
| `reject` | Mỗi thực thể chỉ được có MỘT giá trị | Truy vấn chạy **precheck** trước: nếu phát hiện thực thể có nhiều giá trị → lỗi `EAV_MULTI_VALUE`, từ chối thực thi |
| `sum` | Cộng các giá trị (chỉ kiểu `number`, chỉ dùng làm metric) | `SUM` trong subquery theo thực thể trước khi join |
| `avg` | Trung bình các giá trị (chỉ `number`, chỉ metric) | `AVG` trong subquery theo thực thể |
| `min` / `max` | Giá trị nhỏ/lớn nhất | `MIN` / `MAX` trong subquery theo thực thể |
| `first` / `last` | **Chưa hỗ trợ** | Lỗi `EAV_RULE_UNSUPPORTED` (không có cột thứ tự dòng) |

Thiết kế "aggregate trước join" đảm bảo mỗi thuộc tính chỉ tạo một dòng trên
thực thể nên kết quả không bị nhân đôi (fan-out).

## History (giá trị theo thời gian)

`history_enabled` là **cờ của từng thuộc tính** (trên UI: checkbox "History" trên
mỗi dòng thuộc tính khi khai báo) — chỉ bật cho thuộc tính thực sự có hiệu lực
theo thời gian. Thuộc tính có `history_enabled: true` yêu cầu cấu hình khai báo cột thời gian:

```json
"history": {"effective_column": "eff_at", "end_column": "end_at"}
```

Khi truy vấn:

- **Có `as_of`** (chọn thời điểm): lấy dòng có `eff_at <= as_of` và
  (`end_at IS NULL` hoặc `end_at > as_of`) — giá trị đúng tại thời điểm đó.
- **Không có `as_of`**: lấy giá trị hiện hành (`end_at IS NULL`). Nếu cấu hình
  thiếu `end_column`, bắt buộc phải truyền `as_of` (lỗi `EAV_AS_OF_REQUIRED`)
  vì không xác định được giá trị "mới nhất".

Thuộc tính không bật history bỏ qua `as_of`.

## Giới hạn

- **Không trộn**: metric EAV không truy vấn cùng metric/dimension/filter quan
  hệ trong một truy vấn (`EAV_MIXED_SELECTION`); các metric EAV trong cùng truy
  vấn phải thuộc **một** cấu hình (`INCOMPATIBLE_BASE_ENTITY`).
- **Cấu hình phải được duyệt** trước khi metric dùng thuộc tính của nó
  (`EAV_CONFIG_NOT_APPROVED`); metric cũng phải ở trạng thái approved.
- Quy tắc `sum`/`avg` chỉ cho thuộc tính kiểu `number` và chỉ vai trò metric.
- Flow 2 vẫn giữ toàn bộ guardrail: chỉ `SELECT` chỉ đọc, `LIMIT 100`
  (tối đa 1000), `statement_timeout` 15s.
- Precheck đa giá trị (quy tắc `reject`) chạy trong cùng giao dịch chỉ đọc ngay
  trước truy vấn chính — vi phạm thì từ chối với mã `EAV_MULTI_VALUE` (HTTP 400).

## Ví dụ truy vấn

Yêu cầu: tổng doanh thu (`revenue`, SUM) theo khu vực (`region`):

```json
POST /api/v1/semantic/{db_id}/query
{
  "metric_ids": [42],
  "eav_dimensions": [{"attribute_id": 12}],
  "limit": 100
}
```

Với `as_of` cho thuộc tính có history:

```json
{
  "metric_ids": [42],
  "eav_dimensions": [{"attribute_id": 12}],
  "as_of": "2026-05-01T00:00:00",
  "limit": 100
}
```

Bộ lọc theo thuộc tính EAV:

```json
{
  "metric_ids": [42],
  "eav_filters": [{"attribute_id": 12, "operator": "eq", "value": "Miền Bắc"}],
  "limit": 100
}
```

Toàn bộ yêu cầu truy vấn đều qua `SemanticQueryCompiler` — không có text-to-SQL
tự do.

## Dữ liệu mẫu

Chạy script tạo target DB mẫu (sqlite mặc định):

```bash
python scripts/setup_target_eav_db.py                     # scratch/eav_demo.db
python scripts/setup_target_eav_db.py --dialect postgres | psql <url>
```

Script tạo bảng `entity_eav` + `attr_dict` với 4 thực thể, gồm cả ca đa giá trị
(`clicks`, quy tắc sum) và ca history (`segment`). Số liệu kỳ vọng:
tổng `revenue` theo `region` — Miền Bắc 300, Miền Nam 125.

## Mã lỗi

| Mã | Ý nghĩa |
|----|---------|
| `EAV_MULTI_VALUE` | Thuộc tính quy tắc `reject` có nhiều giá trị trên một thực thể |
| `EAV_CONFIG_NOT_APPROVED` | Cấu hình nguồn EAV chưa được duyệt |
| `EAV_MIXED_SELECTION` | Trộn metric EAV với metric/dimension/filter quan hệ |
| `EAV_RULE_UNSUPPORTED` | Quy tắc đa giá trị không áp dụng được (first/last, sum cho chuỗi…) |
| `EAV_VALUE_COLUMN_MISSING` | Cấu hình thiếu cột giá trị cho kiểu dữ liệu |
| `EAV_HISTORY_CONFIG_MISSING` | Thuộc tính bật history nhưng cấu hình thiếu cột thời gian |
| `EAV_AS_OF_REQUIRED` | Cần truyền `as_of` vì cấu hình history thiếu `end_column` |
| `INCOMPATIBLE_BASE_ENTITY` | Các thuộc tính thuộc nhiều cấu hình khác nhau |
