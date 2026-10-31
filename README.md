# OntoExtract · direct-TBox 升级版

默认用本机已登录的 Codex（gpt-6.1-sol / high），从文档直接提出类、属性、有向关系、层级和约束。文件读取、原文证据和 Markdown 审核表保留，新增可离线打开的浏览器审核页。

## 日常使用

在项目目录使用其 Python 环境：

```sh
.venv/bin/python -m ontoextract 文档.pdf -o output
```

也支持 `.txt`、`.md`、`.docx`；PDF 使用文本层，DOCX 读取段落。多文件可用 `--combine` 合并；不加则分别抽取。

每份文档输出：

- `文档.json`：完整候选、原始模型返回、约束适用条件、引文位置、来源摘要、未通过检查的提案。
- `文档.md`：保留 Classes / Attributes / Relations 原有审核栏目，并列出全部约束与审核勾选框。
- `文档.review.html`：双击打开，逐条接受/退回、定位原文、筛选待形式化规则、导出带审核状态的 JSON。审核选择存于本地浏览器；请导出结果长期保存。

可通过 `--model`、`--effort` 调整 Codex 调用。`--backend auto` 同样选择 Codex。Codex CLI 需要已有有效登录；本版核验的 CLI 为 0.166.0。每条请求失败会明确报错，无自动切换到其他后端。

## 抽取与审核规则

默认每文档一次提案，不做多次投票或模型自我校验。确定性检查包括：表达式类型白名单、所有引文原文精确匹配、类/属性引用存在、重复候选按条件分别保留、冲突标识拒绝。所有保留项初始均为 `pending`，没有把单次出现标成 100% 置信度。

数量约束保留主体类、属性、目标类型、最小/最大/恰好值及语义；单位单列为注释。复杂规则、版本限定、正则、否定与条件保留在 `statement`、`scope` 和 `conditions` 中，等待人工形式化。方向不会按名称重新排序。

引文位置为原文提取文本的 Python Unicode 字符偏移 `[start,end)`，不是 PDF 页坐标。来源 SHA-256 基于提取后的 UTF-8 文本；合并文件的位置对应含文件名标题的合并文本。

这些检查证明可回溯性和结构有效性，不能替代语义判断，也不声称 OWL 一致性、全部语义正确或生产验收。JSON 是本体候选，不自动发布为正式 OWL/SHACL。

## 旧内核对照

保留原类图分阶段抽取算法和提示，可显式运行：

```sh
.venv/bin/python -m ontoextract 文档.md --kernel legacy --samples 1 --no-verify -o old-output
```

`--kernel legacy` 未另设参数时使用原五次采样和模型校验。默认 direct-TBox 只接受 `--samples 1`；原投票/校验参数仅用于 legacy。历史基准脚本已显式固定到 legacy，避免无意改测新算法。

## 安装与检查

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q tests
```

本次 18 份文档的同模型验证见 [升级验证说明](docs/validation-2026-10-31.md)。旧 Claude API / Claude Code 后端为显式选项保留；本轮实测全部使用 Codex。

Codex 接入依据：[OpenAI Docs：非交互运行与结构化输出](https://learn.chatgpt.com/docs/non-interactive-mode)。本机 CLI 参数已按安装版本核验。

第三方基准材料的来源、版本和许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
