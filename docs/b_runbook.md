# B 组实验环境与交接

运行入口为 `python -m baselines.runner`。C 生成实验清单，A 提供模型可见输入和变体索引，D 执行并保存日志。标准答案和审核标签在推理之后离线合并。

## 1. 安装和冻结配置

建议 Python 3.10 以上。Transformers 支持本地 CPU 检查点。Apple Silicon 上使用 MLX 权重时，将 backend 改为 `mlx_vlm`，并在可访问 Metal 的环境里另装 `mlx-vlm`。使用 OpenAI 兼容服务时，将 backend 改为 `openai_compatible`，配置 `base_url`（含 API 版本路径）、服务端模型名、实际 revision、tokenizer ID 和持有密钥的环境变量名 `api_key_env`。API 的 seed 若被支持，可以放在 generation 中，和顶层 seed 保持一致。模型版本由服务公开信息与原始响应复核。可选 `api_usd_per_million_tokens` 对象使用 `input`、`output` 两个费率，金额是估算值。

```sh
python -m pip install -r requirements-baselines.txt
python -m unittest discover -s tests -q
cp configs/baselines.template.json configs/baselines.actual.json
```

编辑 `configs/baselines.actual.json` 中的 `experiment_id`、`model`、本地 `checkpoint`、实际输出 token 上限，以及 embedding 配置。B3/B5 使用同一固定版本的句向量模型和同一阈值。位置顺序采用 A 的输入顺序，C 在生成清单时记录 A 使用的 position seed。先测试自然长度，固定长度条件启用前用本地 tokenizer 试定预算。

```sh
python -m baselines.config --template configs/baselines.actual.json \
  --output runs/config/baselines.json
```

生成的配置记录 checkpoint、tokenizer 文件指纹、实际依赖版本、解码参数和提示模板指纹。对本地模型，`--checkpoint` 可覆盖模板路径。保存模型权重出处和 revision；配置里的本地 revision 是目录内容指纹。

## 2. 运行 B0–B3 pilot

向 A 获取 `questions.jsonl`、`public_inputs.jsonl`、离线 `gold.jsonl` 和 `input_index.jsonl`。索引每行用 `base_question_id`、`replica_condition`、`metadata_state`、`metadata_error_type`、`length_policy` 映射 `input_id`，也支持对当批清单的 `run_id → input_id` 映射。建议自然长度与固定预算对应同一证据内容，后者由 runner 自动补齐。gold 使用 `input_id`、`should_answer`、`references`，可靠来源审查另加 `gold_independent_support_groups` 和 `evidence_truth`（证据 ID 映射到含 `gold_group` 的对象）。

```sh
python -m evaluation.scheduler --questions data/pilot/questions.jsonl \
  --config runs/config/baselines.json --methods B0 B1 B2 B3 \
  --output runs/manifests/pilot_plan.jsonl

python -m baselines.plan --manifest runs/manifests/pilot_plan.jsonl \
  --public data/pilot/public_inputs.jsonl --input-index data/pilot/input_index.jsonl \
  --questions QUESTION_ID_1 QUESTION_ID_2 --metadata complete --lengths natural_length \
  --output runs/manifests/pilot_small.jsonl

python -m baselines.runner --manifest runs/manifests/pilot_small.jsonl \
  --public data/pilot/public_inputs.jsonl --config runs/config/baselines.json \
  --output runs/raw/pilot_small
```

把示例问题 ID 换成 A 提供的开发题。小批通过后，由 C 用已审的十题注册表生成完整清单，并按相同流程绑定全部变体。固定预算要求本地后端可以在调用前核算完整 chat prompt。校验实际输入 token 数和预算一致，过长或无法精确补齐会记作 `blocked_budget`。补齐只添加模型被要求忽略的中性标记，同时记录实际长度。

`attempts.jsonl` 保存每次尝试、完整提示、输出、状态、调用数、token、时延和可用的提供方响应。`predictions.jsonl` 一条任务一行。相同参数重跑使用 SQLite 日志恢复，只处理未成功且还有尝试额度的任务。中断发生在调用期间的记录保留为用量未知。日志以第一次成功为最终结果，耗尽重试则保留最后失败。缺失用量以 null 表示，同时输出已知 token 小计。语义编码的处理耗时及处理段落数分别记录。

