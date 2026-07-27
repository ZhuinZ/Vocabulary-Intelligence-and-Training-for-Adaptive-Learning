# VITAL Desktop v1.4.2

**VITAL — Vocabulary-Intelligence-and-Training-for-Adaptive-Learning**  
**词汇智能与自适应训练系统**

VITAL Desktop 是一个仅使用 **Python 标准库与 Tkinter** 的桌面英文词汇学习程序。

> 开发者：[ZhuinZ](https://github.com/ZhuinZ)  
> 词典数据来源：[ECDICT](https://github.com/skywind3000/ECDICT)

## 本版本重点更新

- 严格区分“绝对未学习词”和“熟练度为 1 的旧词”；只有从未存在学习记录的词才算新词。
- 使用与服务端相同的 VITAL Ranker v0.2.1 规则模型安排每轮词汇。
- 支持固定新词数量和根据学习间隔、近期保持率自动调整的新词数量。
- 支持命名词库、多个词库保存、切换、删除和当前词库状态展示。
- 词库考试范围与网页版统一为：中考、高考、四级、六级、考研、雅思、托福、GRE。
- 支持“包含任一所选范围”与“同时属于全部所选范围”，并按服务端语义合并同一单词的重复 tag。
- 保留生成词库中的 `tag` 列，供推荐算法计算考试覆盖度与难度。
- 增加详细学习事件日志、学习次数、两次最近评分、首次/最近学习时间。
- 增加学习历史搜索和熟练度筛选。
- 第二轮词义学习使用错位顺序，词数大于 1 时不会与第一轮处于相同位置。
- 文章长度按本轮新词和复习词动态计算，不再固定为 300 词。
- 增加推荐审计日志，记录每个词的类别、分数、原因、概率和两轮顺序。
- 改进主界面、设置页、词库管理页、状态提示、中文标签和 VITAL 品牌展示。
- 已删除并停用桌面版 `.bat`、`.ps1` 启动脚本；统一使用 `python main.py`。
- 保持旧版 `config.json`、`vocabulary.csv` 和两列式 `learningHistory.csv` 兼容。

## 环境要求

- 推荐 Python 3.12；代码不依赖 3.12 独有的第三方包。
- 仅使用 Python 标准库，无需 `pip install`。
- Windows 官方 Python 和 Conda 通常自带 Tkinter。
- 某些 Linux 发行版需要通过系统包管理器安装 `python3-tk`；它不是本项目的 PyPI 依赖。

`requirements.txt` 仅用于明确声明“不需要第三方 Python 包”。

## 启动方式

进入项目目录后运行：

```bash
python main.py
```

本版本不再提供或调用 `.bat`、`.ps1` 文件。

## 首次使用

VITAL 不会自动下载大型词典。首次启动会显示 ECDICT 获取说明：

1. 打开 [ECDICT](https://github.com/skywind3000/ECDICT)。
2. 下载 `stardict.7z`，或下载整个项目后找到该文件。
3. 使用 7-Zip 等工具解压，取得 `stardict.csv`。
4. 启动 VITAL，打开“管理词库与学习历史”。
5. 填写词库名称并选择 `stardict.csv`。
6. 选择考试范围及组合方式。
7. 点击“创建并设为当前词库”。
8. 打开“学习与 AI 设置”，填写 AI 接口信息。
9. 返回主界面开始一轮学习。

## 词库选择逻辑

### 允许的考试范围

| tag | 中文名称 | 默认难度系数 |
|---|---|---:|
| `zk` | 中考 | 0.15 |
| `gk` | 高考 | 0.25 |
| `cet4` | 大学英语四级 | 0.35 |
| `cet6` | 大学英语六级 | 0.50 |
| `ky` | 考研英语 | 0.50 |
| `ielts` | 雅思 | 0.65 |
| `toefl` | 托福 | 0.65 |
| `gre` | GRE | 0.85 |

为了与服务端保持一致，界面创建词库时只允许以上 8 个范围。自定义旧词库仍可继续使用。

### 任一范围与全部范围

- **包含任一所选范围（any）**：单词拥有任一所选 tag 即进入词库。
- **同时属于全部所选范围（all）**：单词必须拥有全部所选 tag 才进入词库。

ECDICT 可能存在大小写不同或重复的同一单词。VITAL 会先按单词的大小写无关键合并其所有 tag，再判断 any/all，行为与服务端导入后的数据库查询一致。输出时：

- 每个单词只保留一条；
- 非 tag 字段采用源文件中最后一条同名单词记录；
- `tag` 字段保存该单词全部已合并 tag；
- 输出使用 UTF-8 with BOM，便于 Excel 和旧版 VITAL 读取。

### 多词库保存与切换

创建词库后，VITAL 会：

- 将不可变快照保存到 `vocabularies/<词库ID>.csv`；
- 将当前词库同步到旧版固定路径 `vocabulary.csv`；
- 切换前将原当前词库备份为 `vocabulary.previous.csv`；
- 在 `vocabularies.json` 保存名称、tag、组合方式、词数、创建时间和当前状态。

已有学习会话引用的词库不能删除，这与服务端的数据完整性规则一致；可以保留它并切换到其他词库。

也可直接使用命令行生成单个 CSV：

```bash
python retrieve.py --input stardict.csv --output vocabulary.csv --tags "gre ielts"
```

要求同时拥有全部范围：

```bash
python retrieve.py --input stardict.csv --output vocabulary.csv --tags "gre ielts" --match-all
```

## 每轮抽词逻辑：VITAL Ranker v0.2.1

### 1. 绝对新词定义

- 单词在学习历史中完全不存在，或明确没有完成学习次数：`unseen`，即绝对新词。
- 熟练度为 1 但已经学习过：仍然是复习词，通常归入 `weak`，不会占用新词名额。

这是本版本与旧桌面版最重要的行为变化。旧桌面版曾把熟练度 1 优先当作新词；该规则已经移除。

### 2. 新词名额

默认每轮 20 词、绝对新词基准 3 词，与服务端默认值一致。

- **fixed**：使用设置中的新词基准数。
- **adaptive**：在至少积累 3 个已完成会话后，根据典型学习间隔、当前间隔和近期跨会话保持率调整新词数。

自适应模式会在长时间未学习或近期保持率偏低时减少新词，在节奏稳定且保持率较好时适度增加；最终仍受本轮总词数和最大新词比例约束。

旧 `config.json` 若仍是旧版精确默认值 `20/10`，首次读取时自动迁移为 `20/3`；用户自行设置的其他数值保持不变。

### 3. 复习词分类

已学习词会根据最近两次评分、学习次数、距上次学习时间、历史事件和预测记忆状态分为：

- `weak`：低分、第一次评分为 1，或预测记忆很弱；
- `stuck`：最近多次学习增益持续偏低且第二次评分仍低；
- `due_review`：已经开始遗忘，适合现在复习；
- `maintenance`：记忆状态较好，但需要维护。

### 4. 复习词排序

复习优先级综合：

- **遗忘风险**：依据上次第二次评分对应的半衰期和距上次学习天数预测；
- **历史学习增益**：比较每次文章学习前后的两次评分；
- **理想难度**：优先选择“有一定遗忘但仍适合重新激活”的词；
- **估计不确定性**：学习次数少的词会获得适度探索机会；
- **重要性**：综合 ECDICT 频率/词频、Collins、词义数、考试 tag 数；
- **惩罚项**：近期评分下降和长期卡住会降低连续重复安排的概率。

评分不是简单按熟练度排序，也不再使用旧版 `20:10:5:1` 候选池。

### 5. 新词排序

绝对新词综合：

- 词频与重要性；
- 单词长度、词义数量、考试范围默认难度形成的难度估计；
- 与当前学习能力的难度匹配；
- 与已掌握词的词形家族或考试范围联系形成的知识脚手架；
- 尚未充分掌握的考试范围覆盖缺口；
- 同时属于多个考试范围时的通用性加成。

### 6. 配额、探索与多样性

在总词数与新词名额确定后：

- 薄弱复习目标约为总词数的 25%；
- 维护复习目标约为总词数的 10%；
- 其余复习名额主要分配给到期复习；
- 卡住词和高难新词有单轮上限，避免一轮过于挫败；
- 默认约 10% 的位置执行概率探索，其余位置以最高综合价值为主；
- 使用类似 MMR 的多样性约束，减少连续选择同一词形家族或高度重合 tag 的词；
- 高分词在 12 小时内进入冷却，除非库存不足需要回填。

若某一类别库存不足，系统按服务端相同的回填优先级从其他类别补足；新用户没有复习词时，剩余位置会全部用绝对新词填满。

### 7. 第二轮顺序

第一轮评分后，第二轮不会简单复用原顺序。词数大于 1 时，系统生成一个**错位排列**：每个词在第二轮的位置都不同于第一轮，从而降低依赖顺序记忆的影响。

### 8. 推荐审计

每次开始学习时，系统向 `selectionAudit.jsonl` 追加一条 JSON 记录，包括：

- 策略版本与当轮参数；
- 请求配额、实际类别数量、自适应计算结果；
- 每个词的类别、推荐分数、探索/利用/回填来源；
- 选择概率、特征、推荐原因；
- 第一轮和第二轮顺序。

审计写入失败不会阻止正常学习。

## 学习流程

1. 第一轮词义自评。
2. 查看完整 ECDICT 词条后再次评分。
3. AI 使用本轮全部目标词生成英文文章。
4. 阅读完成后统计文章词数与阅读时间。
5. AI 生成简体中文译文。
6. 第二轮以错位顺序再次进行完整词义学习。
7. 计算最终熟练程度并一次性写入学习历史。

用户中途关闭任一学习窗口时，本轮不写入学习历史。

### 最终熟练程度

```text
floor((第一次词义学习结果 + 2 × 第二次词义学习结果) / 3)
```

结果限制在 1～5。第二轮权重更高，用于反映文章学习后的状态。

### 动态文章长度

```text
文章目标词数 = 180 + 35 × 绝对新词数 + 18 × 复习词数
```

例如，一轮包含 3 个绝对新词和 17 个复习词时，目标长度约为 591 个英文词。AI 最多生成两次；若第一次缺少某些目标词的原形，会把缺失列表反馈给模型并重写整篇文章。

## 快捷键与界面

### 词义学习

- 主键盘 `1`～`5`：选择评分；
- 小键盘 `1`～`5`：选择评分；
- 空格：执行当前“查看词义 / 下一词 / 完成”主按钮；
- 第一次确认后显示 CSV 中的全部词条字段；
- 顶部显示当前轮次与进度。

### 文章学习

- “我已读完”按钮固定在底部操作栏，不会被文章内容挤出窗口；
- 空格：执行当前可用的主要按钮；
- 生成文章或译文失败后可直接重试；
- 英文文章与中文译文可分别滚动；
- 状态栏显示文章生成、计时和翻译状态。

### 词库与历史管理

- 词库生成在后台线程执行，界面不会在扫描大型 ECDICT 时完全卡死；
- 词库列表显示名称、词数、中文考试范围、组合方式和当前状态；
- 学习历史支持单词搜索和熟练度 1～5 筛选；
- 可查看学习次数、最近两次评分和最近学习时间；
- 清空历史会同时清空汇总文件和详细事件文件。

## AI 接口

程序调用 OpenAI-compatible Chat Completions API，使用标准库 `urllib`：

- `BASE_URL` 若填写到 `/v1`，程序自动追加 `/chat/completions`；
- 也可填写完整的 `/chat/completions` 地址；
- 请求体包含 `model`、`messages`、`temperature`；
- 若设置了 API Key，则使用 `Authorization: Bearer ...`；
- 单次请求超时为 120 秒。

开始学习前必须填写：

- `API_KEY`
- `BASE_URL`
- `MODEL`
- AI 写作提示词

## 数据文件

### 项目代码

- `main.py`：主界面、品牌信息和程序入口；
- `config_manager.py`：设置、旧配置迁移与界面字体；
- `vocabulary_tags.py`：网页版一致的 tag 白名单、中文名称和默认难度；
- `retrieve.py`：按 tag 从 ECDICT 生成词库；
- `vocabulary_store.py`：命名词库、快照、切换、备份与删除保护；
- `vital_ranker.py`：VITAL Ranker v0.2.1 的标准库桌面适配；
- `learning_history.py`：旧历史兼容、扩展汇总与详细事件日志；
- `learning_flow.py`：完整学习流程、推荐审计与最终写入；
- `word_study.py`：两阶段词义评分；
- `article_study.py`：文章、计时、目标词检查、翻译与重试；
- `tests/test_core.py`：核心兼容与算法回归测试。

### 运行时生成或维护

- `config.json`：设置；
- `vocabulary.csv`：当前词库的旧版兼容副本；
- `vocabulary.previous.csv`：最近一次切换前的词库备份；
- `vocabularies.json`：词库注册表；
- `vocabularies/*.csv`：命名词库快照；
- `learningHistory.csv`：每个单词的当前汇总状态；
- `learningEvents.csv`：每次已完成会话的逐词详细记录；
- `selectionAudit.jsonl`：推荐决策审计日志。

## 旧版本兼容

### `vocabulary.csv`

若升级前只有旧版 `vocabulary.csv`：

- 首次启动自动登记为“旧版当前词库”；
- 原文件继续保留并作为当前词库使用；
- 同时创建一份词库快照；
- 旧版本仍可读取固定路径 `vocabulary.csv`。

### `learningHistory.csv`

旧版两列格式可直接读取：

```csv
单词,熟练程度
example,3
```

首次完成新会话后，文件自动升级为扩展格式。旧记录缺少时间信息时，使用旧文件最后修改时间作为兼容估计；旧熟练度会保留，不会被当作未学习。

若新版本已生成 `learningEvents.csv`，详细事件日志是更可靠的数据来源；即使旧桌面版之后把 `learningHistory.csv` 再次写回两列格式，新版本仍会用事件日志修复汇总信息。

### `config.json`

- 缺失的新字段自动补默认值；
- 无效颜色或数值回退到安全默认；
- 旧的固定 300 词默认提示词自动迁移到动态长度提示词；
- 精确旧默认 `20/10` 迁移到 `20/3`；
- 其他用户自定义学习数量保留。

## 测试

运行：

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

当前回归测试覆盖：

- 旧配置迁移及自定义值保留；
- 异常配置容错；
- any/all tag 与重复词 tag 合并；
- tag 白名单；
- 旧两列学习历史；
- 熟练度 1 与绝对新词分离；
- 新用户回填；
- 自适应新词配额；
- 第二轮错位顺序；
- 动态文章长度；
- 旧词库自动登记；
- 命名词库切换与学习记录删除保护；
- 无第三方 Python 导入；
- 无 `.bat` / `.ps1` 文件。

## License

Copyright © 2026 ZhuinZ. All Rights Reserved. 详见 `LICENSE`。

---

## English Summary

VITAL Desktop v1.4.2 is a standard-library-only Tkinter vocabulary trainer aligned with the server-side VITAL Ranker v0.2.1. It provides named vocabulary profiles, server-equivalent any/all ECDICT tag matching, a strict unseen-word definition, fixed or adaptive unseen quotas, forgetting-aware review ranking, diversity-aware selection, deranged second-pass ordering, dynamic article length, detailed learning events, recommendation audits, and backward compatibility with legacy desktop CSV/JSON files.

Run it with:

```bash
python main.py
```
