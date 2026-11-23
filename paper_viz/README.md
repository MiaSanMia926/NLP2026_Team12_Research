# paper_viz —— ACL/CCF 论文风格结果可视化模块

本模块是为 Track C 研究项目「来源依赖信息不完备时 RAG 的证据去重与选择性作答」
单独新建的可视化模块，目标是把结果图做到可直接放进 ACL/CCF 论文的水准。

论文图复用 `evaluation/` 的指标、配对 bootstrap 和重合曲线判定，绘图入口为 `paper_viz/paper_figures.py`。

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
python -m pip install -r requirements-plot.txt
```

安装一次即可，之后重复运行不需要再装。无需任何付费软件或在线服务。

---

## 3. 复现五张主图

在仓库根目录运行。第一条命令生成合成预测，第二条命令绘图。已有评测输出时，可直接把它传给绘图命令。

```powershell
python -m integration_smoke.run --output-dir artifacts/selfcheck/paper_viz_demo --questions 12 --replicates 200 --no-figures
python paper_viz/paper_figures.py artifacts/selfcheck/paper_viz_demo/scored_predictions.jsonl --split dev --output-dir artifacts/selfcheck/paper_viz_demo_figures
```

参数说明：

- 第一个参数：输入的 `scored_predictions.jsonl` 数据文件路径。
- `--output-dir`：图输出目录，不存在会自动创建。
- 可选 `--length-policy`：默认 `natural_length`，如需固定 token 预算结果可改为
  `--length-policy fixed_token_budget`。
- 可选 `--split`：五张图统一使用同一划分。默认优先选 `test`，其次 `dev`，最后使用输入中的首个划分。
  当前示例的 `dev` 自然长度切片包含 384 条成功记录、8 道基础题，图内标记为 `Synthetic demo`。
  输入包含多个模型、数据版本、随机种子或同一方法的多个配置时，先按单个可比较切片准备 JSONL。

运行结束会打印一个 JSON，列出本次写出的全部文件，`figures_written` 应为 10。

---

## 4. 五张图分别讲什么（对应三个研究问题）

| 图 | 文件 | 对应研究问题 | 内容与职责 |
|---|---|---|---|
| 图1 | `fig1_risk_coverage` | 总览 | 上方对照原始证据与同源复本的经验阶梯曲线，下方列出两条件的 AURC 与描述性差值。完全重合的曲线共用一条线 |
| 图2 | `fig2_metadata` | H2（主比较） | 三种元数据状态的覆盖率与选择性风险，展示点估计、95% 聚类 bootstrap 区间和数值 |
| 图3 | `fig3_dumbbell` | H1 | 每种方法的原始证据和同源复本点估计用线相连，各显示条件内区间，右侧标注描述性百分点变化 |
| 图4 | `fig4_forest` | 方法对比 | Gate−Vote（真实 B 系列采用 B7−B5）的配对差值森林图，估计值和区间位于绘图区外 |
| 图5 | `fig5_retention` | H3 | 左侧附保留/应保留证据组数，右侧列出误答率、误拒率各自的适用预测数 |

每张图都按「一个研究问题一张图、一个面板只回答一个问题」的原则组织，
避免了原来多图信息重复、读者要自己拼图的问题。

---

## 5. 视觉编码逻辑（为什么这样配色和选形状）

专业论文图的核心要求是**跨图一致**：同一个东西在所有图里长得一样，读者只需学一次。

- 主图用深青 `#006C68` 与浅青行底标出 Gate/B7。Vote、Text dedup. 和 Source count 分别使用蓝色、赭色和紫色。
- 风险曲线同时用颜色和线型区分方法。元数据图同时用颜色和点形区分方法，哑铃图用实心圆和空心方区分证据条件。
- 缺失或未定义的估计标为 `NA`，比例图的 `NA` 放在 100% 刻度以外的注记区域。

---

## 6. 排版与导出规范（对齐 ACL/CCF 要求）

- 五张主图保留项目既定的 160 mm 双栏宽度，高度随方法数和标注空间调整。
- 主标题使用 DejaVu Serif，图内使用 Arial 或系统无衬线回退字体，面板字母为 9 pt。标题区显示数据划分、长度策略和基础题总数，各比例的分母以对应面板的定义为准。
- 每张图同时导出：
  - **PDF 矢量图**：论文排版用，任意缩放不模糊；`pdf.fonttype=42`，文字可被正确检索；
  - **600 dpi PNG**：预览、贴 PPT 或不支持矢量的系统用。
- 主图使用细轴线和浅网格。导出保留固定宽度。设置 `NATURE_FIGURE_QA_DIR` 后可执行渲染后的面板对齐检查。

---

## 7. 统计严谨性（不发明误差棒）

- 图中每一根置信区间都来自**真实的 bootstrap 计算**：
  单切片用 base-question 聚类 bootstrap，方法对比用配对 bootstrap，
  均为 2000 次重采样、95% percentile 区间，与项目统计协议一致。
- 数据本身没有不确定性信息的地方，**不会凭空画误差棒**，也不做平滑处理。
- 完全拒答导致 risk 无定义（如 Gate 在 missing 状态）时，该点按缺失处理，不编造数值。
- 脚本只报告差值与置信区间，不自动写「显著」之类的结论性措辞，结论留给正文。

### GitHub 参考

- 用 AURC 读取选择性分类的风险—覆盖率曲线。阶梯端点、分数并列规则和面积沿用本项目的 `evaluation.metrics.risk_curve`。[fd-shifts](https://github.com/IML-DKFZ/fd-shifts/blob/main/docs/publications/neurips_2024.md)
- 元数据图采用分组错位的点与区间，各状态保留独立的比较位置。[seaborn 分组点和区间](https://seaborn.pydata.org/tutorial/objects_interface)
- 森林图为区间和值分别留出布局空间，图例与数据标记分开摆放。[Matplotlib GridSpec](https://matplotlib.org/stable/gallery/subplots_axes_and_figures/gridspec_multicolumn.html) · [Scientific Visualization 示例](https://github.com/rougier/scientific-visualization-book/tree/master/code/ornaments)
- 细轴线、轻网格、无边框图例与固定尺寸样式集中配置。[SciencePlots 科研图样式](https://github.com/garrettj403/SciencePlots/blob/master/src/scienceplots/styles/science.mplstyle)

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