## 3. 离线审核与 C 验收

A/D 按 `run_id` 提供每个成功输出的审核记录，含 `label_origin`。候选存在时，受控问答给布尔值 `candidate_task_correct`，事实问答给 `candidate_factual_correct`。可附 `answer_supported`、`citation_correct` 和与引用等长同序的 `citation_labels`。拒答时仍可审核候选。保留 D 的原始日志和运行配置用于复盘。

```sh
python -m baselines.review --predictions runs/raw/pilot_small/predictions.jsonl \
  --manifest runs/manifests/pilot_small.jsonl --gold data/pilot/gold.jsonl \
  --reviews data/pilot/pilot_small_reviews.jsonl --output results/pilot/scored_small.jsonl

python -m evaluation.report results/pilot/scored_small.jsonl \
  --manifest runs/manifests/pilot_small.jsonl --output-dir results/pilot/audit_small \
  --label pilot --compare B3:B0
```

先看 `manifest_audit.json` 中的漏跑、多跑、阻塞和身份差异，再检查 `failed_n`。十道基础题全量设计对应 480 个 B0–B3 逻辑任务。子清单单独留档和验收。

## 4. 方法、门控和消融

| 编号 | 实现 |
|---|---|
| B0 | 原始证据直接作答 |
| B1 | 原始证据，使用提示词决定是否拒答 |
| B2 | 文本 NFKC、casefold、空白归一化去重，再使用 B1 提示 |
| B3 | 按输入顺序用归一化句向量和余弦阈值做贪心语义去重，再使用 B1 提示 |
| B4 | 原始证据，基于模型报告的候选置信度、证据充分性进行门控 |
| B5 | B3 语义去重，结合 B4 门控 |
| B6 | B7 类门控，单独使用真实来源组作为 oracle |
| B7 | 可见来源内去除同文本复本，保留同源互补段及不同来源的相似段。根据模型的支持和反对段落判断，统计已知支持组数、unknown 比例和是否出现 unknown 支持，以及冲突指示，再与 B4 特征一起门控 |

B7 将 `source_id` 和 `reprint_of` 连接成来源组。来源未知的段落不能增加已知独立支持数。B7_no_source 使用 B2 式全局精确去重，去掉来源组统计，保留元数据是否可见的 unknown 特征。B7_no_unknown 保留聚合，关闭两项 unknown 特征。B7_no_conflict 关闭冲突特征，证据仍保留给模型。B0–B3 的分数为 null。B4–B7 输出独立候选及门控得分，分数越高越倾向作答。B6 必须使用独立清单（scheduler 加 `--methods B6 --include-oracle`），runner 加 `--oracle-lineage`，谱系文件每行仅有 `input_id` 和 `evidence_groups`（证据 ID 到真实来源组）。

先用 scheduler 的 `--collect-gate-features --methods B4 B5 B7 B7_no_source B7_no_unknown B7_no_conflict` 生成数据清单，使用 `baselines.plan --splits train dev` 精确绑定，再在 runner 加 `--collect-gate-features` 保存待审核候选与特征。A/D 审核后对每种方法独立执行下列命令。

```sh
python -m baselines.gates --method B7 --predictions runs/raw/gate_features/predictions.jsonl \
  --reviews data/pilot/gate_reviews.jsonl --config runs/config/baselines.json --artifacts runs/gates
```

只在 train 拟合逻辑回归，在 dev 按固定风险上限选择覆盖率最高的完整同分组。默认风险上限 10%，无可行非零覆盖时保存全拒答阈值。将输出的 `artifact_hash`、`fit_split`、`calibration_split`、`threshold` 写入新配置的 `method_configs.<方法>.gate`。每个消融用自己的工件。用新配置重生成正式清单。runner 按工件内容哈希和训练上下文核对来源，对 test 拒绝出现过的 train/dev family。测试题只用冻结配置运行。
