# `frontend/src/i18n/` — Từ điển dịch

| File | Chức năng chi tiết |
| --- | --- |
| `catalog.json` | Ánh xạ **chuỗi gốc tiếng Việt → `{ "vi": ..., "en": ... }`**. Khóa chính là câu tiếng Việt (ví dụ "Phân loại yêu cầu" → "Classify the request"). Dùng cho nhãn UI và tên bước trong luồng agent. |

Cách dùng: component `Translated` (`components/ui/translated.tsx`) và `LanguageContext` tra khóa trong catalog theo ngôn ngữ hiện tại; nếu thiếu khóa thì hiển thị nguyên văn tiếng Việt. Thêm chuỗi mới: thêm một mục vào `catalog.json` với đủ hai ngôn ngữ.
