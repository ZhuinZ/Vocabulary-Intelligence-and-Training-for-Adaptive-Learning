# AI 辅助英文单词学习系统

这是一个基于 Python 标准库和 Tkinter 的桌面词汇学习程序。

## 文件结构

- `config_manager.py`：创建、读取和编辑 `config.json`
- `learning_flow.py`：抽词、流程调度、历史记录读写与最终评分
- `word_study.py`：两阶段词义自评、快捷键与完整词条信息展示
- `article_study.py`：AI 英文文章生成、阅读计时、词数统计和中文翻译
- `retrieve.py`：从 ECDICT 的 `stardict.csv` 按一个或多个 tag 生成词库
- `vocabulary_manager.py`：词库切换和学习历史管理界面
- `main.py`：主界面和程序入口
- `vocabulary.csv`：当前使用的词库
- `learningHistory.csv`：学习历史，首次学习时自动创建
- `config.json`：配置文件，首次启动时自动创建

## 首次运行

运行：

```bash
python main.py
```

首次启动会弹出词库获取说明。程序使用 ECDICT：

https://github.com/skywind3000/ECDICT

操作步骤：

1. 打开 ECDICT GitHub 项目。
2. 下载项目中的 `stardict.7z`，或下载整个项目后找到该文件。
3. 使用 7-Zip 等工具解压，取得 `stardict.csv`。
4. 回到主界面，打开“管理词库和学习历史”。
5. 选择 `stardict.csv`。
6. 输入一个或多个 tag，例如 `gre`、`cet6`、`ielts toefl`。
7. 点击“按标签生成并切换词库”。

主界面右下角的“点我下载词库”会再次显示说明并打开 ECDICT 项目。

## 词库管理

“管理词库和学习历史”页面支持：

- 按单个 tag 生成词库，例如 `gre`
- 按多个 tag 生成词库，支持空格、逗号和分号分隔
- “匹配任意一个 tag”：词条具有任一输入 tag 即可导出
- “必须同时具有全部 tag”：词条必须同时具有全部输入 tag
- 自动去除重复单词
- 自动排除源 CSV 中的 `tag` 列，保留其他词条字段
- 切换前把当前 `vocabulary.csv` 备份为 `vocabulary.previous.csv`
- 单独删除全部 `learningHistory.csv` 学习记录

也可以直接在控制台使用：

```bash
python retrieve.py --input stardict.csv --output vocabulary.csv --tags "gre ielts"
```

要求同时具有全部 tag：

```bash
python retrieve.py --input stardict.csv --output vocabulary.csv --tags "gre ielts" --match-all
```

## 设置

首次学习前请打开“设置”，完整填写：

- `API_KEY`
- `BASE_URL`
- `MODEL`
- AI 写作提示词

程序会在开始学习前检查这些项目。

## AI 接口格式

程序调用 OpenAI-compatible Chat Completions 接口：

- `BASE_URL` 填写到 `/v1` 时，程序自动追加 `/chat/completions`
- 也可以直接填写以 `/chat/completions` 结尾的完整地址
- 请求体使用 `model`、`messages`、`temperature`
- 程序发送 `Authorization: Bearer ...`

## 每轮抽词规则

- 新学习词名额优先选择 `learningHistory.csv` 中熟练程度为 1 的词。
- 仍有空缺时，再选择从未出现在学习历史中的词。
- 复习词先按照熟练程度 2、3、4、5，以 `20:10:5:1` 的数量比例建立候选池。
- 再从候选池中等概率、不重复地抽取所需复习词。
- 某些熟练度库存不足时，会继续按同一比例从剩余词中补充候选池。
- 复习词仍不足时，继续使用历史 1 级词和未学习词补足。

## 界面和快捷键

词义学习阶段：

- 数字键 `1`～`5`：选择熟练程度
- 小键盘 `1`～`5`：选择熟练程度
- 空格：按下当前“我已评分”主按钮
- 第一次评分后展示完整词条信息
- 第二次评分后立即进入下一个单词

文章学习阶段：

- “我已读完（空格）”固定显示在窗口底部，不会被文章区域挤出窗口
- 空格：按下当前主要按钮，包括“我已读完”“完成并继续”和失败后的重试按钮
- 点击“我已读完”后统计文章词数和阅读时间，然后生成中文译文

## 最终评分

同一单词在文章学习前、后各进行一次完整的词义学习。最终熟练程度为：

```text
floor((第一次结果 + 2 × 第二次结果) / 3)
```

结果限制在 1 至 5，并写入 `learningHistory.csv`。

## 环境

只使用 Python 标准库，无需安装额外依赖。推荐 Python 3.12。Windows 的标准 Python/Conda 环境通常带有 Tkinter；部分 Linux 发行版可能需要单独安装 `python3-tk`。



# AI-Powered English Vocabulary Learning System

