# Evaluation tools v1.0

C 的评价与统计代码。核心功能只依赖 Python 标准库，要求 Python 3.10+；首次核验使用 Python 3.12，2026-10-30 本轮使用 Python 3.13.9。可选 PNG/SVG 绘图需要 matplotlib，CSV 导出不需要。

## 文件

- validation.py：校验本仓库 schema 的类型/枚举/结构及语义；不是通用 JSON Schema 引擎。
- metrics.py：答案、拒答、完整候选 AURC/部分面积、复本、保留、引用与成本。
- bootstrap.py：基础问题配对 cluster bootstrap，支持普通与复本指标。
- scheduler.py：版本化 manifest，只列任务，不运行模型。
- plot_risk_coverage.py：逐切片 CSV，可选图片。
- report.py：一键主表、配对 CI、复本诊断、曲线、失败/缺失清单和来源哈希。
- normalize_input.py：旧导出的显式字段映射，按完整 schema 验收并保留合法 null。
- [评价协议](protocol.md)、[核验记录](verification.md)、[分析定义](../docs/analysis_plan.md)。
- schemas 目录为正式数据契约；examples 为虚构软件样例。

## 可直接运行的自检

在仓库根目录执行：

~~~powershell
python -m unittest discover -s tests -v
python -m evaluation.validation evaluation/examples/predictions.jsonl
python -m evaluation.validation evaluation/examples/questions.jsonl --kind question
python -m evaluation.validation evaluation/examples/public_inputs.jsonl --kind public_input
python -m evaluation.metrics evaluation/examples/predictions.jsonl --output artifacts/selfcheck/metrics.json
python -m evaluation.bootstrap evaluation/examples/predictions.jsonl --method-a B7 --method-b B5 --replicates 2000 --output artifacts/selfcheck/bootstrap.json
python -m evaluation.plot_risk_coverage evaluation/examples/predictions.jsonl --output artifacts/selfcheck/risk_coverage.csv
python -m evaluation.scheduler --questions evaluation/examples/questions.jsonl --config evaluation/examples/manifest_config.json --output artifacts/selfcheck/manifest.jsonl
~~~

以上输出只能称软件自检。假模型标识、预算与标签不代表真实配置或模型结果，自检产物不作为课程实验结果提交。

装有 matplotlib 时可将图输出扩展名改为 png 或 svg；缺库时保留 CSV 并显式报未生成图片，不假报成功。

## 接真实输出

1. A 按 question 注册表和 public_input 白名单提供数据；gold 独立管理。
2. B/D 保存原始响应、作答决定、候选及 score。拒答的 prediction/correct 为 null，候选单独保留。
3. 离线合并可信答案和人工正确性标签为 prediction.schema.json 对应标准表；工具不猜语义正确性。
4. C 先校验，再按模型、任务、划分、长度与条件切片。一个 run_id 只留冻结规则选定记录，原始重试不删除。
5. 正式主比较过滤到可比切片，例如 --where split=test --where metadata_state=missing --where replica_condition=no_replica；真实配对可评分输出才能解释 CI。
6. 版本/评价变化需注明受影响结果并重算。

当前不提供任意列名猜测或 Excel/PDF 自动转标签；来源、引用支持与 score 含义需负责成员确认。

检查真实预测完整性时，metrics 可加 --manifest 对应任务清单；缺失/多余 run ID 或版本错配会报错。未传 manifest 时 planned_n 仅代表提供的记录数，不能证明原计划全部运行。

## 一键汇总（2026-10-30）

~~~powershell
python -m evaluation.report evaluation/examples/predictions.jsonl --output-dir artifacts/selfcheck/my-check --label software-selfcheck --figures
~~~

输出目录须全新或为空，防止旧结果混入。默认逐条件比较 B7−B5，并另做复本变化诊断；2,000 次基础题配对 bootstrap。`--compare A:B` 可重复指定，显式指定会替代默认比较。输出 summary.csv/json、comparisons.csv/json、replica.json、risk_coverage.csv、curve_audit.json、manifest_audit.json、failures.json、provenance.json 和 bundle_hashes.json。`--figures` 为每个可比条件生成独立 SVG/PNG；默认只需标准库。

真实输出加 `--manifest ... --label pilot`；正式 test 用 `--label frozen-test` 且必须提供 manifest 和纯 test 记录。标签不代替团队冻结签收。清单有缺失/多余/错配/blocked 时保存诊断并返回非零；不会补假预测。缺少方法或条件时比较显式标 not_comparable；全拒答 risk/部分统计可为 null。软件样例永不作为研究结果。

### 消融与 H3

scheduler 新增 `--include-ablations` 和 `--replica-conditions`；三种方法 ID 为 B7_no_source、B7_no_unknown、B7_no_conflict。method_configs 不齐时标 blocked。详见 [消融契约](../docs/ablations.md) 与 [C 交接说明](../docs/c_handoff.md)。这里只生成逻辑任务，不会生成 H3 数据、训练或运行模型。

### 旧导出转换

~~~powershell
python -m evaluation.normalize_input old_export.jsonl --map prediction=response --output artifacts/imported/canonical.jsonl
~~~

未改名字段原样保留；版本、run/pair ID、hash、候选标签等必须由上游提供。默认不推断应答或正确性；可选推断不能代替审核。空参考、未知 should_answer、拒答和执行失败按现行 schema 验收；缺字段、重复 ID、跨 split family 或不兼容 pair 均拒绝，不发布部分成功文件。CSV 空单元格不自动补成 null；含 null 的完整表建议用 JSONL。
