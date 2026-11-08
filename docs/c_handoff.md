# C 端交付与 10 题联调

更新：2026-11-04。范围：评价软件、调度契约、统计与报告准备。真实模型实验仍待 A/B/D 交接。

## 当前能交付什么

- 三类 schema 与字段/语义校验；短答案 EM/F1、拒答、完整候选 RC/AURC、复本、支持保留、引用和成本指标。
- 基础问题配对 bootstrap；按条件独立主表与 B7−B5 差值/CI；执行失败和不配对 ID 显式输出。
- `python -m evaluation.report` 一键输出主表、CI、曲线坐标、可选 SVG/PNG、失败清单和来源哈希。
- 三种核心消融的逻辑任务；可选 independent/complementary support 面板。缺配置标为 blocked。
- schema 对齐的旧导出转换器；不补造版本、run ID 或人工标签。
- [评价与统计章节草稿](../report/sections/evaluation_statistics.md)、[消融方案](ablations.md)、[复核提交说明](c_review_submission.md)。

软件通过不表示 A 已批准标签、B 已提供合法 score、D 已完成真实运行。当前示例全部是 fixture。

## 队友交给 C 的最小材料

| 交接方 | 所需材料 | C 的验收 |
|---|---|---|
| A | 10 个真实基础题；question 注册表；分离的 public_input 与 gold；应答/答案/来源谱系定义；family 与 split | 先校验两份 JSONL；同 family 不跨 split；gold 不出现在模型可见字段 |
| B | 实际 model/revision/tokenizer、提示哈希、解码参数；B0–B3 runner；候选与 score 语义；输出映射；后续 B5/B7 门控工件 | score 方向为越大越应接受；无 score 留 null；拒答保留独立候选；不把 EM 自动当语义裁决 |
| D | 原始调用日志与可获取索引；每条 manifest 任务的最终状态；全部尝试的 tokens/调用数/延迟；失败/重跑规则 | 每个 run 恰好一条冻结规则选出的最终记录，保留所有原始 attempt；失败显式列出，不能删行 |
| A/D | 可信的 final/candidate correctness；引用条目审核；可靠独立支持组 | 绑定 run_id；unknown 保留 null；来源真值只用于离线评价/oracle |

public_input 只含白名单；condition_id、metadata_state、gold、门控训练信息均属离线控制。runner 可按清单查输入，但不能把清单整行拼进 prompt。白名单校验不能识别证据正文里人工嵌入的答案提示，A/B 还需检查内容。

## 先做软件自检

从仓库根目录执行，输出目录应为全新路径：

```powershell
python -m unittest discover -s tests -v
python -m evaluation.report evaluation/examples/predictions.jsonl --output-dir artifacts/selfcheck/manual-check --label software-selfcheck --figures
```

核心仅需 Python 3.10+ 标准库；`--figures` 需要 matplotlib。未安装时仍保存 CSV 和 unavailable 状态，并返回非零；可以去掉该选项。fixture 主表、CI、曲线不能进入中期或最终研究结果。

## 真实 10 题联调的操作顺序

1. A 按 schema 提供 `data/pilot/questions.jsonl` 与 `data/pilot/public_inputs.jsonl`，单独保管 gold；路径是接口约定，当前尚无这些文件。B/D 确认外部日志存储可访问。
2. C 校验注册表与模型可见输入：

```powershell
python -m evaluation.validation data/pilot/questions.jsonl --kind question
python -m evaluation.validation data/pilot/public_inputs.jsonl --kind public_input
```

3. B 根据实际配置复制并填写 `configs/pilot_manifest.template.json` 为 `configs/pilot.actual.json`。空模型字段有意不通过；不能直接用 examples 假配置。固定预算必须经真实 tokenizer 试跑确定；temperature=0 只是模板值，B 确认后冻结。配置中的 null 权重/阈值不是已完成门控。
4. C 为第一批 B0–B3 生成任务，D 核对预计数量与阻塞。10 题×2 复本×3 metadata×2 长度×4 方法=480 条逻辑任务；先跑更小子集时由 C 另存精确子清单，不把子集输出对全清单验收。

```powershell
python -m evaluation.scheduler --questions data/pilot/questions.jsonl --config configs/pilot.actual.json --methods B0 B1 B2 B3 --output runs/manifests/pilot_b0_b3.jsonl
```

5. B 的 runner 负责调用模型；D 执行并保存原始日志。C 的 scheduler 不提供运行、重试、预算控制或断点续跑。A/B/D 离线合并可信 gold 后生成标准预测；若旧导出只是列名不同，可显式映射转换，仍必须补齐所有来源字段。
6. C 按对应清单一键验收（以下输入/清单必须属于同一批）：

