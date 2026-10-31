"""Self-contained local review page. No network calls; source is rendered as text."""
import json
import hashlib


def to_html(result, document):
    review_id = hashlib.sha256(json.dumps(result.get('items', []), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    data = json.dumps({'result': result, 'document': document, 'review_id': review_id}, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026')
    return TEMPLATE.replace('__ONTOEXTRACT_DATA__', data)


TEMPLATE = '''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OntoExtract · 候选审核</title>
<style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#183233;background:#f3f6f5}*{box-sizing:border-box}body{margin:0}header{background:#153f3b;color:white;padding:24px 4vw}h1{margin:0 0 10px;font-size:26px}p{line-height:1.7;margin:8px 0}button,select{font:inherit;border:1px solid #b4ccc6;border-radius:7px;padding:8px 12px;background:white;color:#183233;cursor:pointer}button{margin:6px 8px 6px 0}.toolbar{padding:12px 4vw;background:#e5efeb;position:sticky;top:0;z-index:1}main{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:20px;padding:20px 4vw}article,aside{border:1px solid #d1e0da;border-radius:12px;background:white;padding:20px;margin-bottom:16px}aside{position:sticky;top:125px;max-height:75vh;overflow:auto;align-self:start}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace;background:#f0f5f3;padding:12px;border-radius:6px}blockquote{margin:12px 0;padding:10px 14px;border-left:3px solid #369280;background:#eff8f4;white-space:pre-wrap}small{color:#53716c}h2{font-size:18px;margin:0 0 10px}.chips{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.accepted{border-left:5px solid #16816b}.rejected{border-left:5px solid #bd5f45}mark{background:#ffe7a1}#source{font:14px/1.9 system-ui;background:white}.warning{color:#6e4a18;background:#fff6dc;padding:12px;border-radius:6px}@media(max-width:850px){main{display:block}aside{position:static;max-height:none}.toolbar{position:static}}
</style>
<header><h1>OntoExtract · 候选审核</h1><p id="summary"></p><p>每条候选都需人工判断。引文存在不代表结论正确；本页不声称完成本体一致性验证。</p></header>
<div class="toolbar"><label>查看 <select id="filter"><option value="all">全部候选</option><option value="pending">待审核</option><option value="accepted">已接受</option><option value="rejected">已退回</option><option value="statement">待形式化规则</option></select></label><button id="download">导出审核结果</button><button id="clear">清除本篇审核标记</button><span id="counts"></span></div>
<main><section id="candidates"></section><aside><h2>原文与证据</h2><small>点击候选中的“定位引文”可在此查看上下文。位置以源文本字符 [起点, 终点) 记录。</small><pre id="source"></pre></aside></main>
<script id="data" type="application/json">__ONTOEXTRACT_DATA__</script>
<script>
const data=JSON.parse(document.getElementById('data').textContent),r=data.result,doc=data.document;
const key='ontoextract-review:'+r.meta.source_sha256+':'+data.review_id;
let decisions={},storageProblem=false;try{decisions=JSON.parse(localStorage.getItem(key)||'{}')}catch(e){storageProblem=true}
const items=r.items||[],$=id=>document.getElementById(id),node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e};
$('summary').textContent=(r.meta.source||'文档')+' · '+r.meta.model+' · '+items.length+' 条候选';
$('source').textContent=doc;
function status(i){const value=decisions[i.candidate_id];return ['pending','accepted','rejected'].includes(value)?value:'pending'}
function locate(span){const s=$('source'),chars=Array.from(doc);s.replaceChildren(document.createTextNode(chars.slice(0,span.start).join('')),node('mark',chars.slice(span.start,span.end).join('')),document.createTextNode(chars.slice(span.end).join('')));s.querySelector('mark').scrollIntoView({block:'center',behavior:'smooth'})}
function save(){try{localStorage.setItem(key,JSON.stringify(decisions))}catch(e){storageProblem=true}}
function draw(){const container=$('candidates');container.replaceChildren();const f=$('filter').value;
 for(const i of items){const st=status(i),expr=i.expression||{};if(f!=='all'&&!(f==='statement'?expr.op==='statement':f===st))continue;
 const a=node('article');a.className=st;const top=node('div');top.className='chips';top.append(node('h2',i.candidate_id+' · '+i.label));const select=node('select');select.setAttribute('aria-label','审核 '+i.label);for(const [val,label] of [['pending','待审核'],['accepted','接受'],['rejected','退回']]){const o=node('option',label);o.value=val;select.append(o)}select.value=st;select.onchange=()=>{decisions[i.candidate_id]=select.value;save();draw()};top.append(select);a.append(top);
 a.append(node('p',i.definition||''),node('pre',JSON.stringify(expr,null,2)),node('p','适用范围：'+(i.scope||'原文一般表述')),node('p','条件：'+((i.conditions||[]).join('；')||'无附加条件')));
 if(expr.op==='statement'){const note=node('p','此条保留为待形式化规则。');note.className='warning';a.append(note)}
 for(const span of i.evidence_spans||[]){a.append(node('blockquote',span.quote));const b=node('button','定位引文 ['+span.start+', '+span.end+')');b.onclick=()=>locate(span);a.append(b)}container.append(a)}
 const counts={pending:0,accepted:0,rejected:0};items.forEach(i=>counts[status(i)]++);$('counts').textContent='待审核 '+counts.pending+' · 接受 '+counts.accepted+' · 退回 '+counts.rejected+(storageProblem?'（浏览器未允许保存，请导出）':'');
 const rejected=r.rejected?.items||[];if(rejected.length){const a=node('article');a.append(node('h2','未通过自动检查的提案'));for(const i of rejected)a.append(node('p',i.candidate_id+' '+(i.label||'')+'：'+i.rejection_reason));container.append(a)}}
$('filter').onchange=draw;$('clear').onclick=()=>{if(confirm('清除本篇文档的全部审核标记？')){decisions={};save();draw()}};
$('download').onclick=()=>{const exported=JSON.parse(JSON.stringify(r));for(const field of ['items','classes','attributes','relations','axioms','hierarchies','pending_constraints'])(exported[field]||[]).forEach(i=>i.review_status=status(i));exported.meta.review_status='human_review_recorded';exported.meta.reviewed_at=new Date().toISOString();exported.meta.review_note='仅记录用户选择；未执行语义推理验证。';const b=new Blob([JSON.stringify(exported,null,2)],{type:'application/json'}),url=URL.createObjectURL(b),a=node('a');a.href=url;a.download=(r.meta.source||'ontology')+'-reviewed.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
draw();
</script></html>'''
