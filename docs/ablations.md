# 核心消融与 H3 调度契约

版本：2026-10-30，C 端拟议契约；B 的开关实现、A 的条件数据、团队科学签收均待完成。

| 方法 ID | 改动 | 训练/校准 | 预定比较 |
|---|---|---|---|
| B7 | 完整来源/unknown/冲突特征 | train 拟合、dev 选阈值 | B7−B5，预定主比较 |
| B7_no_source | disabled_features=[source]；去来源依赖特征，具体列由 B 列出 | 独立拟合、独立 dev 校准 | B7_no_source−B7，探索性 |
| B7_no_unknown | disabled_features=[unknown]；去 unknown 指示及其交互，具体列由 B 列出 | 同上 | B7_no_unknown−B7，探索性 |
| B7_no_conflict | disabled_features=[conflict]；去冲突特征，具体列由 B 列出 | 同上 | B7_no_conflict−B7，探索性 |

本表落实统一实验协议的三种核心消融。原分工里的“仅精确/仅语义去重”暂由 B2/B3 等对应基线提供对照，具体对应须 B 签收；不未经确认新加主实验或替代核心消融。去特征是否仍可用在上游来源聚合/聚类，必须 B 明确，否则不能解释为移除了整个来源机制。

## 清单生成

`configs/pilot_manifest.template.json` 为待填写模板。method_configs 给每个消融传 disabled_features 和 gate 的 fit_split=train、calibration_split=dev、artifact_hash、threshold。三个开关名称是 C/B 接口约定，尚无 B 的执行实现。

```powershell
python -m evaluation.scheduler --questions data/pilot/questions.jsonl --config configs/pilot.actual.json --include-ablations --output runs/manifests/pilot_with_ablations.jsonl
```

默认七核心方法；启用三种消融后共十方法。N 题×2 复本×3 metadata×2 长度×10=120N 逻辑任务。B6 需另加 --include-oracle；不能将 oracle 当部署方法。

缺少开关、独立 train/dev 声明、有效权重 SHA256 或有限阈值时，相关任务标 blocked；不同变体复用同一权重哈希也会阻塞。生成器检查配置声明，不能证明模型真的重新训练或阈值来自 dev；B/D 仍需提交工件、训练数据来源、dev 选择记录与实际校验。配置 hash 覆盖 method_configs，变更会改变 run/pair ID，不可混合旧输出。

## H3 面板

```powershell
python -m evaluation.scheduler --questions data/pilot/questions.jsonl --config configs/pilot.actual.json --methods B5 B7 --replica-conditions independent_support complementary_support --output runs/manifests/pilot_h3.jsonl
```

此命令只生成逻辑任务。A 必须提供对应证据变体及可靠 gold 独立支持组；不能把 no_replica 数据改名当 H3。B/D 记录保留来源组，A/D 审核谱系。评价输出 micro/macro retention 及 eligible_rows/gold_groups，不从答案正确率猜保留率。复本变化指标只用 no_replica/same_source_replica，H3 不混入。

## 统计与冻结

自然长度与固定完整 prompt token 预算分开；metadata 错误拆分/合并分开。所有权重、特征、阈值、分组、排除规则均在看 test 前冻结。采用基础题配对 percentile bootstrap（2,000 次，seed=20261019），每个比较同时报告 coverage/risk/EM/AURC，不只挑风险下降。

```powershell
python -m evaluation.report results/pilot/scored_predictions.jsonl --manifest runs/manifests/pilot_with_ablations.jsonl --output-dir results/pilot/ablation_eval_v1 --label pilot --compare B7:B5 --compare B7_no_source:B7 --compare B7_no_unknown:B7 --compare B7_no_conflict:B7
```

--compare 显式提供后替代默认比较，因此同时保留 B7:B5。多消融只报告差值与 CI；没有预声明多重检验族时不写“显著”。失败、不配对、无定义 replicate 与负结果均保留。预算、主模型和数据量的最终选择属于全组，不由模板代作决定。
