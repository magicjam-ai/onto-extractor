import copy
import json
from collections import Counter
from pathlib import Path
import subprocess
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ontoextract import Config, Pipeline
from ontoextract.llm import CodexLLM, LLMError, make_llm
from ontoextract.report import to_markdown
from ontoextract.tbox import normalize

DOC='温控舱是试验舱。温控舱至少测量两个物理量。温度单位为摄氏度。仅在模式 A 中适用。'
class Fake:
 model,effort='fake','high'
 def __init__(self,items=()):self.items=list(items);self.usage=Counter()
 def cost_usd(self):return None
 def json_call(self,*args):self.usage['requests']+=1;return {'items':self.items}
def item(e,quote='温控舱是试验舱。',**kw):
 return dict(label=e.get('id',e['op']),definition='source-derived proposal',expression=e,scope='',conditions=[],quotes=[quote],**kw)
def declarations():
 return [item({'op':'Class','id':s}) for s in ['温控舱','试验舱','物理量']] + [item({'op':'ObjectProperty','id':'测量'})]
def result(items):return normalize(DOC,{'items':items},Fake(),Config())
def test_one_call_default_and_direction():
 items=declarations()+[item({'op':'subClassOf','child':'温控舱','parent':'试验舱'}),item({'op':'domain','property':'测量','class':'温控舱'}),item({'op':'range','property':'测量','class':'物理量'})]
 llm=Fake(items);r=Pipeline(DOC,llm).run()
 rel=next(v for v in r['relations'] if v['name']=='测量')
 assert (rel['source'],rel['target'])==('温控舱','物理量')
 assert llm.usage['requests']==1 and r['meta']['cost_usd_estimate'] is None
 assert all(v['support'] is None for v in r['items'])
 assert r['meta']['review_status']=='pending'
def test_qualified_cardinality_scope_evidence_and_no_broadening():
 i=item({'op':'minCardinality','class':'温控舱','property':'测量','value':2,'on_class':'物理量','semantics':'document-validation'},'温控舱至少测量两个物理量。')
 i['scope']='模式 A';i['conditions']=['仅在模式 A 中适用。']
 r=result(declarations()+[i]);v=r['axioms'][0]
 assert v['expression']['class']=='温控舱' and v['expression']['value']==2
 assert v['conditions']==i['conditions'] and v['scope']==i['scope']
 for span in v['evidence_spans']:assert DOC[span['start']:span['end']]==span['quote']
def test_bad_quotes_dangling_and_malformed_retained():
 bad=item({'op':'Class','id':'missing'},'invented quote')
 dangling=item({'op':'subClassOf','child':'missing','parent':'试验舱'})
 negative=item({'op':'exactCardinality','class':'温控舱','property':'测量','value':-1,'on_class':None,'semantics':'document-validation'})
 r=result(declarations()+[bad,dangling,negative,{'malformed':True}])
 assert len(r['rejected']['items'])==4
 assert r['raw_output']['items'][-1]=={'malformed':True}
 assert not any(v['expression'].get('id')=='missing' for v in r['items'])
def test_dedup_preserves_context_and_conflicts_fail_closed():
 a=item({'op':'subClassOf','child':'温控舱','parent':'试验舱'})
 b=copy.deepcopy(a);b['conditions']=['条件A']
 r=result(declarations()+[a,copy.deepcopy(a),b])
 assert len(r['hierarchies'])==2
 conflict=item({'op':'ObjectProperty','id':'温控舱'})
 r=result(declarations()+[conflict,a])
 assert len(r['rejected']['items'])==3  # both declarations + dependent hierarchy
 assert '温控舱' not in [v['id'] for v in r['classes']]
def test_pending_statement_and_review_escaping():
 a=item({'op':'statement','text':'key | value < limit'},'温度单位为摄氏度。');a['label']='key | value'
 r=result([a]);r['meta']['source']='test'
 md=to_markdown(r)
 assert len(r['pending_constraints'])==1 and '- [ ]' in md
 assert 'key &#124; value' in md and '待人工审核' in md
 assert '100%' not in md
@pytest.mark.parametrize('cfg',[Config(samples=2),Config(verify=True)])
def test_no_silent_legacy_controls(cfg):
 with pytest.raises(ValueError):Pipeline(DOC,Fake(),cfg).run()
def test_factory_never_implicitly_selects_paid_api(monkeypatch):
 monkeypatch.setenv('ANTHROPIC_API_KEY','not-a-real-key')
 assert isinstance(make_llm(),CodexLLM) and isinstance(make_llm('auto'),CodexLLM)
def test_codex_wire_and_error_no_fallback(tmp_path):
 log=tmp_path/'wire.json';exe=tmp_path/'codex'
 exe.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
a=sys.argv[1:];p=sys.stdin.read()
Path(LOG).write_text(json.dumps({'args':a,'prompt':p,'cwd':str(Path.cwd())}))
Path(a[a.index('--output-last-message')+1]).write_text('{"items": []}')
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':21,'output_tokens':3,'cached_input_tokens':4}}))
'''.replace('LOG',repr(str(log))))
 exe.chmod(0o755)
 llm=CodexLLM(binary=str(exe));assert llm.json_call('sys','source','task',{'type':'object'})=={'items':[]}
 a=json.loads(log.read_text());assert '--ignore-user-config' in a['args'] and '--ephemeral' in a['args']
 assert 'shell_tool' in a['args'] and 'multi_agent' in a['args']
 assert json.loads(a['prompt'].split('\n')[-1])=={'document':'source','task':'task'}
 assert llm.usage['input']==21 and llm.usage['cache_read']==4
 exe.write_text('#!/usr/bin/env python3\nraise SystemExit(1)\n')
 with pytest.raises(LLMError,match='no fallback'):llm.json_call('s','d','t',{})


@pytest.mark.parametrize('quotes', [[3], [' '], [None], 'not-a-list'])
def test_invalid_quote_types_fail_closed(quotes):
    a=item({'op':'Class','id':'bad'});a['quotes']=quotes
    r=result([a]);assert not r['items'] and len(r['rejected']['items'])==1


def test_no_attributes_flag_is_enforced_not_only_prompted():
    items=declarations()+[item({'op':'DataProperty','id':'temperature','datatype':'xsd:decimal'}),item({'op':'unit','property':'temperature','unit':'摄氏度'})]
    r=Pipeline(DOC,Fake(items),Config(attributes=False)).run()
    assert not r['attributes']
    assert not any(i['expression']['op']=='DataProperty' for i in r['items'])
    assert len(r['rejected']['items'])==2