This is a desktop vocabulary learning application built with Python's standard library and Tkinter.

## Project Structure

* `config_manager.py` – Creates, loads, and edits `config.json`
* `learning_flow.py` – Handles word selection, learning workflow, learning history, and final proficiency calculation
* `word_study.py` – Two-stage vocabulary self-assessment, keyboard shortcuts, and full dictionary entry display
* `article_study.py` – AI-generated English articles, reading timer, word count, and Chinese translation
* `retrieve.py` – Generates vocabulary lists from ECDICT's `stardict.csv` using one or more tags
* `vocabulary_manager.py` – Vocabulary management and learning history interface
* `main.py` – Main window and application entry point
* `vocabulary.csv` – The currently selected vocabulary list
* `learningHistory.csv` – Learning history (created automatically on first use)
* `config.json` – Configuration file (created automatically on first launch)

## First Launch

Run:

```bash
python main.py
```

When the program is launched for the first time, it will display instructions for obtaining the vocabulary database. The application uses **ECDICT**:

https://github.com/skywind3000/ECDICT

Steps:

1. Open the ECDICT GitHub repository.
2. Download `stardict.7z`, or download the entire repository and locate the file.
3. Extract it with 7-Zip or another archive tool to obtain `stardict.csv`.
4. Return to the application and open **Manage Vocabulary & Learning History**.
5. Select `stardict.csv`.
6. Enter one or more tags, such as `gre`, `cet6`, or `ielts toefl`.
7. Click **Generate and Switch Vocabulary by Tags**.

The **Download Vocabulary Database** button in the lower-right corner of the main window will reopen the instructions and open the ECDICT repository.

## Vocabulary Management

The **Manage Vocabulary & Learning History** page supports:

* Generating a vocabulary list from a single tag (e.g. `gre`)
* Generating a vocabulary list from multiple tags separated by spaces, commas, or semicolons
* **Match Any Tag**: export entries containing at least one specified tag
* **Match All Tags**: export only entries containing every specified tag
* Automatic removal of duplicate words
* Automatic exclusion of the `tag` column while preserving all other dictionary fields
* Automatic backup of the current `vocabulary.csv` as `vocabulary.previous.csv` before switching
* Deleting the entire `learningHistory.csv` independently

You can also use the command line directly:

```bash
python retrieve.py --input stardict.csv --output vocabulary.csv --tags "gre ielts"
```

Require all specified tags:

```bash
python retrieve.py --input stardict.csv --output vocabulary.csv --tags "gre ielts" --match-all
```

## Settings

Before starting your first learning session, open **Settings** and complete the following fields:

* `API_KEY`
* `BASE_URL`
* `MODEL`
* AI writing prompt

The application validates these settings before each learning session.

## AI API Format

The application uses an OpenAI-compatible Chat Completions API.

* If `BASE_URL` ends with `/v1`, the program automatically appends `/chat/completions`.
* You may also enter the complete endpoint ending with `/chat/completions`.
* Requests use the `model`, `messages`, and `temperature` fields.
* Authentication is sent via `Authorization: Bearer ...`.

## Word Selection Strategy

* New-word slots are first filled with words whose proficiency level is **1** in `learningHistory.csv`.
* Remaining slots are filled with words that have never appeared in the learning history.
* Review candidates are collected from proficiency levels **2**, **3**, **4**, and **5** using a **20:10:5:1** weighting.
* Review words are then sampled uniformly at random from the candidate pool without duplication.
* If some proficiency levels do not contain enough words, the candidate pool is supplemented proportionally from the remaining levels.
* If there are still not enough review words, proficiency level 1 words and unseen words are used to fill the remaining slots.

## User Interface & Keyboard Shortcuts

### Vocabulary Study

* Number keys `1`–`5`: select proficiency level
* Numpad `1`–`5`: select proficiency level
* Space: press the current **I've Rated It** button
* The complete dictionary entry is displayed after the first rating
* After the second rating, the program immediately proceeds to the next word

### Article Study

* The **I've Finished Reading (Space)** button is permanently displayed at the bottom of the window and will never be pushed out by the article content.
* Space: activates the current primary button, including **I've Finished Reading**, **Finish and Continue**, and the retry button after a failed generation.
* After clicking **I've Finished Reading**, the application calculates the article's word count and reading time, then generates a Chinese translation.

## Final Proficiency Score

Each word is assessed twice: once before the article-reading stage and once afterward.

The final proficiency level is calculated as:

```text
floor((First Rating + 2 × Second Rating) / 3)
```

The result is clamped to the range **1–5** and written to `learningHistory.csv`.

## Environment

The application uses only Python's standard library and requires no additional dependencies.

Python **3.12** is recommended. Tkinter is included in standard Python and Conda installations on Windows. On some Linux distributions, you may need to install `python3-tk` separately.
