# Evaluation Report

- Run: `hybrid-ecommerce` (smoke) — status **PASS**
- Overall score: 99.740 / 100 (valid=True, coverage=100%)

## Suite scores

| Suite | Weight | Score | Minimum | Samples | Errors |
|---|---:|---:|---:|---:|---:|
| discovery | 15% | 1.000 | 0.95 | 4 | 0 |
| enrichment | 20% | 0.987 | 0.85 | 4 | 0 |
| metric_generation | 25% | 1.000 | 0.85 | 12 | 0 |
| query_compilation | 25% | 1.000 | 0.90 | 32 | 0 |
| guardrail | 15% | 1.000 | 0.95 | 13 | 0 |

## Metric scores

| Metric | Mean score |
|---|---:|
| allowed_dimension_f1 | 1.000 |
| business_definition_correctness | n/a |
| business_name_similarity | 1.000 |
| business_semantic_correctness | n/a |
| column_f1 | 1.000 |
| dimension_f1 | 1.000 |
| entity_f1 | 1.000 |
| error_code_accuracy | 1.000 |
| filter_accuracy | 1.000 |
| formula_equivalence | 1.000 |
| formula_semantic_correctness | n/a |
| invalid_selection_rejection | 1.000 |
| limit_enforcement | 1.000 |
| metric_identity_accuracy | 1.000 |
| primary_key_accuracy | 1.000 |
| relationship_accuracy | 0.909 |
| relationship_f1 | 1.000 |
| request_validation_accuracy | 1.000 |
| result_schema_accuracy | 1.000 |
| selection_preservation_accuracy | 1.000 |
| sql_ast_equivalence | 1.000 |
| sql_execution_accuracy | 1.000 |
| sql_expression_equivalence | 1.000 |
| table_f1 | 1.000 |
| table_precision | 1.000 |
| table_recall | 1.000 |
| timeout_enforcement | 1.000 |
| unsafe_sql_rejection | 1.000 |
| valid_select_acceptance | 1.000 |

## Quality gates

| Gate | Passed | Detail |
|---|---|---|
| security_negative_guardrails | ✅ | negative guardrail decisions correct |
| compiler_execution_accuracy | ✅ | sql_execution_accuracy=1.0 |
| zero_metric_errors | ✅ | metric errors=0 |
| required_negatives_evaluated | ✅ | missing candidates=0 |
| dataset_approved | ✅ | dataset_review_status=pending |
| release_evidence | ✅ | candidate_source=golden_derived, profile=pipeline |

## Failed results

- `ecommerce_discovery_001` / `relationship_accuracy`: failed — 
- `ecommerce_discovery_002` / `relationship_accuracy`: failed — 
- `ecommerce_discovery_003` / `relationship_accuracy`: failed — 
- `ecommerce_discovery_004` / `relationship_accuracy`: failed — 
