# C 端评审提交说明

2026-10-31 上传范围：在远端 evaluation-metrics 现有评价实现上追加 C 的源码、测试、配置模板、交接/消融说明和评价章节；不包含自检输出、图片、缓存、临时文件或整个小组的本地规划材料。以下“本轮未提交”等表述记录 10/30 准备阶段，本次上传授权来自 10/31 用户指令。

建议标题：Complete evaluation reporting, ablation manifests and C handoff

## 目的与行为

把现有评价工具连成可追溯汇总流程，减少拿到真实预测后手工切片、拼 CI 和查缺失的工作。修复旧 normalizer 与现行 schema 的不一致；按数据哈希和位置种子加强隔离；添加三消融与 H3 逻辑任务；明确软件自检和真实研究结果的边界。

## 本次工作文件

- `evaluation/report.py`、`evaluation/metrics.py`、`evaluation/bootstrap.py`、`evaluation/scheduler.py`、`evaluation/normalize_input.py`。
- `tests/test_reporting.py`；原 `tests/test_evaluation.py` 同时回归。
- `configs/pilot_manifest.template.json`、`docs/c_handoff.md`、`docs/ablations.md`、`report/sections/evaluation_statistics.md`。
- 同步 `README.md`、`evaluation/README.md`、`evaluation/protocol.md`、`evaluation/verification.md`、`docs/implementation_status.md`、`docs/milestones.md`、`docs/analysis_plan.md`、`docs/decisions.md`、`docs/tool_usage.md`、`CONTRIBUTIONS.md`。
- `.gitignore` 隔离软件自检产物；根目录实验协议第 11 节补充历史状态说明。

10/30 本地准备时，evaluation/、schemas/、tests/ 为未跟踪文件。10/31 已核对远端 evaluation-metrics 分支包含其上一版基础实现及 fixtures，本次以远端提交为父提交，仅更新变更文件并保留其依赖；不把先前所有未跟踪文件都归为本轮新增工作。

本轮未代填成员姓名/账号，未设置 Git 身份、暂存、提交、推送或给队友发消息。所有修改保持本地可审状态，避免把来源混杂的整个工作区一起提交。

本次仅上传 C 范围的代码与说明；上方列出的 docs/implementation_status.md、milestones.md、decisions.md 和根目录实验规划属于本地协作资料，不在本次源码上传范围。它们的本地状态更新保留。贡献记录与 AI 工具使用说明随 C 交付纳入。

## 验证

从根目录执行 `python -m unittest discover -s tests -v`。新增检查覆盖手算条件差值、完整/缺失配对、复本面板、数据哈希与位置隔离、manifest 错配、输入转换空值与跨行泄漏、消融缺工件阻塞、清单身份变化、汇总输出与来源追溯。

最终软件图表自检包见 `artifacts/selfcheck/c_delivery_20261030_final/`，不得作为模型实验结果。最终执行记录见 `evaluation/verification.md`。

## 建议交叉评审

| 复核方 | 核查内容 | 当前状态 |
|---|---|---|
| A | 标签含义、EM/F1 可接受范围、应答率分母、H3 真值 | 待人工复核 |
| B | score 方向、拒答候选保存、三种开关与工件/阈值对应 | 待真实接口 |
| D | 精确 manifest 覆盖、全部 attempts 成本、失败处理与重算 | 待实际运行 |
| E | 评价章节的计划语态、无结果主张、贡献与 AI 使用说明 | 待整合 |

## 重跑影响

数据/划分哈希现在参与分组和 manifest 追溯检查；旧输出若混用同版本名下的不同哈希，将被拆分或拒绝。现有核心 schema 未变更。scheduler 输出新增 method_config；加入消融配置会影响 config/run/pair hash，旧清单与新清单不能混接。normalizer 现强制完整 schema，旧的简略六列导出必须先由负责人补齐真实来源字段。

没有真实模型结果需要重跑；若队友在此本地文件夹外已有结果，需依据新契约重新核对后重算。
