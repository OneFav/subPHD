# sub-PHD 🎓🤖

> 给博士生的 AI 研究生：你布置研究任务，它替你推进执行。

sub-PHD 是一个面向研究循环的本地 reader/runner 运行时。你保留科学判断权，agent 负责把阅读、规划、编码、执行和汇报持续往前推进。

## 🚀 最方便的安装方式
最推荐的安装方式，不是手动猜配置，而是**直接把下面这句话交给 Codex**：

```text
阅读 https://github.com/OneFav/subPHD/blob/main/index.md 并安装项目到本地
```

你也可以用英文版：

```text
Read https://github.com/OneFav/subPHD/blob/main/index.md and install the project locally.
```

`index.md` 是给 Codex 的安装契约。它会告诉 Codex：
- 部署仓库自带的两个 sub-PHD skill
- 初始化 starter
- 运行所需的本地验证

## 🧠 sub-PHD 是为了解决什么问题
如果你想让 agent 持续推进研究，但又**不想把真正的科学判断交出去**，sub-PHD 就是为这个场景设计的。

你负责：
- 定义问题
- 决定优先级
- 审阅证据
- 重写研究任务

agent 负责：
- 阅读材料
- 收紧 handoff
- 写代码 / 跑流程
- 产出报告
- 继续下一轮

它不是普通 AI copilot，也不是完全自治的 “AI scientist”。它更像是**在你指导下工作的 AI 研究生**。 👨‍🎓🤖

## ⚡ 快速开始
1. clone 这个仓库
2. 让 Codex 读取 `index.md` 并完成本地安装
3. 编辑 `person_program.md`
4. 用 `start.bat` 或 Python 入口启动

## ✍️ 你真正会修改的文件
### `person_program.md`

这是主要的人类任务文件。通常在这些时候修改它：
- 改研究方向
- 调整优先级
- 重定义成功标准
- 进入下一阶段

## 🧰 两个内置技能
这个 starter 自带两个 sub-PHD skill，文档默认你会用它们来理解项目工作和收紧 mission。

### `subphd-run-disclosure`
当你想让 Codex 解释下面这些问题时，用它：
- 当前 run 在做什么
- 哪些结论真正有证据支持
- 有哪些证据存在
- 当前进度相对 `person_program.md` 到了哪一步

### `subphd-program-refinement`
当你想让 Codex 帮你改进 `person_program.md` 时，用它：
- 收紧一个还比较模糊的下一步研究方向
- 提出更好的 `person_program.md` 改写版本
- 让 mission 更正确，但不要过早写死

## 🔁 运行模型
- `start.bat` = 开启一个新的大轮次
- `resume.bat` = 继续当前状态
- continuity 通过 role-local window 控制，而不是无限累积长上下文
- authoritative handoff 的优先级高于 generic recent reports

## 📦 包含内容
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

## 🚫 不包含
- 你的项目专属研究代码
- 你之前的运行历史
- 你的私人 SSH 凭据

## 📝 说明
- SSH 支持仍然保留，但仓库不会附带你的真实配置。
- 如果你想**理解项目当前在做什么**，优先用 `subphd-run-disclosure`。
- 如果你想**修改 `person_program.md`**，优先用 `subphd-program-refinement`。
