# 离线联调

用合成问题和规则后端检查数据生成、预测、日志、评价和绘图的完整流程。运行不需要模型权重或 API key；这些输出不是大模型实验结果。

```powershell
python -m integration_smoke.run --output-dir artifacts/selfcheck/demo --questions 12 --replicates 200
```

核心流程只依赖标准库。图片需安装 `requirements-plot.txt`，也可加 `--no-figures`。输出目录须新建或为空。

默认生成 12 个基础题，覆盖四类证据、四种复本/支持面板、三档来源元数据、两种长度和四个规则方法，共 1,152 条任务。固定四题 train，其余为 dev，不使用正式 test。

| 文件 | 内容 |
|---|---|
| `dataset.py` | 数据构造、划分、来源变体、公开输入与独立 gold |
| `backend.py` | 投票、精确去重、来源计数和固定拒答门控 |
| `runner.py` | 原始响应、有限重试、恢复及离线标签合并 |
| `run.py` | 调用上游与 C 的评价入口，检查清单和重算一致性 |

规则方法使用 `SMOKE_*` 名称，不代表正式 B0–B7。后端只解析显式模板属性，不做两跳推理；分数是支持比例，门控阈值是固定规则。长度由自定义正则 tokenizer 计数，不是任何大模型的计费 token。

## 数据

`examples/` 保留四个基础题、八条公开输入及对应 gold，分别覆盖证据一致、错误反证、无法消解的冲突和证据不足。它们是明确标注的最小测试样例，不是正式 pilot。

```powershell
python -m evaluation.validation integration_smoke/examples/questions.jsonl --kind question
python -m evaluation.validation integration_smoke/examples/public_inputs.jsonl --kind public_input
```

完整数据由脚本重建。公开输入和 gold 分开保存，预测函数只接收公开输入；正确性标签在运行结束后离线合并。

运行会生成 `data/`、`logs/`、`scored_predictions.jsonl`、`evaluation_all/` 和 `evaluation_demo/`。失败尝试会保留，恢复时跳过成功任务。评价的调用数是规则后端调用数，引用标签是合成文本检查结果，均不等于真实 API 费用或人工审核。
