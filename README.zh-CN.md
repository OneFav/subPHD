# sub-PHD 迁移启动包

这个包是一个最小可复用的 sub-PHD 运行时框架，用来迁移到新的项目中。

## 已包含
- `index.md`（给 agent 用的初始化入口文档）
- `person_program.md`
- `agent_program.md`
- `research_agent.toml`（默认不带现成 SSH 配置）
- `start.bat`（全新启动）
- `resume.bat`（继续当前状态）
- `.subphd/` 初始化运行时状态
- `roles/reader/`
- `roles/runner/`
- `scripts/`
- `research/` 下供配置引用的轻量占位日志文件

## 未包含
- 项目专属研究代码
- 来源项目的旧运行状态和历史
- 旧的 reports / prompts / commands / synced results
- 项目专属实验产物

## 典型迁移步骤
1. 将这个启动包复制或解压到新项目目录。
2. 先让 agent 读取 `index.md` 并完成初始化。
3. 按新项目目标改写 `person_program.md`。
4. 如有需要，在 `research/` 下补充项目自己的文件。
5. 启动时：
   - 新任务用 `start.bat`
   - 续跑用 `resume.bat`

## 说明
- `index.md` 是 agent 引导初始化时应优先读取的文档。
- SSH 仍然受支持，但仓库默认不携带现成 SSH 配置。
- 初始化完成后，用户通常只需要维护 `person_program.md` 和 `research/` 下的项目代码。
- `start.bat` 会先重置 `.subphd/state/*`。
- `resume.bat` 会复用当前 `.subphd/state/*`。
- 当前 canonical runtime 根目录是 `.subphd/`。
