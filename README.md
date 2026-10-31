# NLP2026_Team12_Research

2026 年自然语言处理课程第 12 组，**Track C: Research**。

**来源依赖信息不完备时，检索增强问答的证据去重与选择性作答研究。**

研究固定检索上下文中同源转载、独立相似证据及来源信息完整/缺失/错误条件下的作答可靠性。已有 [Proposal](Proposal.pdf)（已核对远端分支文件）；尚未完成真实数据、模型方法和正式实验。

## 评价代码

本次提交 C 的输入校验、EM/F1、拒答、完整候选 RC/AURC、复本诊断、配对 bootstrap 与 manifest 生成。

- [使用说明](evaluation/README.md)
- [评价协议](evaluation/protocol.md)
- [统计分析定义](docs/analysis_plan.md)
- [核验记录](evaluation/verification.md)
- [C 交付与真实 10 题联调](docs/c_handoff.md)
- [核心消融调度契约](docs/ablations.md)
- [可交 E 的评价与统计章节草稿](report/sections/evaluation_statistics.md)

Python 3.10+，核心只用标准库；可选图片需要 matplotlib。从仓库根目录执行：

~~~powershell
python -m unittest discover -s tests -v
python -m evaluation.report evaluation/examples/predictions.jsonl --output-dir artifacts/selfcheck/my-check --label software-selfcheck
~~~

evaluation/examples 全为虚构软件 fixture，不能充当课程实验结果。真实数据/模型获取、环境和完整实验运行方法将在相应实现完成后补充。

2026-10-30：已补一键结果汇总、消融/H3 逻辑调度和输入转换验收；C 软件自检与真实模型联调分开记录。当前无真实 pilot/test 结果，详见实现状态与交接说明。

内部完成目标 2026-12-15；中期、最终截止和展示以教师通知为准。课程正式材料按指定飞书渠道统一提交。
