# Thẩm định metric AI trước HITL

Luồng hoạt động: chuẩn bị context → sinh đề xuất → kiểm tra kỹ thuật →
Metric Reviewer Agent → tối đa một lượt sửa và kiểm tra lại → người duyệt.
Reviewer gọi model riêng với cùng cấu hình `get_llm(role="metric")`, temperature 0;
đây chưa phải một model Judge độc lập.

## Metric Workflow Coordinator và giao tiếp nội bộ

LangGraph điều phối Metric Designer Agent → kiểm tra kỹ thuật bằng code →
Metric Reviewer Agent. Đọc schema và Metric Workflow Coordinator là các bước backend, không phải agent độc lập. Khi cần sửa, Metric Workflow Coordinator
chỉ giao lại các KPI lỗi, tối đa một lượt. Metric Reviewer Agent trả JSON hỏng thì chỉ gọi lại
Reviewer; không sinh lại các định nghĩa đã hợp lệ.

Builder phải trả `MetricDefinition` đầy đủ cho trạng thái `ready`. Mô tả công thức
trong `reason` hoặc `definition=null` không đủ để chuyển sang thẩm định nghiệp vụ.
KPI chưa khả thi có contract riêng với lý do và trạng thái rõ ràng. Một phần tử
hỏng không làm mất các KPI hợp lệ trong cùng batch. Builder và Reviewer đều làm
việc theo batch để giảm lượt gọi model.

Backend cấp task ID và candidate ID, đối chiếu phản hồi theo từng KPI và không áp dụng
phản hồi trùng hoặc sai ID. Báo cáo và trace nằm trong JSON proposal/chat hiện có;
không tạo thông điệp bàn giao giả cho các lời gọi hàm trong cùng backend.
Không cần migration mới. Đây là giao tiếp trong backend, chưa phải A2A qua mạng.

