# C 评价工具核验记录

日期：2026-10-19。C 软件自检完成；A 的标签复核、B/D 真实输出接口交接尚未进行。没有真实模型实验结果。

## 修复与核验

| 草稿问题 | 当前处理 | 核验证据 |
|---|---|---|
| 混合拒答时索引已作答子集越界 | 按实际排序长度迭代，候选/决定分离 | mixed/all-refused/full-curve |
| 不同终点面积混叫完整 AURC | 完整终点 1，partial 单列终点 | 手算 AURC、partial、tie 不变 |
| bootstrap 重复题导致 pair ID 失效 | 每次抽中生成临时 base/pair ID | 重复簇与复本 replicate |
| 默认池化模型/任务/条件 | 多键分组，无池化主结果 | grouping/mixed slice |
| 空参考与未知应答标签被拒 | 受控应拒答质量 0；外部未知 null | should-abstain/external |
| 引用 precision 混用回答分母 | 引用条目和回答比例独立 | 2/3 与 1/2 手算 |
| 无正式 schema 或输入隔离 | 三种 schema、语义与跨划分校验、模型白名单 | duplicate/leak/nonfinite/gold |
| 默认混 oracle，缺预算仍列计划 | 默认七方法，显式 B6，缺项 blocked | 168/192 矩阵、预算与 ID |

## 手算样例

examples/predictions.jsonl 是 2 个虚构题×2 方法×2 重复条件，假模型与标签专用于测试。

- B5：4 条全作答，3 错；coverage=1，risk=0.75，全题 EM=0.25。
- B7：4 条中 2 作答且正确；coverage=0.5，risk=0，全题 EM=0.5。
- B5 全候选 AURC=(0+1/2+2/3+3/4)/4。
- B7 全候选 AURC=(0+0+1/3+1/2)/4；已作答 partial=0，终点 0.5。
- operating risk 的 B7−B5=−0.75。仅为程序断言，绝非研究发现。
- 两题 manifest=2×6×7×2=168；启用 B6 为 192；缺固定预算时 84 条 blocked。

## 执行

运行 python -m unittest discover -s tests -v。本次 31 项通过，覆盖各 CLI 端到端软件 smoke。可选 matplotlib 图片渲染不属于已验证的标准库测试范围。

测试临时目录显式位于仓库内，清理前检查路径。首次测试发现 Windows 沙箱系统临时目录写权限问题，改用仓库临时目录后通过；未绕过权限。

C 交付的是评价定义、接口与工具。真实数据、候选得分定义、token 预算、原始调用及人工审核由相应负责人交接后，才可形成正式结果。

本轮使用 Codex 辅助修订代码与技术说明；手算样例和 31 项测试已实际执行。AI 辅助不替代成员理解、真实标签审核或研究实验。
