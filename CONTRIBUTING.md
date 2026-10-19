# 小组协作指南

## 1. 文件夹和分支一起使用

文件夹按模块存放最终成果；分支用于隔离某次任务的修改。所有成员共享一套项目，不建立 `成员A/成员B/` 各自的代码副本。

采用 `main + 短期任务分支`。一个任务可以包含多次提交；不必每改一个文件就新建分支。任务完成并合并后，下一项任务从最新 `main` 开始。

| 示例分支 | 对应任务 | 建议复核人 |
|---|---|---|
| `codex/data-pilot` | A：pilot 数据与标注规则 | D 独立复核，B/C 检查接口 |
| `codex/baselines-b0-b3` | B：环境、runner、基础方法 | C/D |
| `codex/evaluation-metrics` | C：指标与边界核验 | A/B |
| `codex/pilot-results` | D：运行索引与结果 | B/C |
| `codex/milestone-report` | E：中期报告与 Slides | A–D 对应章节负责人 |

以上是命名示例，不需要组织者提前建立这些分支。共享接口和配置由对应负责人协调；涉及多模块时在 Issue 中说明交接。

## 2. 首次加入

成员应先确认自己能访问仓库，领取 A–E 角色，在 `CONTRIBUTIONS.md` 填写姓名和 GitHub 账号。仓库所有者在 GitHub 的 Settings → Collaborators 中邀请真实成员账号；成员接受邀请后再确认推送权限。账号未提供时，不能预先邀请或替他人认领角色。

克隆仓库：

```powershell
git clone https://github.com/MiaSanMia926/NLP2026_Team12_Research.git
cd NLP2026_Team12_Research
```

Git 提交身份由本人设置，不能复制别人的姓名和邮箱。按实际 GitHub 账户配置已验证邮箱或 GitHub 提供的隐私邮箱。

## 3. 从任务到 PR

先用阶段任务模板建 Issue，写清负责人、验收人、阶段截止、上游依赖、实际交付文件和完成条件。

在工作区没有未保存修改时，以下以 C 的指标任务为例：

```powershell
git switch main
git pull --ff-only origin main
git switch -c codex/evaluation-metrics
```

修改后，先查看再添加自己负责的文件：

```powershell
git status
git diff
git add evaluation/metrics.py
git commit -m "Implement selective-risk metrics and boundary checks"
git push -u origin codex/evaluation-metrics
```

示例中的文件是未来任务产物，不表示目前已有实现。按实际修改路径执行 `git add`，避免把大日志、密钥或无关文件一并提交。

推送后在 GitHub 打开 Pull requests → New pull request：

- base 选择 `main`，compare 选择自己的任务分支。
- 用仓库 PR 模板填写目的、变化、验证、关联 Issue 和重跑影响。
- 指定交叉复核人；尚未完成可先创建 Draft PR。
- 有评审意见时继续修改同一任务分支，commit/push 后原 PR 自动更新，无需重新开 PR。
- 复核通过后合并；优先使用 Squash and merge 保持主线清晰，合并说明保留贡献和协作事实。
- 合并后删除远端任务分支，本地回到 `main` 并更新。

PR 评审是团队约定，当前仓库没有因此自动启用强制分支保护。不要把“有模板”理解为技术上已阻止直接推送。

## 4. 文档也走相同流程

Markdown、报告章节、标注规范和实验记录均可以通过任务分支与 PR 交付。报告按章节拆文件，E 负责主文件和统一排版；其他成员修改本人负责章节。

无新文件变化的评审、标注讨论、运行监控可记录在 Issue 或贡献表中，不强制每人每阶段创建 PR。PDF 附可编辑源文件；数字表图优先由脚本生成，不手动修改结果凑一致。

## 5. 冲突与同步

任务开始前更新 `main`；长任务需要同步时，先提交或妥善保存本地修改，再执行：

```powershell
git fetch origin
git merge origin/main
```

如出现冲突，与相关文件负责人确认后处理，检查完整文件并验证。不要整份覆盖队友版本或对共享分支 force push。短任务分支尽快交评审，减少多人修改同一配置。

## 6. 合并前检查

- 文件放在约定模块；新增/变更接口有样例、版本与迁移说明。
- 只宣称实际完成的工作，测试/运行证据与描述对应。
- 科学计算改动核对分母、划分、配对与边界；数据/方法/配置变化注明是否重跑。
- 无 API key、`.env`、个人凭据、模型权重、大缓存或不可公开材料。
- 结果附 run_id、版本/哈希、获取方式；失败不能当拒答或静默删除。
- 第三方与 AI 使用如实记录；贡献表写具体产出，不以提交次数代替工作量。

详细科学规范以根目录 [实验规范与整合协议](实验规范与整合协议.md) 为准；每阶段截止和验收见 [阶段方案](项目DDL与任务规划.md)。
