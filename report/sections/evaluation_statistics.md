# Evaluation and statistical analysis — draft for integration

Status: protocol-based draft prepared on 2026-10-30. No real-model results are available. The procedures below are proposed or implemented in evaluation software; execution and team approval remain to be verified. Retain future tense until experiments are completed.

## Draft

### Evaluation metrics

We will evaluate answer quality and selective answering separately for evidence-constrained question answering and factual question answering. Answer quality will be measured using exact match (EM) and token F1 against the available reference answers. EM will apply Unicode NFKC normalization, lowercasing, punctuation removal and English article removal. Token F1 will use word tokens for Latin text and character tokens for CJK ideographs, taking the maximum F1 across references. Abstentions will receive zero answer-quality credit. In the controlled evidence-constrained task, examples labelled as requiring abstention will remain in the all-example quality denominator with zero credit. External examples without reference answers will be excluded from EM/F1 and counted explicitly. Correctness labels used for selective risk will be provided separately; string matching will not substitute for evidence-based or semantic adjudication.

Coverage will be defined as the number of answered predictions divided by the number of successfully executed predictions. Selective risk will be the proportion of answered predictions labelled incorrect. Risk will be undefined when no prediction is answered. We will report planned, successful, failed, quality-eligible and answered counts alongside these metrics. Execution failures will not be treated as abstentions. Inappropriate answering and refusal rates will be computed within examples labelled as requiring abstention and permitting an answer, respectively; unknown answerability labels will be excluded from these rates. Citation precision will use reviewed citation entries as its denominator, whereas the proportion of answers with all citations correct will use reviewed answers.

### Risk–coverage analysis

Complete candidate risk–coverage curves will require a candidate answer, its task-appropriate correctness label and a finite acceptance score for every successfully executed example, including examples on which the final decision is abstention. Higher scores must indicate stronger acceptance preference. Candidates will be sorted in descending score order, with tied scores admitted as a whole group. For coverage endpoints c_j and cumulative risks r_j, the area under the risk–coverage curve (AURC) will be computed as the sum of (c_j − c_{j−1})r_j, with c_0=0 and final coverage equal to one. This specifies the endpoint-step convention used by both integration and plotting.

Where complete candidate information is unavailable, complete AURC will be reported as unavailable. A curve constructed only from final answered predictions will be labelled as partial, with its endpoint reported relative to all successful predictions. Partial areas with different endpoints will not be treated as directly comparable. The operating point will be determined using the frozen development-set threshold; ranking test candidates for descriptive curves will not be used to select a test threshold. Models or baselines without a valid acceptance score will be evaluated at their actual operating point.

### Paired comparisons and uncertainty

The prespecified primary comparison is B7 minus B5. We will calculate estimates separately by dataset and version/hash, task, split, model and revision, length policy, metadata state and error subtype, replica condition, and randomization settings. Natural-length and fixed-token-budget settings will be reported separately. We will not pool these conditions by default. The split will be assigned before variants are expanded, and a question family must not span training, development and test partitions.

Uncertainty will be estimated using a paired cluster percentile bootstrap with 2,000 replicates, random seed 20261019 and 95% confidence intervals. The sampling unit will be the base question. Within each analysis panel, all included variants of a sampled question will be carried together, and both methods will use the same sample. Repeatedly selected questions will receive distinct temporary identifiers so that paired replica observations are retained. Missing or duplicated method–condition pairs will be reported as non-comparable. Questions with execution failures will be excluded jointly from the paired analysis, with their identifiers and affected runs recorded. Undefined bootstrap statistics will not be replaced with zero; the number of defined replicates and any interval-instability warning will accompany the interval. These estimates describe the available paired successful subset and do not remove potential bias due to method-specific execution failure.

### Replica and support diagnostics

Replica diagnostics will compare no-replica and same-source-replica conditions for the same base question and method, reporting changes in answer text, normalized answer and answering decision separately. Correctness improvements and deteriorations will be evaluated only for pairs answered in both conditions, so a transition to abstention is not credited as factual improvement. Independent-support retention will be assessed only when reliable source-group labels and retained-group records are available, reporting retained and gold group counts as well as micro- and macro-averaged rates. Unknown source relations will not be assumed independent.

The three core ablations will remove source, unknown and conflict features, respectively. Each variant will require separate training-set fitting and development-set threshold selection before test evaluation. Ablation comparisons will be treated as exploratory and reported as differences with confidence intervals, without automatic significance claims. All tables and figures will retain input and configuration identifiers, evaluation-code and schema hashes, and links to the corresponding execution logs through the supplied run identifiers.

## 中文整合说明

本节说明评价与统计口径，不包含尚未完成的结果，也未声称真实模型验证已通过。E 可按 ACL 正文空间压缩至“指标—曲线—统计”三段；复本诊断、引用分母和完整软件溯源细节可移附录，但执行失败和适用边界不能隐藏。

## Terminology ledger

| Canonical term | Definition | Decision |
|---|---|---|
| coverage | answered / successful predictions | 不与运行完成率混用 |
| selective risk | incorrect / answered predictions | 零作答为 undefined/null |
| AURC | area under the risk–coverage curve | 仅完整候选曲线，partial 另标 |
| base question | cluster resampling unit | 不把条件变体当独立样本 |
| same-source replica | 同源复本条件 | 不与 independent support 混用 |

## Section outline

- Define quality and decision metrics with their denominators.
- Specify score requirements, ties and the AURC convention.
- State the primary comparison, stratification and paired uncertainty procedure.
- Bound interpretation with failure, replica, support and ablation diagnostics.

## Assumptions or missing inputs

- A/C review of task correctness, answerability and language-specific answer normalization.
- B/D confirmation of candidate score semantics, actual model identity, frozen thresholds and complete execution logs.
- Team approval of the analysis plan before viewing the formal test set; actual dataset sizes, costs and results remain absent.
- B confirmation of the exact feature columns removed by each ablation, separate gate artifacts, and train/dev provenance.
- E/A addition of verified methodological references from the project's bibliography; no references are invented here.

## Claim-evidence map

| Claim | Evidence | Status |
|---|---|---|
| Evaluation software separates abstention, failure and candidate ranking | evaluation/metrics.py, evaluation/validation.py; software tests | supported for fixtures; human label review pending |
| Base-question paired bootstrap preserves repeated clusters | evaluation/bootstrap.py; duplicate-draw and pairing tests | supported for software behavior |
| One-command tables and curves preserve traceability | evaluation/report.py; sliced-report integration tests | supported for software behavior |
| The proposed method improves reliability | No real-model output | needs evidence; no result sentence drafted |

## Why this structure

- Denominators precede uncertainty so the estimated quantities are explicit.
- Complete and partial curves are separated before any method comparison.
- Missingness and execution failure qualify the inference at the point where it is introduced.

To redirect this draft, identify the paragraph or definition to change; unaffected definitions should remain aligned with evaluation/protocol.md and the code.
