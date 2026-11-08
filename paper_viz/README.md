# paper_viz —— ACL/CCF 论文风格结果可视化模块

本模块是为 Track C 研究项目「来源依赖信息不完备时 RAG 的证据去重与选择性作答」
单独新建的可视化模块，目标是把结果图做到可直接放进 ACL/CCF 论文的水准。

**它是一个独立模块，不修改、不依赖 `evaluation/` 目录里的任何现有代码**，
你原有的绘图脚本和产物完全不受影响，可以放心使用，也可以随时删掉本目录而不影响主工程。

---

## 1. 目录结构

```
paper_viz/
├── acl_style.py        # 全局样式系统：尺寸、字体、配色、视觉编码、导出、面板标签、脚注
├── paper_figures.py    # 5 张图的绘图主逻辑 + 命令行入口
├── README.md           # 本文件
└── figures/            # 生成的图（每张图同时输出 PDF 矢量和 600dpi PNG）
    ├── fig1_risk_coverage.pdf / .png
    ├── fig2_metadata.pdf / .png
    ├── fig3_dumbbell.pdf / .png
    ├── fig4_forest.pdf / .png
    └── fig5_retention.pdf / .png
```

---

## 2. 环境准备（只需要一个免费依赖）

本模块只依赖 `matplotlib`，版本与项目 `requirements-plot.txt` 锁定一致。
在 PowerShell 中执行：

```powershell
python -m pip install matplotlib==3.10.6
```

安装一次即可，之后重复运行不需要再装。无需任何付费软件或在线服务。

---

## 3. 运行命令（保姆级）

确认数据文件存在后，在 PowerShell 中执行下面这一整行（路径可以直接照抄）：

```powershell
python "C:\Users\czh99\Desktop\NLP\paper_viz\paper_figures.py" `
  "C:\Users\czh99\Desktop\NLP\artifacts\selfcheck\ab_to_c_20261031\scored_predictions.jsonl" `
  --output-dir "C:\Users\czh99\Desktop\NLP\paper_viz\figures"
```

参数说明：

- 第一个参数：输入的 `scored_predictions.jsonl` 数据文件路径。
- `--output-dir`：图输出目录，不存在会自动创建。
- 可选 `--length-policy`：默认 `natural_length`，如需固定 token 预算结果可改为
  `--length-policy fixed_token_budget`。

运行结束会打印一个 JSON，列出本次写出的全部文件，`figures_written` 应为 10。

---

## 4. 五张图分别讲什么（对应三个研究问题）

| 图 | 文件 | 对应研究问题 | 内容与职责 |
|---|---|---|---|
| 图1 | `fig1_risk_coverage` | 总览 | 风险-覆盖（risk-coverage）阶梯曲线，两面板分别为原始证据与同源复本，图级图例标注每方法 AURC |
| 图2 | `fig2_metadata` | H2（主比较） | 元数据 complete / missing / incorrect 三态下的 coverage 与 selective risk，带 95% 聚类 bootstrap 置信区间 |
| 图3 | `fig3_dumbbell` | H1 | 同一批 base question 从原始证据到同源复本的配对哑铃图，直观显示复本如何改变 coverage 与 risk |
| 图4 | `fig4_forest` | 方法对比 | Gate 相对 Vote 在四个指标上的差值森林图，右侧附「估计值 [置信区间]」数值列 |
| 图5 | `fig5_retention` | H3 | 独立同义/互补证据保留率，以及选择性作答的两类错误（误答、误拒） |

每张图都按「一个研究问题一张图、一个面板只回答一个问题」的原则组织，
避免了原来多图信息重复、读者要自己拼图的问题。

---

## 5. 视觉编码逻辑（为什么这样配色和选形状）

专业论文图的核心要求是**跨图一致**：同一个东西在所有图里长得一样，读者只需学一次。

- **方法 → 颜色（全图统一）**，采用色盲友好的 Okabe-Ito 配色：
  - Vote：蓝色 `#0072B2`
  - Text dedup.（文本去重）：朱红 `#D55E00`
  - Source count（来源计数）：绿色 `#009E73`
  - Gate（主方法）：黑色 `#1A1A1A`，并加粗强调，让读者第一眼锁定主方法
- **复本条件 → 形状 + 线型（全图统一）**：
  - no_replica：圆形 + 实线
  - same_source_replica：方形 + 虚线
  - independent_support：三角 + 点线
  - complementary_support：菱形 + 点划线
- 颜色和形状是**两条独立通道**：黑白打印时靠形状/线型仍能区分，色盲读者也不会丢失信息。

---

## 6. 排版与导出规范（对齐 ACL/CCF 要求）

- 物理尺寸按 ACL 版心固定：单栏 77 mm（约 3.03 英寸）、双栏 160 mm（约 6.30 英寸），
  放进论文不会出现缩放后字体忽大忽小的问题。
- 字体统一使用 Times New Roman 衬线体（与论文正文一致），数学符号用 STIX；
  基础字号 8 pt、刻度 7.5 pt、面板标签 9 pt 加粗。
- 每张图同时导出：
  - **PDF 矢量图**：论文排版用，任意缩放不模糊；`pdf.fonttype=42`，文字可被正确检索；
  - **600 dpi PNG**：预览、贴 PPT 或不支持矢量的系统用。
- 全框细线、细网格，不使用 `bbox_inches='tight'`（避免实际尺寸漂移），所有留白都在脚本里精确控制。

---

## 7. 统计严谨性（不发明误差棒）

- 图中每一根置信区间都来自**真实的 bootstrap 计算**：
  单切片用 base-question 聚类 bootstrap，方法对比用配对 bootstrap，
  均为 2000 次重采样、95% percentile 区间，与项目统计协议一致。
- 数据本身没有不确定性信息的地方，**不会凭空画误差棒**，也不做平滑处理。
- 完全拒答导致 risk 无定义（如 Gate 在 missing 状态）时，该点按缺失处理，不编造数值。
- 脚本只报告差值与置信区间，不自动写「显著」之类的结论性措辞，结论留给正文。

---

## 8. 切换到真实 B5/B7 冻结数据后怎么做

当前数据来自合成规则后端（`SMOKE_*` 方法名）。等真实冻结测试数据产出后：

1. 把新的 `scored_predictions.jsonl` 路径作为第一个参数传入，命令完全不变。
2. 若新数据的方法字段直接叫 `B5`、`B7`，`acl_style.py` 已预留映射，会自动识别配色与强调；
   若方法名是其他字符串，样式函数也会用稳定的后备配色自动分配，不会报错。
3. 建议在 `METHOD_STYLE`（`acl_style.py` 第 50 行附近）里按真实方法名补全
   「方法名 → (标签, 颜色, 是否强调)」，保证标签文字与论文一致。
4. 真实数据重跑后，务必逐张目视检查一次（尤其样本量变小时置信区间会变宽），
   确认没有标签重叠或裁切，再决定是否需要微调 `subplots_adjust` 的边距。

---

## 9. 常见问题

- **报错 `No module named 'matplotlib'`**：回到第 2 步先安装依赖。
- **图里文字被裁切**：本模块已按 ACL 尺寸调好边距；若你改了数据或字号后出现裁切，
  优先调整对应图函数里的 `fig.subplots_adjust(...)`，不要用 `bbox_inches='tight'`。
- **想单独重画某一张图**：在 Python 里 `from paper_figures import fig2_metadata` 等，
  传入对应切片数据和输出目录即可单独调用，不必每次跑全部。
- **想恢复原来的图**：原 `evaluation/` 下的脚本与产物一个字都没动，直接用原来的即可。
