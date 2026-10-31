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

## 2026-10-30：C 端补齐与实际核验

以下为本轮实际执行，不改变上文 10/19 历史记录。运行环境为 Python 3.13.9、matplotlib 3.10.6。由 Codex 辅助实施并执行软件核验，C 本人及 A/B/D 的人工签收仍待完成。

### 实现

- report.py：按条件主表、B7−B5 四指标 CI、复本变化两指标 CI、独立复本诊断、曲线 CSV、每条件 SVG/PNG、失败/缺失清单与输入/源码/schema/结果哈希。
- scheduler.py：三种核心消融及 H3 面板；缺开关、工件哈希、独立 train/dev 声明或阈值时 blocked，跨变体共享门控哈希也阻塞。这里只校验配置声明，不证明 B 已训练。
- normalize_input.py：修复包导入、合法 null/空参考/失败处理；完整 schema 与跨行重复/泄漏校验；非整数成本拒绝；拒绝覆盖已有输出。
- 分组纳入 dataset/split 哈希；bootstrap 拒绝混合位置种子；manifest 对照完整条件身份并拒绝重复预测。
- 准备 C 交接、真实 10 题验收步骤、消融配置模板、评审说明和计划语态英文评价章节；同步过时状态。

### 实际验证结果

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -v`（另一次 -q 复核） | 44/44 通过，原 31 项 + 新增 13 项；含 CLI、手算差值、缺配对、失败、来源隔离、转换与消融阻塞 |
| 完整一键汇总，2,000 次 bootstrap，带图片 | 8 条虚构预测 → 4 个分条件主表组、2 个条件比较面板、1 个复本比较面板 |
| 图片 | 2 组 SVG/PNG，逐张检查 PNG；条件标题、坐标、图例和 software-selfcheck 标识可见 |
| 数值重算 | summary.json、comparisons.json、replica.json、risk_coverage.csv 逐字节一致 |
| 溯源核对 | 16 个结果文件 SHA256 与清单一致；8 个评价源码文件 SHA256 与当前代码一致 |
| 消融清单 | fixture 两题生成 240 条，72 条消融因缺实际工件等字段 blocked，符合预期 |
| H3 清单 | fixture 两题×两方法×两支持面板×三 metadata×两长度=48 条逻辑任务；仅为软件调度，不表示存在 H3 真实数据 |
| 未提供真实 manifest | 最终包明确 unverified；planned_n 不能证明原计划全部执行 |
| Git 空白检查 | `git diff --check` 无错误；系统提示换行格式转换，不影响检查 |

最终本地自检包：`artifacts/selfcheck/c_delivery_20261030_final/`。`figure_index.json` 对应图片与条件；`bundle_hashes.json` 不包含自身。初次绘图检查及版式迭代保留在同目录下其他软件自检子目录；正式交接以 final 包为例。

风险统计在部分 bootstrap 抽样中因全拒答而无定义，工具实际输出 undefined_replicates 与不稳定提示，未填零。上述数字只描述软件行为，不能写成方法优于基线的研究发现。

### 尚待外部交接

A 的真实数据/标签复核；B 的实际模型、合法 score、三消融开关/独立工件与 dev 阈值；D 的真实日志/失败/成本；10 题真实闭环及 pilot 表图。没有冒记这些已完成，也没有向远端推送或代发消息。
