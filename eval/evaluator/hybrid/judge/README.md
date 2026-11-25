# `eval/evaluator/hybrid/judge/` — AI Judge cô lập

LLM chấm điểm kiểu "AI-as-Judge" (rubric có phiên bản, đầu ra có cấu trúc, **không chain-of-thought**). Judge phải dùng **provider, model và key khác** với agent (`JUDGE_*`); không có credential dự phòng, thiếu hoặc trùng thì run dừng trước mọi lời gọi API.

| File | Chức năng chi tiết |
| --- | --- |
| `base.py` | `JudgeLLM` (giao diện), `LangChainJudgeLLM` (cài đặt qua `get_llm(role="judge")`), `JudgeRequest`, `JudgeRunner` (retry có giới hạn), `JudgeEvaluationError`, `TruncatedJudgeOutputError`, `extract_json`. |
| `prompts.py` | `judge_system_prompt`, `judge_user_prompt`: rubric và prompt có phiên bản. |
| `output.py` | `CriterionScore`, `JudgeVerdict` (Pydantic), `weighted_score`. |
| `metrics.py` | `build_judge_metrics`; `AiJudgeMetric` và các metric `BusinessSemanticCorrectness`, `BusinessDefinitionCorrectness`, `FormulaSemanticCorrectness`. |
| `cache.py` | `content_hash`, `judge_cache_key`, `MemoryJudgeCache`, `FileJudgeCache`: cache theo mẫu + nội dung + phiên bản + model để chạy lại không tốn thêm chi phí. |
