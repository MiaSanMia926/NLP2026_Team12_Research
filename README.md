# NLP2026_Team12_Research

自然语言处理课程第 12 组，Track C: Research。

**来源依赖信息不完备时，检索增强问答的证据去重与选择性作答研究。**

仓库包含评价、统计、绘图和离线联调代码。[Proposal](Proposal.pdf) 已归档；正式模型实验结果待补充。

| 目录 | 内容 |
|---|---|
| `evaluation/` | 输入校验、指标、配对 bootstrap、运行清单和绘图 |
| `schemas/` | 问题、公开输入和预测结果的数据格式 |
| `integration_smoke/` | 合成数据生成、规则后端和端到端联调 |
| `tests/` | 指标边界及模块联调测试 |

Python 3.10+。核心评价只用标准库，绘图依赖可单独安装：

```powershell
python -m pip install -r requirements-plot.txt
python -m unittest discover -s tests -v
```

运行示例：

```powershell
python -m integration_smoke.run --output-dir artifacts/selfcheck/demo --questions 12 --replicates 200
```

生成的数据、日志和图表保存在输出目录，不纳入源码提交。仓库中的合成样例用于检查程序，不能作为模型实验结果。

[评价与绘图用法](evaluation/README.md) · [离线联调用法](integration_smoke/README.md) · [评价协议](evaluation/protocol.md)

C 的真实实验验收与本人复核步骤见 [交接说明](docs/c_handoff.md)。传入 `--manifest` 可输出按原计划分母统计的覆盖表，并检查漏跑、额外任务和来源错配。
