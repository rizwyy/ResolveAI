# Evaluation dataset and modes

`cases.jsonl` starts the versioned safety dataset. Before claiming model quality, extend it to 60 cases (10 each across success, clarification, abstention, approval, escalation, isolation/adversarial failure) and run two modes:

1. **Deterministic regression:** scripted provider/tool output; asserts database side effects and authorization. This measures orchestration, not model intelligence.
2. **Live Bedrock:** explicit model, region, prompt/policy versions, time, token/cost cap, and raw outcomes. It must report tool selection, argument validity, completion, clarification/escalation, unauthorized action rate, grounding, and latency by category.

No quality score is present because no live model evaluation was run.
