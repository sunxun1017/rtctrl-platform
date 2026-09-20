# 来源与项目适配

- 上游：[wshobson/agents — git-advanced-workflows](https://github.com/wshobson/agents/tree/4236bb91f8395b0435f1d8b8baf9e8e4c69a8620/plugins/developer-essentials/skills/git-advanced-workflows)
- 固定提交：`4236bb91f8395b0435f1d8b8baf9e8e4c69a8620`。
- 安装与适配日期：2026-09-21。
- 许可证：MIT，Copyright (c) 2024 Seth Hobson；原文保存在 [LICENSE](../LICENSE)。
- 使用 Codex `skill-installer` 的 `install-skill-from-github.py`，指定上述 ref、上游 skill 路径，
  通过下载方式安装到项目 `.agents/skills/`，没有安装外部执行脚本或 Git hooks。

下载原件 SHA-256（适配前，不是当前文件校验值）：

| 上游文件 | SHA-256 |
| --- | --- |
| `SKILL.md` | `05205690ef34b05d1ae2596a59f9897680511198b16b38e9a6c1bf04e8da9711` |
| `references/details.md` | `66ef1df71f2fb9cb6a86bb24e33175a3b2a2889afa245c7e6fa9bea8ac10cd44` |

本地适配：中文入口和参考页，增加按主题提交、已有暂存内容保护、WSL Git、项目验证入口及
submodule 检查；增加 Codex UI 元数据。保留高级 Git 工作流主题，移除示例里的默认推送、
整仓暂存和破坏性恢复链；明确 reflog 期限及整文件恢复不等于增量移植的限制。

这是固定版本的项目内副本，不会自动跟随上游更新。更新时比较上述提交与新版本，
保留项目适配并重新检查入口、链接和操作边界。
