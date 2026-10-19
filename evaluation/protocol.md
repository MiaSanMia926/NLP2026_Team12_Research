# 评价协议 v1.0

这是 C 的评价代码接口说明与可执行口径，不是项目时间规划，也不包含真实模型结果。当前已完成软件自检；标签含义需 A 复核，候选得分与日志字段需 B/D 对接。未冒记其他成员签收。

## 输入边界

- 统计单位为 base_question_id，同题复本、来源元数据和位置变体不作独立样本。
- 模型输入使用 public_input.schema.json 白名单，只含问题、证据与可见来源字段。不允许 references、should_answer、gold 来源组或 metadata_state 等操控真值进入模型。
- question.schema.json 是 A/C/D 的题目注册表，不是模型输入。同一 family 不得跨 train/dev/test。
- prediction.schema.json 是离线合并可信标签后的标准表。校验器不会推断语义正确性。
- correct 是最终已作答输出在当前任务下的正确性；拒答时 prediction 和 correct 均为 null。候选答案、候选正确性及 score 另存，拒答时仍可保留。
- 证据约束任务使用 candidate_task_correct；事实外检使用 candidate_factual_correct。任务、事实真假、证据充分性、should_answer 和来源关系分开。
- 来源真值仅评价/oracle 可见。B6 只能额外读 gold lineage，不能看答案。unknown 不默认算独立来源。
- 数值须有限；缺失为 null。API/解析失败显式列出，不能伪装拒答。

## 指标及分母

| 指标 | 实现口径 | 边界 |
|---|---|---|
| EM / token F1 | NFKC、小写、去标点/英文冠词的 EM；英文词/CJK 字符 F1 | 拒答为 0；受控 should_answer=false 且 references=[] 也以 0 纳入全题分母；外部缺参考单列排除数 |
| Coverage | 作答数 / 成功预测数 | 另报计划、失败与完成率，不把失败当拒答 |
| Selective risk | 错误作答数 / 作答数 | 零作答为 null；事实外检按事实正确性单列 |
| 不当作答率 | should_answer=false 中作答数 / 该类成功预测数 | 未知标签不计；分母零为 null |
| 不当拒答率 | should_answer=true 中拒答数 / 该类成功预测数 | 同上 |
| 完整 AURC | 所有成功预测的候选按 score 降序，同分成组；组末风险乘覆盖增量 | 每题须有候选、相应正确性、有限 score；终点 1，否则不可用 |
| partial_aurc_answered | 仅最终已作答行排序，覆盖分母仍为所有成功预测 | 单列终点，不与完整面积混比；不同终点只在共同区间比较 |
| 复本变化 | 配对前后原文答案、规范化答案、作答决定分别变化 | 无效配对数显式输出；pair_id 只排除重复条件 |
| 正确性改善/退化 | 两边都作答时错误→正确 / 正确→错误比例 | 分母为 both_answered_pairs，拒答转换不奖励为事实改善 |
| 独立支持保留 | 保留 gold 独立支持组 / gold 支持组 | 仅可靠、非空 gold；给 micro/macro 与分子分母 |
| 证据支持率 | 人工审核的已作答输出中受证据支持的比例 | 给审核数量，不由 EM 推断 |
| 引用 precision | citation_labels 中正确引用条目 / 审核引用条目 | 与 citation_correct 所指“全部引用正确的回答比例”分开 |
| 成本 | 输入/输出 tokens、调用数、延迟和非空记录数 | 包括失败尝试、额外特征调用与重试；由 B/D 汇总 |

EM/F1 是短答案基线 evaluator；专用答案规范在看 test 前由 A/C 固定。自报置信度和 score 不等于校准概率。

## 曲线与阈值

完整曲线按相同 score 整组加入，面积为 sum((c_j-c_prev)*risk_j)。绘图与积分采用相同右端点阶梯。B0–B3 无合法 score 时填 null，只报实际 operating point，不借用 B7 得分。

dev 冻结阈值决定实际 operating point；test 排序曲线是描述性诊断，不表示每个点已校准。不得在 test 选 tau。相同 coverage 比较保留完整 tie 组，没有共同可达点就报告可达点表，不拆 tie。partial_area 支持共同区间描述性积分，必须报告端点。

## 分组与统计

默认按数据/version、任务、split、模型/revision、长度、seed、experiment_id、方法/config_hash、条件、metadata 状态/错误子类、位置种子多键分组，不产生池化主结果。

预定主比较 B7−B5。按基础问题 paired cluster bootstrap：2,000 次、seed=20261019、95% percentile CI。同题所有条件随抽样，两方法共用抽样；重复抽中时重命名临时 base/pair ID。

双方条件矩阵不齐或重复直接报错。执行失败导致排除时列出基础题 ID，不挑有利成功子集。无定义 replicate 不填零，报告有效数；无定义超过 5% 附区间不稳定提示。正式主表按条件切片，跨条件汇总须另作预声明。

## 调度与待接入材料

scheduler 只列逻辑任务，不调用模型、不拟合门控、不产生实验结果。默认七方法 B0/B1/B2/B3/B4/B5/B7；B6 显式启用并标 oracle。

主轴 2 重复×3 metadata×2 长度。缺 fixed token 预算或错误 metadata split/merge recipe 时标 blocked。ID 覆盖数据/划分、方法配置、模型、提示模板、解码与种子；B 的 runner 仍须记录实际输入/prompt 哈希、token、缓存与日志。

A 需提供题目、划分与可信标签；B 提供候选/得分、门控权重及阈值；D 提供原始调用和人工引用审查。examples 仅作软件核验，不能写入论文实验结果。

真实汇总须覆盖所选 manifest 的全部 run：失败和未完成不得无声省略。metrics 的 --manifest 可核对 ID 和版本；不提供 manifest 时，planned_n 只表示当前输入记录数。