```powershell
python -m evaluation.report results/pilot/scored_predictions.jsonl --manifest runs/manifests/pilot_b0_b3.jsonl --output-dir results/pilot/evaluation_v1 --label pilot --figures
```

B0–B3 阶段没有 B5/B7 时，默认主比较会列 `not_comparable`，这是预期，不能填零。后续 B5/B7 就绪后，用其对应清单和预测重跑到新目录。

7. 检查 manifest_audit、failures、comparisons、curve_audit；A 手算至少一个作答与一个拒答例；D 验证相同保存输出的确定性重算。最后 A/B/D 各自在交接记录中写真实结论。

## 联调验收记录（尚未执行）

| 验收项 | 当前状态 | 实际证据/复核人 |
|---|---|---|
| 真实 10 题与 gold/模型输入分离 | 等 A | 待真实文件与审核 |
| 实际模型访问、版本和合法候选得分 | 等 B | 待 runner/原始响应 |
| 日志、失败、重试与成功记录关联 | 等 B/D | 待运行索引 |
| 输出覆盖精确 manifest，且版本一致 | 等真实输出 | 待 manifest_audit |
| A 手算指标、D 重算核对 | 未执行 | 待人工复核 |
| 真实 pilot 表图交 E | 未生成 | 待上述通过 |

## 自动输出怎么读

- `summary.csv/json`：每个模型、版本、数据哈希、划分、方法配置、长度和条件独立一行；不自动池化。
- `comparisons.csv/json`：A−B，默认 B7−B5；每条件与复本面板分别计算。缺一方基础题不计算差值；执行失败排除整簇并列 ID；零作答 risk 为 null；CI 无定义次数单列。
- `replica.json`：合并 no_replica/same_source_replica 后的真实配对诊断，避免从单条件主表误读 valid_pairs=0。
- `risk_coverage.csv`：完整候选与已作答 partial 曲线分开；`curve_audit.json` 解释缺 score/候选/标签等不可用原因。图片每条件独立，不能混叠无关条件。
- `manifest_audit.json`：缺失/多余/阻塞任务与版本问题。缺失时命令返回非零，保存诊断，不补假预测；没有 manifest 就不能声称原计划全部完成。
- `manifest_coverage.csv`：按原计划分母统计每个切片，包括整组漏跑。完成率为身份匹配的成功数/计划数；与 summary 的成功数/已交记录数、coverage 的作答数/成功数分开。审计 complete 仍可能有执行失败，须同时检查 failed_n。部分交付也检查全部共同 run 的来源错配。
- `provenance.json`、`bundle_hashes.json`：输入、manifest、评价源码、schema 与结果哈希。运行日志仍由 D 提供，此处不替代原始调用来源。
- `--label frozen-test` 只允许 test 且要求 manifest，但不替代团队数据/方法/阈值冻结签收。

## C 本人需要理解并复核

能解释 coverage 和完成率的不同分母、零作答风险为何不是 0、为何完整 AURC 需要拒答行的候选、tie 整组处理、为何按基础题而非变体 bootstrap，以及 CI 跨零/无改善时如何如实报告。AI 辅助代码与章节均需本人理解，不将软件测试记作真实研究结果。

## C 本人现在最值得做的三件事

以下是建议执行的人工工作，未记作已完成贡献。

1. **独立手算一页复核记录。** 不看程序输出，先用 examples 的 B5/B7 各 4 行算 coverage、risk、全题 EM 与候选 AURC，再与 verification 的手算结果比对。另自行删掉整组复本预测、将一条记录改成执行失败，解释为什么计划完成率、已交记录完成率和 coverage 不同；保存自己的推导、误差与修正，不只截图“测试通过”。
2. **拿真实 10 题做首次接口验收。** 按上方 A/B/D 材料表逐项接收；使用运行前冻结的精确 manifest。先看 missing/extra/blocked/trace_mismatches，再看 failed_n、候选 score/标签和原始日志，最后才解读 CI/表图。缺材料时记录具体缺项，不用规则后端结果补位。B0–B3 尚无 B5/B7 时显式选择已有方法，例如 `--compare B3:B0`，并标为探索性检查。
3. **准备自己讲得清的结果解释。** 用一题复本使答案变化的例子解释去重假设；用两方法 CI 跨零或风险无定义的例子说明结论边界。真实结果齐备后再更新评价章节、交 E 的表图及本人实际贡献；不能提前写“显著提高”。

本轮软件新增项是清单验收修复、计划覆盖表、针对性回归测试与 CI 配置；不构成 A 数据、B 模型/门控或 D 真实运行的完成证明。CI 的远端运行结果应以 GitHub Actions 为准。
