# 评价与绘图

Python 3.10+。标准输入格式见 `schemas/prediction.schema.json`，指标分母和统计定义见 [protocol.md](protocol.md)。拒答、执行失败和候选答案分别记录；缺失值用 null。

## 评价

从仓库根目录执行：

```powershell
python -m evaluation.validation evaluation/examples/predictions.jsonl
python -m evaluation.report evaluation/examples/predictions.jsonl --output-dir artifacts/selfcheck/example --figures
```

真实运行时用 `--manifest FILE` 核对任务是否齐全。默认比较 B7−B5，以基础题为单位做 2,000 次配对 bootstrap。`--compare A:B` 可重复指定，显式指定会替代默认比较。`--label pilot` 表示开发结果；`frozen-test` 要求提供清单和纯 test 记录。

输出包括分条件指标、差值与 CI、复本诊断、曲线坐标、失败清单和来源哈希。输出目录须新建或为空。没有合法候选/分数时不生成完整 AURC；零作答风险为 null。

### 按原计划验收（2026-11-04）

传入 `--manifest` 后，新增 `manifest_coverage.csv`：每个计划切片显示 planned/provided/ok/failed/missing/extra/trace_mismatch/blocked 数量。整组没有预测的条件也会保留；额外切片没有计划分母，完成率为 null。完整明细在 `manifest_audit.json` 的 `groups` 与 `trace_mismatches`。

- 本表 `completion_rate = ok_n / planned_n`，仅计来源身份匹配且成功的结果。`summary.csv` 的完成率仍以已提供记录为分母；coverage 则以成功记录为分母，三者不可混用。
- 每个计划切片满足 `planned_n = missing_n + ok_n + failed_n + trace_mismatch_n`；provided 包括错配记录，blocked 是计划状态，可与其他计数重叠。
- `manifest_status=complete` 只表示记录齐全、身份匹配且计划无 blocked。已有失败记录时仍可 complete，须另看 failed_n；它不证明全部推理成功、标签已审核或实验已获批准。
- 清单须含全部切片字段及 `run_id/base_question_id/family_id/pair_id/status`，由 scheduler 生成最稳妥。只有 run_id 的文件不再接受。历史完整预测形状的 fixture 清单兼容；它不能替代真实运行前保存的计划。
- 漏跑和额外记录不会再使来源检查跳过：所有共同 run 的模型、版本、数据哈希和条件等字段都会逐项检查。两个评价入口都拒绝 blocked 计划；report 保存诊断并返回 2，metrics 直接返回 2。清单本身格式非法时，在生成报告前报错。

未传 manifest 时该 CSV 只有表头，不能据此判断计划完成。CI 将检查 Python 3.10/3.13、Windows/Linux 的核心回归，并单独检查可选绘图；软件通过不替代真实联调。

## 绘图

绘图依赖：

```powershell
python -m pip install -r requirements-plot.txt
```

单独重画已保存的预测：

```powershell
python -m evaluation.publication evaluation/examples/predictions.jsonl --output-dir artifacts/selfcheck/curves --style journal
```

风险—覆盖率曲线按条件并排显示，另输出实际 coverage/risk。重合阶梯函数共同标注，所有阈值坐标保存在源 CSV；不平滑或移动数据。可选配色为 `journal`、`minimal`、`warm`、`monochrome`，`--all-styles` 一次导出全部配色。

不同图形类型：

```powershell
python -m evaluation.chart_types evaluation/examples/predictions.jsonl --comparisons artifacts/selfcheck/example/comparisons.json --output-dir artifacts/selfcheck/charts --kind all
```

| `--kind` | 图形 |
|---|---|
| `bars` | 分组柱状图 |
| `heatmap` | 数值热力图 |
| `scatter` | 风险—覆盖率散点图 |
| `forest` | 方法差值与 95% 配对置信区间 |

森林图读取已有比较结果，需传 `--comparisons`。`all` 导出四种图形。每种图导出 PDF、SVG、600 dpi PNG 和源 CSV。`--where key=value` 可重复指定，选择可比切片；不会自动池化不同模型、数据版本或实验条件。

一键报告支持 `--figures --figure-style minimal`。旧曲线入口 `evaluation.plot_risk_coverage` 保留 CSV 用法；图片输出的其他条件页列在对应目录的 `figure_index.json` 中。

## 其他入口

- `evaluation.scheduler`：生成逻辑任务清单，不执行模型。支持核心方法、三种消融和可选 H3 面板。
- `evaluation.normalize_input`：通过 `--map TARGET=SOURCE` 转换旧导出；仍需提供完整追溯字段和可信标签。
- `evaluation.bootstrap`：对指定方法和指标单独计算配对区间。

`examples/` 是软件测试数据。正式结果需接入真实预测，并由数据和实验负责人核对标签、候选得分及日志。
