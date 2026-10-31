"""Markdown review sheet for a pipeline result."""


def _quote(evidence: list[str]) -> str:
    return f"“{evidence[0]}”" if evidence else ""


def to_markdown(result: dict) -> str:
    if result.get("meta", {}).get("kernel") == "direct-tbox":
        return tbox_markdown(result)
    meta = dict(result["meta"])
    cost = meta.get("cost_usd_estimate")
    cost_text = f"estimated cost ${cost:.2f}" if cost is not None else "subscription; cash cost not estimated"
    out = [f"# Ontology candidates: {meta.get('source', '')}", "",
           f"Model `{meta['model']}` (effort {meta['effort']}), "
           f"{meta['config']['samples']} samples per stage, min support "
           f"{meta['config']['min_support']:.0%}, {cost_text}.",
           "", "## Classes", "", "| Class | Support | Definition | Evidence |", "|---|---|---|---|"]
    for c in result["classes"]:
        if c.get("given"):
            out.append(f"| {c['name']} | given | | |")
            continue
        aliases = f" (aka {', '.join(c['aliases'])})" if c["aliases"] else ""
        out.append(f"| **{c['name']}**{aliases} | {c['support']:.0%} | {c['definition']} "
                   f"| {_quote(c['evidence'])} |")

    if result["attributes"]:
        out += ["", "## Attributes", "", "| Class | Attribute | Type | Support | Evidence |",
                "|---|---|---|---|---|"]
        out += [f"| {a['class']} | {a['name']} | {a['datatype']} | {a['support']:.0%} "
                f"| {_quote(a['evidence'])} |" for a in result["attributes"]]

    out += ["", "## Relations", "", "| Source | Relation | Target | Kind | Multiplicity | Support "
            "| Evidence |", "|---|---|---|---|---|---|---|"]
    out += [f"| {r['source']} | {r['name']} | {r['target']} | {r['kind']} "
            f"| {r['source_multiplicity']} : {r['target_multiplicity']} | {r['support']:.0%} "
            f"| {_quote(r['evidence'])} |" for r in result["relations"]]

    rejected = result["rejected"]
    if rejected["classes"] or rejected["relations"]:
        out += ["", "## Rejected candidates", "",
                "Kept for review: rejected by the verifier, below the support threshold, or "
                "without evidence found in the document.", "",
                "| Candidate | Support | Grounded | Verdict | Reason |", "|---|---|---|---|---|"]
        for c in rejected["classes"]:
            v = c["verdict"]
            out.append(f"| class: {c['name']} | {c['support']:.0%} | {c['grounded']} "
                       f"| {v['decision']} / {v['category']} | {v['reason']} |")
        for r in rejected["relations"]:
            v = r["verdict"]
            out.append(f"| {r['source']} – {r['target']} | {r['support']:.0%} | {r['grounded']} "
                       f"| {v['decision']} / {v['category']} | {v['reason']} |")
    return "\n".join(out) + "\n"


def _cell(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace("|", "&#124;").replace("\n", "<br>")


def tbox_markdown(result):
    import json
    m = result['meta']
    out = [f"# Ontology candidates: {_cell(m.get('source', ''))}", "",
           f"模型 `{m['model']}` · direct-TBox · 单次提案 · 待人工审核", "",
           "引文已按原文精确匹配；这不等于公理已被证明。未估计置信度，未执行语义推理验证。",
           "Codex 使用现有登录；金额不作估算。", "",
           f"源文本 SHA-256: `{m['source_sha256']}`", "",
           "原有审核栏目保留；以下每条完整候选均提供适用范围、条件及引文位置。", ""]
    for title, key in [('Classes', 'classes'), ('Attributes', 'attributes'), ('Relations', 'relations')]:
        out += [f"## {title}", "", "| ID | 候选 | 定义 / 类型 | Evidence |", "|---|---|---|---|"]
        for v in result[key]:
            name = v.get('name', '')
            if key == 'relations':
                name = f"{v['source']} → {name} → {v['target']}"
            out.append('| ' + ' | '.join(_cell(x) for x in [v['candidate_id'], name,
                       v.get('datatype', v.get('definition', '')), ' / '.join(v['evidence'])]) + ' |')
    out += ['', '## 完整 TBox 候选与审核', '',
            '勾选表示人工接受；所有候选初始均为待审核。statement 保留为待形式化规则，不伪装为可执行公理。', '']
    for item in result['items']:
        e = json.dumps(item['expression'], ensure_ascii=False, sort_keys=True)
        out += [f"- [ ] **{item['candidate_id']} {_cell(item['label'])}**", '',
                f"  `{e.replace('`', 'ˋ')}`", '',
                f"  定义：{_cell(item['definition'])}", '',
                f"  适用范围：{_cell(item['scope']) or '原文一般表述'}；条件：{_cell('；'.join(item['conditions'])) or '无附加条件'}", '']
        for span in item['evidence_spans']:
            out += [f"  引文 [{span['start']}, {span['end']})：{_cell(span['quote'])}", '']
    out += ['## Rejected candidates', '', '未通过结构、引用或证据检查的原始提案仍保存在 JSON 中，供人工复查。', '']
    for item in result['rejected']['items']:
        out.append(f"- {item['candidate_id']} {_cell(item.get('label', ''))}：{_cell(item['rejection_reason'])}")
    return '\n'.join(out) + '\n'
