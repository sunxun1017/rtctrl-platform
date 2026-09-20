---
name: git-advanced-workflows
description: 用于 rtctrl-platform 的 Git 状态检查、按主题提交、分支与 worktree 管理、合并冲突、rebase、cherry-pick、bisect、reflog 恢复及已授权的远端同步。用户要求管理 Git、整理提交或处理版本历史时使用；普通源码讲解不触发。
license: MIT
---

# Git 管理

基于 wshobson/agents 的同名 skill 做项目适配；固定版本、修改说明与许可证见
[来源](references/sources.md)。遵循项目 [AGENTS.md](../../../AGENTS.md)、
[协作偏好](../../PROJECT_MEMORY.md) 和用户当前要求。

## 先确认现场

在实际仓库或目标 worktree 内检查：

```bash
git status --short --branch
git branch --show-current
git worktree list
git diff --stat
git diff --cached --stat
```

随后只读取任务相关的工作区和暂存区 diff。记录原有修改、暂存内容及正在进行的
merge/rebase/cherry-pick；不自动中止别人的操作。分支为空表示 detached HEAD，
先确定要保存提交的分支；默认新分支用 `codex/`，用户指定名称时遵从。

Windows 通过 WSL UNC 路径访问本仓库时，优先在对应发行版内运行 Git。
核实发行版与 Linux 路径后使用 `wsl.exe -d <发行版> --cd <仓库路径> git ...`；
不为绕过 ownership 检查修改全局 `safe.directory`。下文命令示例使用 Bash 语法。

## 日常提交

按独立主题组织当前任务的修改；只读审查请求不触发提交。已有暂存文件不代表它们属于本任务。
明确路径后用 `git add -- <路径...>`；同文件混有用户改动时按补丁块暂存，
无法可靠分离时先报告具体冲突点。不要整仓 `git add .`、`git add -A` 或 `git commit -a`。

提交前检查实际暂存差异并按 [验证指南](../rtctrl-dev/references/verification.md)
运行匹配检查。仅 Markdown/元数据变更检查格式、链接和 frontmatter 即可。
不提交凭据、人脸/录音数据、构建产物或设备临时文件。submodule 变更需同时核实内部状态
与父仓库 gitlink，不把移动分支当作固定版本，见 [第三方依赖](../../../third_party/README.md)。

提交说明写清问题、修改、验证条件与限制；性能收益只写实际测量值。沿用近期提交风格，
可用 `feat/fix/docs/chore(scope): 简述`。多行说明写入临时文件，再用 `git commit -F <文件>`。
不要把用户已有暂存内容一并提交；如无法隔离，在提交前指出需用户决定的范围。
不跳过 hooks；hook 失败时按实际状态修复，不假设已生成提交。

提交后核对 `git show --stat --oneline HEAD` 和 `git status --short --branch`，
报告提交及仍保留的改动。子 agent 仅提供建议，提交与整合由主 agent 负责。

## 分支、冲突与历史

需要隔离任务时才创建 worktree；已有合适 worktree 则复用。新 worktree 不含原工作区
未提交内容，必须核实目标分支和起点，不自动 stash 用户工作。

只在需要时读取 [操作细节](references/details.md)：

| 当前任务 | 选择依据 |
| --- | --- |
| 同步、合并、冲突 | 先确认基线与远端跟踪关系；共享历史优先保留提交关系 |
| 整理本地提交 | 在已确认范围内 rebase/fixup；改写前保存引用并确认工作区状态 |
| 跨分支移植 | cherry-pick 已核实的提交，理解依赖和冲突后继续 |
| 定位回归 | 独立 worktree 中 bisect；测试必须区分故障、正常和无法测试 |
| 找回提交或撤销 | reflog 找到对象后先建立恢复分支；共享提交通常用 revert |

恢复分支只能保留提交，不能备份未提交/未跟踪文件。不要把 `reset --hard`、
`clean -fd`、覆盖式 restore 或删除 worktree 当作默认收尾；确需丢弃内容时核实对象、
可恢复性及当前授权。冲突按两侧意图逐文件解决，不整仓选择 ours/theirs。

## 远端同步

按任务需要核实 remote、upstream、待推送提交及目标分支，显示结果时隐藏 URL 内凭据。
普通开发或本地提交不自动授权 push、发布 tag、删除远端分支或改写共享历史。
已有明确授权时继续执行对应操作，不重复确认；不要以旧任务授权推送新任务。

确需并已授权强制更新某个远端引用时，先核实远端当前 OID 与待替换提交，使用显式
`--force-with-lease=<目标引用>:<已核实OID>`；lease 失败后重新比较，不能改成 `--force`。
完成后核对远端引用；创建 PR 时遵守当前工具的附件要求。不把本 skill 当作自动同步后台服务。
