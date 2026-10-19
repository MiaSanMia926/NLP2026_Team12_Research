# Evaluation tools v1.0

C 的评价与统计代码。核心功能只依赖 Python 标准库，要求 Python 3.10+；本次使用 Python 3.12。可选 PNG/SVG 绘图需要 matplotlib，CSV 导出不需要。

## 文件

- validation.py：校验本仓库 schema 的类型/枚举/结构及语义；不是通用 JSON Schema 引擎。
- metrics.py：答案、拒答、完整候选 AURC/部分面积、复本、保留、引用与成本。
- bootstrap.py：基础问题配对 cluster bootstrap，支持普通与复本指标。
- scheduler.py：版本化 manifest，只列任务，不运行模型。
- plot_risk_coverage.py：逐切片 CSV，可选图片。
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
