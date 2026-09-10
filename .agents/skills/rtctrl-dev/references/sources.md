# 维护依据与开源参考

核查日期：2026-09-10。以下链接是参考资料，不作为需要安装或执行的依赖。

- [OpenAI skill-creator](https://github.com/openai/skills/blob/main/skills/.system/skill-creator/SKILL.md)：借鉴简短入口、按需加载 references、结构校验与实际使用后迭代。
- [obra/superpowers subagent-driven-development](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md)：借鉴明确的独立任务交接、需求与质量审查、主 agent 汇总。按本项目任务规模采用，不复制其完整流程、自动提交或模型选择策略。
- [官方 skills 文档](https://learn.chatgpt.com/docs/build-skills)：项目 `.agents/skills/`、显式调用与隐式匹配、界面元数据。
- [官方 subagents 文档](https://learn.chatgpt.com/docs/agent-configuration/subagents)：项目 `.codex/agents/*.toml` 与 `name`、`description`、`developer_instructions` 字段。

文件为结合本仓库编写的原创指导，没有下载运行开源脚本或整套引入第三方 skill。
客户端可能存在版本差异；配置调整时重新核实官方文档，不根据角色文件存在就宣称已成功加载。
