# sub-PHD

> 给博士生的 AI 研究生：你布置课题，它替你推进研究循环。

sub-PHD 是一个本地 reader/runner 研究运行时。你保留研究判断权，agent 负责把阅读、规划、编码、执行和汇报这条链条持续往前推。

## 最推荐、最方便的安装方式
最合理的安装方式，不是让用户手动猜怎么配，而是**直接把下面这句话丢给 Codex**：

```text
阅读 https://github.com/OneFav/subPHD/blob/main/index.md 并安装项目到本地
```

也可以用英文：

```text
Read https://github.com/OneFav/subPHD/blob/main/index.md and install the project locally.
```

`index.md` 就是给 Codex 的安装说明书。它会告诉 Codex：
- 先部署仓库自带的两个 sub-PHD skill
- 再初始化 starter
- 最后做必要的本地验证

## sub-PHD 是做什么的
如果你想让 agent 帮你持续推进研究，但又不想把研究判断完全交出去，sub-PHD 就是为这个场景设计的。

你负责：
- 定义问题
- 判断轻重缓急
- 看证据、开组会
- 改写研究任务

agent 负责：
- 读材料
- 收紧 handoff
- 写代码 / 跑流程
- 产出报告
- 继续下一轮

它不是普通 AI 副手，也不是完全自治的 AI scientist，更像是**在你指导下工作的 AI 研究生**。

## 快速开始
1. clone 这个仓库
2. 让 Codex 阅读 `index.md` 并完成本地安装
3. 编辑 `person_program.md`
4. 用 `start.bat` 或 Python 入口启动

## 你平时真正需要改的文件
`person_program.md`

这是主要的人类任务文件。你通常在以下时候改它：
- 想换研究方向
- 想调整优先级
- 想重定义成功标准
- 想进入下一阶段

## 两个内置技能
这个 starter 自带两个 sub-PHD skill，文档默认你会用它们来理解项目和改任务。

### `subphd-run-disclosure`
当你想让 Codex 解释下面这些问题时，用它：
- 当前 run 在做什么
- 哪些结论已经有证据支持
- 证据来自哪里
- 当前进度相对 `person_program.md` 到了哪一步

### `subphd-program-refinement`
当你想让 Codex 帮你改进 `person_program.md` 时，用它：
- 梳理一个还不够清楚的新研究方向
- 提出更好的 `person_program.md` 候选改写
- 让 mission 更正确，但不过度写死

## 运行模型
- `start.bat` = 一个新的大轮次开始
- `resume.bat` = 继续当前状态
- continuity 用 role-local window 控制，不做无边界长上下文累积
- authoritative handoff 比 generic recent reports 优先级更高

## 包含内容
- `index.md`
- `skills/subphd-run-disclosure/`
- `skills/subphd-program-refinement/`
- `person_program.md`
- `agent_program.md`
- `research_agent.toml`
- `start.bat` / `resume.bat`
- `.subphd/`
- `roles/`
- `scripts/`

## 不包含
- 你的项目专属研究代码
- 你旧项目的运行历史
- 你的私人 SSH 凭据

## 说明
- SSH 能力保留，但仓库不会附带你的真实配置。
- **理解项目工作**，优先用 `subphd-run-disclosure`。
- **修改 `person_program.md`**，优先用 `subphd-program-refinement`。
