# Git 操作细节

先完成 [入口](../SKILL.md) 的范围与现场检查。下列占位符必须替换成已核实值，
仅执行当前请求需要的步骤；示例不构成推送、改写或丢弃内容的授权。

## worktree 与分支

先核实已有 worktree、分支占用和起点。需要隔离时，优先使用宿主提供的 worktree 工具；
不可用时可用原生 Git：

```bash
git worktree list
git worktree add -b codex/<主题> <新目录> <已核实起点>
```

已有分支则使用 `git worktree add <新目录> <分支>`，不加 `-b`。起点不默认等于 main。
新目录没有旧工作区的未提交代码；需要基于那些代码时先确定如何保留和迁移，不能假装已经包含。
删除前检查该 worktree 的已修改、未跟踪及被忽略文件，并确认重要内容均已保存。
用普通 `git worktree remove <目录>`；失败时解释原因，不强制删除。

## 同步与合并冲突

先用 `git branch -vv` 核实 upstream，按任务需要 `git fetch <远端>` 后比较：

```bash
git log --left-right --oneline HEAD...<远端跟踪分支>
git diff HEAD...<远端跟踪分支>
```

能快进且任务要求同步时可 `git merge --ff-only <目标>`；分叉时根据协作方式选择
merge 或对本地未共享提交 rebase。避免未检查就执行带隐式策略的 `git pull`。

发生冲突时用 `git status`、`git diff --name-only --diff-filter=U` 定位文件，理解两侧修改，
只暂存已解决文件，然后执行对应的 `merge/rebase/cherry-pick --continue`。
检查原始意图仍成立，运行受影响测试；“无冲突标记”不等于行为正确。
若决定放弃本任务发起的操作，核实原始状态后使用对应 `--abort`，不自动中止别人启动的流程。

## rebase、fixup 与拆分提交

对已确认的本地未共享提交整理历史。核实工作区/暂存区可安全操作，记录起点并创建唯一备份分支：

```bash
git branch codex/backup-<主题> HEAD
git rebase -i <已核实基线>
```

`reword` 改说明，`edit` 停下修改，`squash/fixup` 合并提交；`drop` 会丢掉该提交的改动。
非交互工具不能盲等编辑器；只有 todo 内容已明确时才使用任务局部 editor，不改全局 Git 配置。
fixup 使用明确目标 `git commit --fixup <目标提交>`，再在已核实范围内 autosquash。

拆分提交时仅在 `edit` 停点、工作区状态已核实时用 `git reset --mixed HEAD^` 保留文件内容，
按路径/补丁块重建提交后继续。备份分支没有保护未提交文件，不以它为理由执行 hard reset。
结束后用 `git range-diff <旧基线>..<备份分支> <新基线>..HEAD` 等检查补丁语义和最终树。

## cherry-pick

先查看 `git show <提交>` 与依赖，再执行 `git cherry-pick <提交>`。
`A..B` 不含 A；范围移植前用 `git log --reverse --oneline A..B` 核对集合和顺序。
merge commit 的 `-m` 需要理解主线父提交，不能猜。

只移植部分修改时可在干净、隔离的 worktree 中用 `git cherry-pick -n <提交>` 审查补丁。
`git restore --source=<提交> -- <文件>` 是替换整份文件，不等于应用该提交对文件的增量；
它可能覆盖目标分支上已有修复，不能把它作为“部分 cherry-pick”的默认做法。

## bisect

在干净的独立 worktree，确认已知好版本、坏版本及可重复测试。先验证测试在两个端点上的结果：

```bash
git bisect start <坏提交> <好提交>
git bisect run <已验证测试命令>
git bisect reset
```

测试 exit 0 为 good，1–127 除 125 为 bad，125 表示 skip；错误命令/依赖缺失不能误报成产品回归。
无法构建的中间版本应明确判断是否 skip。板端、权限或模型版本不匹配时不能伪造好坏结论。
多个 skip 可能导致无法唯一定位，需如实报告候选范围。

## 恢复与撤销

用 `git reflog show <引用>` 找到候选，再 `git show <OID>` 核实，优先
`git branch codex/recovery-<主题> <OID>` 并在独立 worktree 查看内容。
reflog 只记录本地引用移动；过期时间受配置、可达性和 GC 影响，不保证 90 天可恢复，
也不能找回从未入库的未提交内容。

共享历史中撤销已发布修改通常用 `git revert <提交>` 创建反向提交，再验证依赖和行为。
仅撤销本地最后一次提交且保留暂存内容可用 `git reset --soft HEAD^`，但先核实当前分支、
该提交是否已共享、是否存在父提交，以及现有暂存内容是否会混入后续提交。
用户确需丢弃数据时先展示精确对象与影响范围，再按现有授权执行；不提供默认整仓清理步骤。
