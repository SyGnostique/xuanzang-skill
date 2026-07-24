# Learning from independent scores

Independent scores are expensive external evidence. Preserve each result, repair the current package, and extract reusable failure modes without teaching the runtime to game one evaluator.

Run `score_feedback_learning.prompt.md` after every formal score, including a passing score with residual risks. Keep three layers separate:

1. Raw score and current-book repairs stay in a private durable task-audit archive outside the restorable package root.
2. Sanitized generalizable proposals describe the failure mechanism, applicability constraints, non-goals, false-positive risk, and a synthetic regression fixture.
3. Promoted skill changes require one implementation owner, a passing regression test, and evidence that the rule is not a book-specific exception.

For concurrent tasks, never append to one central feedback JSONL. Use unique files keyed by scope, package ID, and attempt. Use a stable proposal fingerprint for deduplication and mark older proposals superseded rather than overwriting them.

The next scorer must remain independent. It may receive a neutral list of changed artifacts and evidence that requires rechecking, but never a prior verdict, desired score, or instruction that a repair should now pass.

Apply the configured scored-content boundary before opening a repair loop. Contributor rosters, acknowledgments, dedications, publication/copyright/cataloging matter, promotional cover copy, repeated title matter, author biographies, duplicate printed Contents, and non-informational index/locator text are outside formal scoring. Do not repair or rescore a book solely because such matter is absent from citation Markdown or chunks.

Suggested proposal fields include `fingerprint`, `source_inbox_files`, `applicability_constraints`, `non_goals`, `implementation_owner`, `regression_fixture_paths`, `status`, and `supersedes`. Suggested inbox fields are defined by the prompt template.

Scoring cannot promote a package or weaken a gate. `PASS_STRICT` still comes only from the active Xuanzang citation gate, and corpus advancement may additionally require the configured independent-score threshold.

Formal score artifacts, raw provider output, and attempt receipts must survive `restore --new-run`. Never place the sole copy below a package root that restoration may replace or reproject. Attempt sequencing must read the durable archive, and each receipt must bind the scored package ID, active run, canonical revision, review revision, export revision, and score-artifact hash.

Pre-score dossiers must distinguish complete review coverage from publish coverage. Structural partitions can cover `used` and `reference_only` paragraphs, while citation chunks normally contain only `used` paragraphs; asset exports contain active `used`/`reference_only` occurrences and omit `excluded` occurrences. Report both inventories explicitly and treat a mismatch only against the artifact-appropriate expected set. For PDF media, independently verify exact-once occurrence coverage and immutable source order across both caption-linked and unlinked figures; never repair an order failure by asserting an unsupported caption relation.
