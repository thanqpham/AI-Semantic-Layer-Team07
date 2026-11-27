# `docs/guide/` — Bộ hướng dẫn

Hướng dẫn cho người phát triển và trợ lý AI. Mỗi thư mục con có `_index.md` liệt kê trang.

## Hướng dẫn gắn với tính năng của dự án

| File | Nội dung |
| --- | --- |
| `langfuse.md` | Cấu hình và thiết kế tracing agent bằng Langfuse. |
| `metric-workflow.md` | Quy trình sinh metric (designer → validate → reviewer → repair). |
| `metric-review.md` | Thẩm định metric AI trước khi tới HITL. |
| `retail-metric-benchmarks.md` | Benchmark metric bán lẻ từ seed hiện tại. |
| `semantic-compiler-compatibility.md` | Tương thích của semantic compiler giữa các dialect. |
| `troubleshooting.md` | Sửa lỗi thường gặp. |

## Hướng dẫn theo chủ đề (thư mục con)

| Thư mục | Nội dung |
| --- | --- |
| `langgraph/` | `nodes-and-edges.md`, `state.md`, `tools.md` — viết node/edge, `AgentState`, tool. |
| `code-style/` | `python.md`, `frontend.md` — quy ước code. |
| `testing/` | `writing-tests.md` — cấu trúc test. |
| `architecture/` | `system-design.md` — kiến trúc hệ thống (bản hướng dẫn). |
| `anti-patterns/` | `cohort-1-mistakes.md` — các lỗi thường gặp cần tránh. |
| `devops/` | `docker-cicd.md` — Docker và CI/CD. |
| `setup/` | `quick-start.md` — bắt đầu nhanh. |
| `deliverables/` | `checklist.md` — 10 deliverable của khóa học. |
| `patterns/` | `rag-pattern.md`. |
| `bmad/` | `overview.md` — phương pháp BMAD. |
| `resources/` | Khóa học đề xuất, phân tích các đội tham chiếu. |
| `book-media/` | Hình ảnh minh họa cho sách hướng dẫn. |

## Chương hướng dẫn của khóa học

`chapter-01.md` … `chapter-10.md` (mục tiêu, clone template, kiến trúc 3 tầng, LangGraph, FastAPI, giao diện, Docker, test, deliverables, lộ trình 6 tuần), cùng `cost-management.md` (quản lý chi phí API) và `free-accounts.md` (tài khoản miễn phí).
