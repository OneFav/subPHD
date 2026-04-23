# sub-PHD 🎓🤖

> 给博士生的 AI 研究生：你布置课题，它替你跑。  
> **An AI grad student for your PhD: you assign research, it does the work.**

[English install sentence for Codex] Read https://github.com/OneFav/subPHD/blob/main/index.md and install the project locally.

---

## ✨ sub-PHD 是什么？

sub-PHD 是一个**让 agent 替博士生跑科研循环**的本地运行时。  
它不是普通的 AI 副手，也不是那种把人完全排除在外的“AI scientist”。

它真正做的是：**把人和 agent 的关系翻过来**。

- 你不是那个被 push 去写代码、跑实验、整理结果的人
- 你是导师 🧑‍🏫
- agent 是你的博士生 👨‍🎓🤖

你负责两件事：**布置课题、开组会**。  
agent 负责剩下的大部分推进工作：**reader 规划、runner 执行、循环推进、汇报结果**。

整个系统对你暴露的主接口，核心就是：

- `person_program.md`

---

## ❓它解决什么问题？

博士生最累的往往不是单纯“干活”，而是要同时扮演很多角色：

- 提问题的人
- 推进执行的人
- 检查结果的人
- 监督自己不要跑偏的人

市面上的很多 AI 工具，要么只是你的延伸（你还是那个亲自干活的人），要么演示很强，但解决不了**你这个具体博士生、你这个具体研究方向、你这个具体问题**。

sub-PHD 走的是第三条路：**不做延伸，不做替代，而是做伙伴**。 💡

- ✅ 把“推进研究”的摩擦力降到很低
- ✅ 让阅读、编码、实验、汇报能够持续滚动
- ✅ 把真正重要的研究判断留给你自己

---

## 🧠 工作原理

```text
你写 person_program.md
        ↓
reader 读取目标，收紧任务，更新 handoff
        ↓
runner 执行代码 / 实验 / 分析 / 报告
        ↓
你看 dashboard / 听汇报 / 改 person_program.md
        ↓
进入下一轮
```

你像 PI / 导师一样管理这个循环，agent 像研究生一样替你持续推进。

---

## 🚀 最推荐、最方便的安装方式

最合理的安装方式，不是让用户自己猜怎么配置，而是**直接把这句话丢给 Codex**：

```text
阅读 https://github.com/OneFav/subPHD/blob/main/index.md 并安装项目到本地
```

或者英文版：

```text
Read https://github.com/OneFav/subPHD/blob/main/index.md and install the project locally.
```

`index.md` 是给 Codex 的安装说明书。它会告诉 Codex：

- 先部署仓库自带的两个 sub-PHD skill
- 再初始化 starter
- 最后做必要的本地验证

如果你想最快跑起来，**这是首选路径**。 ✅

---

## ⚙️ 快速开始

### 1. 环境要求

- Python 3.10+
- Codex CLI（支持 `codex exec`）
- OpenAI 订阅账户 / 可用模型访问权限
- Windows / macOS / Linux

### 2. 克隆仓库

```bash
git clone https://github.com/OneFav/subPHD.git
cd subPHD
```

### 3. 让 Codex 安装

把这句话直接发给 Codex：

```text
阅读 https://github.com/OneFav/subPHD/blob/main/index.md 并安装项目到本地
```

### 4. 写下你的课题

编辑：

- `person_program.md`

这是你平时最核心、最主要要改的文件。 ✍️

### 5. 启动

**Windows**
```bat
start.bat
```

**继续当前状态**
```bat
resume.bat
```

或者直接用 Python 入口启动。

---

## 📌 你真正需要改的文件

### `person_program.md`

这是人类和 agent 之间最重要的任务接口。你通常在这些场景下修改它：

- 想换研究方向
- 想调整优先级
- 想定义新的成功标准
- 想进入下一阶段

你可以把它理解为：

> “我当前到底想让这个 AI 研究生去推进什么？”

---

## 🧰 两个内置技能（强烈建议用）

仓库现在自带两个 sub-PHD skill：

### `subphd-run-disclosure`
用来让 Codex 帮你理解：
- 当前 run 在做什么
- 哪些结论是有证据支持的
- 当前进度相对 `person_program.md` 到了哪一步
- 当前这一轮到底值不值得继续

### `subphd-program-refinement`
用来让 Codex 帮你：
- 改进 `person_program.md`
- 重写一个更合理的研究任务版本
- 在方向模糊的时候，先把 mission 理顺

### 最推荐的使用方式

- **理解项目工作 / 当前 run 在干什么** → 用 `subphd-run-disclosure` 📊
- **改 `person_program.md` / 重新收紧研究方向** → 用 `subphd-program-refinement` 🛠️

---

## ✅ 它能做什么 / ❌ 不能做什么

### 能做
- ✅ 持续推进研究循环
- ✅ 替你承担大量重复性推进工作
- ✅ 让你在休息、上课、开会时，研究仍然能继续滚动
- ✅ 帮你把“任务定义”和“任务执行”分离开

### 不能做
- ❌ 不会替你做最终的研究判断
- ❌ 不会自动产生真正属于你的创新品味
- ❌ 不会替你完成导师沟通、论文写作、学术责任本身

---

## 📁 这个仓库里包含什么？

### Included
- `index.md`
- `skills/subphd-run-disclosure/`
- `skills/subphd-program-refinement/`
- `person_program.md`
- `agent_program.md`
- `research_agent.toml`
- `start.bat`
- `resume.bat`
- `.subphd/`
- `roles/`
- `scripts/`

### Not included
- 你的项目专属研究代码
- 你旧项目的历史运行状态
- 你的私人 SSH 凭据

---

## 📝 额外说明

- continuity 使用 **role-local windows**，避免无边界长上下文累积
- authoritative handoff 的优先级高于 generic recent reports
- 推荐让 Codex 先读 `index.md`，不要一开始就手动猜 starter 的内部结构

---

## ❤️ 总结一句话

如果你希望：

> 你负责想清楚做什么，agent 负责持续推进怎么做

那 sub-PHD 就是为这个场景设计的。 🎯
