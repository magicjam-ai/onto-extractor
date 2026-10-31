import json
from pathlib import Path
from collections import Counter
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ontoextract.__main__ import read_document, main

def test_real_readers_unicode_and_pdf(tmp_path):
    from docx import Document
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    text='温控舱是试验舱。\n证据 | 范围'
    for suffix in ['.txt','.md']:
        f=tmp_path/('中文'+suffix);f.write_text(text)
        assert read_document(f)==text
    d=Document();d.add_paragraph('温控舱是试验舱。');d.add_paragraph('证据 | 范围')
    f=tmp_path/'中文.docx';d.save(f);assert read_document(f)==text
    w=PdfWriter();page=w.add_blank_page(width=300,height=200)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):w._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 100 Td (Optical frame is a frame.) Tj ET')
    page[NameObject('/Contents')]=w._add_object(stream)
    f=tmp_path/'example.pdf';w.write(f)
    assert 'Optical frame is a frame.' in read_document(f)

def test_cli_combine_output_and_default_backend(tmp_path,monkeypatch):
    from ontoextract import __main__ as cli
    calls=[]
    class Fake:
        model,effort='fake-codex','high'
        usage=Counter(requests=1)
        def cost_usd(self):return None
        def json_call(self,system,document,task,schema):
            calls.append(document)
            return {'items':[{'label':'frame','definition':'a frame','scope':'','conditions':[],
                              'quotes':['Optical frame is a frame.'],
                              'expression':{'op':'Class','id':'Frame'}}]}
    def make(backend,*args,**kwargs):
        assert backend=='codex';return Fake()
    monkeypatch.setattr(cli,'make_llm',make)
    a=tmp_path/'first.md';a.write_text('Optical frame is a frame.')
    b=tmp_path/'second.txt';b.write_text('Additional context.')
    out=tmp_path/'out'
    assert main([str(a),str(b),'--combine','-o',str(out)])==0
    r=json.loads((out/'combined.json').read_text())
    assert r['meta']['kernel']=='direct-tbox' and r['meta']['cost_usd_estimate'] is None
    assert '## first.md' in calls[0] and '## second.txt' in calls[0]
    span=r['items'][0]['evidence_spans'][0]
    assert calls[0][span['start']:span['end']]=='Optical frame is a frame.'
    assert '## Classes' in (out/'combined.md').read_text()


def test_review_html_escapes_source_and_separates_proposals():
    from ontoextract.review import to_html
    import re
    r={'items':[], 'meta':{'source_sha256':'source'}}
    source='😀 </script><script>alert(1)</script>'
    h=to_html(r,source)
    embedded=re.search(r'<script id="data" type="application/json">(.*?)</script>',h,re.S).group(1)
    assert '</script>' not in embedded and json.loads(embedded)['document']==source
    a=json.loads(embedded)['review_id']
    r['items']=[{'candidate_id':'C0001','expression':{'op':'Class','id':'Other'}}]
    b=json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>',to_html(r,source),re.S).group(1))['review_id']
    assert a!=b