Thiết kế tham khảo các cơ chế giới hạn hop và chống gửi lặp của
[Rakazo bot messages](https://github.com/elie222/rakazo/blob/6de958f0608248d82f655cf5b88e8eacdf030341/packages/adapters/src/bot-messages.ts).

## Sử dụng

Trong Studio, nhập yêu cầu một KPI hoặc chọn **Đề xuất KPI** để nhận gợi ý dựa trên schema.
Yêu cầu chưa chọn công thức có thể tạo tối đa 5 biến thể khả thi thành 5 proposal riêng.
Mỗi tên nêu rõ các tiêu chí ảnh hưởng kết quả; báo cáo lưu `variant_id`, `criteria`
và nguồn đúng của biến thể. Yêu cầu đã chọn trước thuế không nhận biến thể gồm VAT.
Nếu không chứng minh được ánh xạ cột hoặc trạng thái, AI hỏi người yêu cầu thay vì
đưa giả định ngầm vào proposal đạt. Data Lead chỉ duyệt ở gate cuối.
Hệ thống giữ yêu cầu gốc, tham chiếu tin nhắn, lựa chọn làm rõ và metadata;
context vượt ngân sách sẽ yêu cầu thu hẹp phạm vi hoặc mở hội thoại mới.
Không có bước lấy mẫu hay chạy truy vấn dữ liệu doanh nghiệp.

Đề xuất đạt hiển thị **AI đã thẩm định — chờ người duyệt**. Mở báo cáo để xem
yêu cầu đã đối chiếu, nhận xét, nguồn và định nghĩa trước/sau. Member gửi request
cho Data Lead; Lead lưu đề xuất vào catalog chờ duyệt. Luồng duyệt request hiện có
vẫn là hành động con người tạo và phê duyệt metric. AI không tự xuất bản.

Đề xuất `needs_revision`, `needs_clarification`, `rejected`, `unsupported` hoặc
`error` không được lưu/gửi. Lỗi còn lại sau một lượt sửa sẽ được hiển thị thay vì
lặp vô hạn. Khi sửa thủ công, dùng **Thẩm định lại bản sửa**, kiểm tra định nghĩa
cuối rồi xác nhận lưu/duyệt. Metadata thay đổi làm mất hiệu lực báo cáo cũ.

Khám phá trả tối đa 5 đề xuất đạt và 5 KPI chưa khả thi, không ép đủ số lượng.
Với schema lớn, AI đọc inventory gọn của tất cả bảng rồi chọn tối đa 5 bảng nghiệp vụ
trong ngân sách context. Các bảng đã chọn giữ nguyên đầy đủ cột, kiểu, khóa, nullable,
giá trị khai báo và quan hệ; không cắt bớt điều kiện để vừa prompt. Phạm vi đã chọn
được ghi trong context báo cáo, không đại diện cho mọi KPI có thể có của toàn database.
Bước chọn phạm vi chỉ chọn bảng, không hỏi người dùng chọn cột giá hay công thức AOV;
Metric Designer Agent tự tạo các biến thể có tiêu chí riêng từ metadata đã nạp.
AOV, biên lợi nhuận và các KPI tỷ lệ có thể dùng `formula.ratio` với hai phép tổng hợp
trên cùng `base_entity`, mỗi phía có `function`, `expression` và `filters` riêng.
`metric.filters` áp dụng cho cả hai phía; `scale=100` biểu diễn phần trăm và mẫu số
bằng 0 trả `NULL`. Không viết phép chia aggregates trong `expression` hoặc chia ID.
Với AOV, `AVG` chỉ tương đương khi metadata xác nhận một dòng mỗi đơn, cột giá
không NULL và cùng tập đơn. Công thức lấy cột từ nhiều bảng gốc vẫn chưa hỗ trợ.

## Tri thức tham khảo

`src/knowledge/retail_metrics.yaml` chứa 10 nhóm KPI và registry URL nguồn.
Các biến thể Shopify/WooCommerce được giữ riêng. Các công thức vận hành nội bộ
được ghi rõ là cần doanh nghiệp xác nhận, không gán cho chuẩn bên ngoài.
Không tìm web runtime, không dùng vector database hoặc đáp án evaluation.
Nguồn tham khảo không ghi đè yêu cầu và quy tắc doanh nghiệp đã xác nhận.
Context mới đọc Knowledge hiện tại; thẩm định lại proposal cũng nạp Knowledge mới
theo yêu cầu gốc và chế độ requested/discovery. Proposal cha và lịch sử cũ giữ nguyên
context, định nghĩa và báo cáo đã lưu; không tự thay đổi kết luận cũ.

Đặt `METRIC_KNOWLEDGE_ENABLED=false` và khởi động lại backend để tạm tắt tri thức
tham khảo. Sinh mới và thẩm định lại vẫn dùng yêu cầu, metadata, kiểm tra kỹ thuật
và Reviewer; không gắn family/variant hoặc nguồn Knowledge. Các điều kiện nghiệp vụ
đã xác nhận và snapshot cũ được giữ nguyên. Metric đã lưu vẫn biên dịch từ definition.
Mặc định là `true`. Công tắc này không tắt HITL, kiểm tra tỷ lệ hoặc guardrails SQL.

Designer/Repair chỉ cung cấp tên bảng/cột và công thức nghiệp vụ. Backend dựng lại
grain, ID và AST từ metadata, đồng thời đối chiếu family/variant với registry.
Một ID biến thể duy nhất có thể được quy về family tương ứng; ID lạ, family mâu
thuẫn hoặc criteria sai vẫn bị từ chối. Phản hồi sửa thiếu/trùng/sai candidate ID
không được áp dụng sang KPI khác.
Schema đầu ra của Designer/Repair không chứa ID hay AST do backend quản lý.
OpenAI dùng JSON mode kèm schema trong prompt để tránh JSON tool-call bị lặp dấu
đóng hoặc hỏng cú pháp; các client khác giữ function calling và fallback hiện có.
Mỗi lời gọi metric giới hạn 4096 output token. Backend vẫn kiểm tra riêng từng
candidate/decision, không chấp nhận cả batch chỉ vì model trả JSON hợp lệ.
Reviewer nhận thêm `filter_scope` do backend dựng từ filters thật. Phạm vi không
có filter được ghi rõ là toàn bộ tập chung, tránh hiểu nhầm là thiếu mẫu số.
Đây là bằng chứng cơ học, không thay thế thẩm định nghiệp vụ hoặc phê duyệt của người dùng.

## API và lưu dấu vết

- Chat/stream và `POST /api/v1/semantic/{db_id}/metrics/generate` nhận
  `proposal_mode: requested | discovery`, mặc định `requested`.
- Suggestion có `proposal_id`, `review`, `definition`, `yaml_preview`;
  response có `blocked_candidates` và `clarification` khi cần hỏi lại.
- `run_status` gồm `completed`, `partial`, `needs_clarification`, `error` và được
  giữ khi replay/reload. Với `partial`, các KPI đạt vẫn có thể gửi duyệt.
- `review.execution_error` phân biệt lỗi đầu ra (`INVALID_AGENT_OUTPUT`), giới hạn
  API (`RATE_LIMITED`), hết quota (`QUOTA_EXHAUSTED`), provider và tài khoản đang bận.
  Đây là lỗi thực thi, không phải kết luận KPI sai nghiệp vụ.
- Tạo metric với `source=ai` phải gửi `proposal_id` cùng định nghĩa đã thẩm định.
  Proposal giả, khác người/database, chưa đạt, bị sửa, đã lưu hoặc lỗi thời bị từ chối.
- `POST /api/v1/semantic/{db_id}/metric-proposals/{proposal_id}/review` nhận
  `{ "definition": ... }`, tạo proposal mới với context gốc và metadata hiện tại.
  Với request Member, Lead gửi `proposal_id` mới khi duyệt bản sửa.
- Bảng `metric_proposals` lưu context, bản gốc/cuối, báo cáo, fingerprint,
  quan hệ proposal cha, request và metric/version được tạo.
- Lịch sử chat giữ báo cáo; màn hình HITL và lịch sử version hiển thị báo cáo
  theo quyền hiện có. Nguồn câu hỏi trong báo cáo version chỉ hiển thị cho Lead.

## Triển khai và kiểm tra

Chạy migration trước khi khởi động backend mới:

```powershell
python -m alembic upgrade head
```

Migration `c02b7c2cd880` chỉ thêm bảng proposal và index, không sửa dữ liệu catalog.
Triển khai frontend cùng phiên bản API mới. Đề xuất AI cũ chưa có proposal phải
được sinh lại; metric đã lưu và luồng nhập metric thủ công giữ nguyên.

Langfuse có node `metric_review`, action `metric_review_decision`, `metric_repair`
và span `metric_review_result`. Span kết quả chỉ ghi status và số lượt sửa trong
`status_message`; prompt/context vẫn tuân thủ cấu hình che nội dung hiện tại.

## Giới hạn gọi model

Mỗi lời gọi metric chỉ có tối đa hai lần gửi provider, tắt retry ngầm SDK. Fallback
sang JSON text chỉ áp dụng khi structured output không được hỗ trợ; JSON sai phải
qua lượt sửa chung của Coordinator, không có vòng retry JSON ẩn.

Rate limit tạm thời được thử lại một lần khi `Retry-After` không quá 10 giây;
thiếu header thì đợi 2 giây. Header yêu cầu đợi lâu hơn sẽ trả lỗi có thời gian
chờ, giữ kết quả đã đạt. Hết quota/xác thực sai không tự thử lại hoặc đổi key/model.
Mỗi credential có một lời gọi metric đang chạy trong một backend worker; chờ
lấy lượt tối đa 10 giây. Chưa có limiter phân tán hoặc job tiếp tục sau restart.

Test tự động dùng mock. Nghiệm thu model thật là bước riêng: tối đa hai KPI đơn
giản (đếm đơn và tổng số lượng), kiểm tra định nghĩa bằng máy cùng báo cáo Reviewer,
không tự lưu catalog/phê duyệt. Thiếu credentials hoặc quota thì ghi chưa đạt,
không xem mock là bằng chứng chất lượng model, theo cách
[Rakazo phân tầng kiểm chứng](https://github.com/elie222/rakazo/blob/6de958f0608248d82f655cf5b88e8eacdf030341/docs/agent-verification.md).
SQL Dump tiếp tục chỉ dùng metadata; compiler/query chỉ chạy metric đã được
người duyệt theo cơ chế cũ.

Test dùng mock LLM và SQLite. Cần đánh giá thêm với model và schema doanh nghiệp
trước khi dùng thực tế: metadata không chứng minh được chất lượng dữ liệu,
và Reviewer cùng model có thể lặp lại sai sót của Generator.

### Metric nhiều bảng và nhiều grain

Metric schema v3 dùng `metric.query_plan` gồm các stage theo thứ tự phụ thuộc. Stage nguồn khai báo `base_entity`, các bảng `joins` đã có relationship an toàn, `group_by`, `aggregates` và `filters`. Stage sau khai báo `source_stage` để tổng hợp tiếp trên output của stage trước. `output_expression` chỉ tham chiếu theo dạng `stage.measure` và phép toán số học; backend tự phân giải cột và khóa từ metadata. Khi có `query_plan`, agent có thể bỏ `formula` hoặc gửi formula aggregate thông thường; backend bỏ qua giá trị đó và chuẩn hóa về `COUNT(*)` để tương thích với metric v2.

Ví dụ tỷ lệ khách có ít nhất hai đơn trên tổng khách mua trong kỳ: stage `per_customer` nhóm theo `customer_id` và đếm đơn; stage `repeat` đếm dòng có `order_count >= 2`; stage `total` đếm mọi khách; output là `repeat.customers / total.customers`. Kỳ phân tích và trạng thái đơn phải được nêu bằng filter đã xác nhận.

Các fact chỉ được ghép sau khi tổng hợp về cùng grain. Compiler chặn đường JOIN mơ hồ, fanout, grain không khớp và runtime filter không có mặt trong mọi nhánh nguồn. Runtime time dimension được áp vào từng stage có cùng column ID. Truy vấn metric plan hiện yêu cầu chọn từng metric riêng; không ghép metric plan với metric khác trong một truy vấn.

## Relationship review and metric publication

Schema Review has separate Tables & columns and Relationships queues. Bulk schema approval approves only table/column metadata. Reading either review queue requires `can_manage_schema`; the shipped organization policy grants this to Data Lead, not Member or Admin. Relationship edits, suggestions and rejection use the same permission. Approval and disable additionally require `can_approve_metrics`. No read-only review permission or new organization role is introduced.

- Imported physical FKs are trusted canonical links (`source=fk`, `approved`); compound FKs remain one link with ordered pairs. Historical trusted links do not invent a human reviewer/time.
- AI suggestions use schema metadata only, are deduplicated against physical links/history, and enter `pending_review`. Manual proposals do too. Neither is available to the compiler. Edit uses table/column IDs; ON is generated by the server, never submitted SQL.
- Managers may edit or reject proposals. Data Lead confirms a proposal only after validation. A many-to-one target must have a complete primary key; one-to-one needs uniqueness on both endpoints. When metadata cannot prove uniqueness, the reviewer must explicitly attest the precise cardinality claim. AI confidence is not uniqueness evidence. Editing resets prior attestation/review.
- An edit to an approved link creates a candidate while its old route continues serving. Preview impact before approve/disable, then submit the matching revision/token with explicit acknowledgment. A stale preview returns 409 and must be refreshed. Approval records reviewer/time and provenance; reject leaves the serving link unchanged.
- Acknowledged approve/disable atomically marks conservatively affected published metrics `needs_review`. Their definitions and SQL are preserved; compilation/execution are blocked until metric review approves again. Reapproval does not restore a disabled relationship: a query needing that route still fails as unreachable. Ambiguous safe paths and unsafe fanout produce compiler diagnostics rather than automatic path selection.
- Sync preserves human-approved/disabled links. Changed FK evidence proposes review without overwriting approved pairs; a missing physical FK makes the canonical link invalid/`needs_review`. A returning FK does not silently reapprove it. Rejected candidates suppress repeated identical proposals. Sync never re-enables a disabled logical link.

The SQLite integration regression `tests/test_integration/test_relationship_review_flow.py` follows import, compound FK visibility, mocked AI suggestion, pending exclusion, edit/attestation, confirmation, metric reapproval, copy-on-write, impact acknowledgment, disable and sync. API RBAC tests separately cover Member/Admin/Data Lead and a manager-capability fixture; the fixture does not add a production role.

Known qualified-identity gap: the current `semantic_tables` uniqueness constraint is still `(db_id, table_name)`, so identical table names in different physical schemas cannot coexist. ID-based relationship payloads and qualified ON previews do not fix import/storage identity. Do not interpret the cross-schema relationship tests as proof of duplicate-name support. The follow-up must migrate that constraint without deleting rows, qualify enrichment/result maps and upserts, and make table-name review/healing lookups explicit or reject ambiguity. It must execute migration preservation tests plus import/repeat-sync/review regressions with truly identical names in two schemas.
