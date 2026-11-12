"""MHTML采集：作用域、基址链、边界行、小语法与终止性检查。"""
import hashlib,json,tempfile,unittest
from pathlib import Path
from source_data.io import load
from source_data.collect import collect

def make(root,name,body,**cfg):
    p=Path(root)/name
    if isinstance(body,str):body=body.encode('utf8')
    p.write_bytes(body)
    v={'source':{'path':name,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()},
       'base_url':cfg.get('base_url','https://shop.invalid/offers/'),
       'preferred_types':cfg.get('preferred_types',['text/html','text/plain']),
       'max_parts':cfg.get('max_parts',1000),'max_decoded_bytes':cfg.get('max_decoded_bytes',1<<20)}
    return collect(v,root)

def refs_of(report,**kw):
    out=[]
    for r in report['references']:
        if all(r.get(k)==v for k,v in kw.items()):out.append(r)
    return out

class FixtureTests(unittest.TestCase):
    def test_offer_scope_and_base_chain(self):
        r=collect(load('data/normal.json')[0],Path('data'))
        self.assertEqual(r['document']['leaf'],'p1')
        self.assertEqual(r['document']['document_base'],'https://shop.invalid/assets/')
        chain=[(s['source'],s['value']) for s in r['document']['base_chain']]
        self.assertEqual(chain[-1],('html-base','https://shop.invalid/assets/'))
        outer,inner=r['containers']
        self.assertEqual(outer['content_ids']['shared'],['p2'])
        self.assertEqual(inner['content_ids']['shared'],['p6'])
        self.assertEqual(r['cid_index']['shared'],[{'container':'p0','parts':['p2']},{'container':'p4','parts':['p6']}])
        outer_ref=refs_of(r,**{'from':'p1','context':'img[src]'})[0]
        self.assertEqual((outer_ref['status'],outer_ref['target'],outer_ref['scope']),('resolved','p2','p0'))
        inner_ref=refs_of(r,**{'from':'p5','context':'img[src]'})[0]
        self.assertEqual((inner_ref['status'],inner_ref['target'],inner_ref['scope']),('resolved','p6','p4'))
        css_ref=refs_of(r,**{'from':'p3','context':'css-url','kind':'relative'})[0]
        self.assertEqual(css_ref['resolved'],'https://shop.invalid/assets/a.png')
        self.assertEqual(css_ref['target'],'p2')
        self.assertEqual(refs_of(r,kind='data')[0]['status'],'inline-data')
        gaps=r['gaps']
        self.assertEqual(len(gaps),1)
        self.assertEqual(gaps[0]['url'],'https://shop.invalid/assets/b.png')
        self.assertEqual(gaps[0]['reason'],'external-not-archived')
        png=next(p for p in r['parts'] if p['id']=='p2')
        self.assertEqual(png['decoded']['sha256'],hashlib.sha256(b'fixture-image').hexdigest())
        raw=Path('data/offer.mhtml').read_bytes()
        s,e=png['body_range']
        self.assertEqual(raw[s:e],b'Zml4dHVyZS1pbWFnZQ==')
        mail=next(p for p in r['parts'] if p['content_type']=='message/rfc822')
        self.assertTrue(mail['opaque'])
        self.assertIsNone(mail['children'])
        self.assertNotIn('not-a-web-resource',json.dumps(r['containers']))
        self.assertEqual(r['completeness']['resolved'],5)

    def test_ambiguous_root_and_duplicate_cid(self):
        r=collect(load('data/ambiguous-root-id.json')[0],Path('data'))
        self.assertIsNone(r['document']['leaf'])
        types={(c['type'],c.get('id')) for c in r['conflicts']}
        self.assertIn(('duplicate-content-id','shared'),types)
        self.assertIn(('root-missing',None),types)
        ref=refs_of(r,**{'from':'p1','context':'img[src]'})[0]
        self.assertEqual(ref['status'],'ambiguous')
        self.assertEqual(ref['candidates'],['p1','p2'])
        inner=refs_of(r,**{'from':'p5'})[0]
        self.assertEqual((inner['status'],inner['target']),('resolved','p6'))

    def test_changed_document_base(self):
        r=collect(load('data/changed-document-base.json')[0],Path('data'))
        self.assertEqual(r['document']['document_base'],'https://other.invalid/a/')
        urls={g['url'] for g in r['gaps']}
        self.assertEqual(urls,{'https://other.invalid/a/style.css','https://other.invalid/a/a.png','https://other.invalid/a/b.png'})
        self.assertEqual(refs_of(r,**{'from':'p1','context':'img[src]'})[0]['status'],'resolved')
        css=refs_of(r,**{'from':'p3','kind':'relative'})[0]
        self.assertEqual(css['status'],'resolved')

class CraftedTests(unittest.TestCase):
    def test_folded_headers(self):
        body=(b'MIME-Version: 1.0\n'
              b'Content-Type: multipart/related;\n boundary="o";\n start="<doc>"\n'
              b'Content-Base: https://x.invalid/a/\n\n'
              b'--o\nContent-Type: text/html\nContent-ID: <doc>\nContent-Location:\n page.html\n\n'
              b'<img src="cid:a">\n'
              b'--o\nContent-Type: image/png\nContent-ID: <a>\n\nZ\n--o--\n')
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body)
        notes=r['parts'][0]['notes']
        self.assertIn('展开折叠头:content-type',notes)
        html=next(p for p in r['parts'] if p['content_type']=='text/html')
        self.assertIn('展开折叠头:content-location',html['notes'])
        self.assertEqual(html['resolved_location'],'https://x.invalid/a/page.html')
        self.assertEqual(refs_of(r,kind='cid')[0]['status'],'resolved')

    def test_boundary_text_inside_encoding(self):
        payload=b'--o\n--o--\ntrailer'
        import base64
        body=(b'MIME-Version: 1.0\nContent-Type: multipart/related; boundary=o\n\n'
              b'--o\nContent-Type: text/plain\nContent-Transfer-Encoding: base64\n\n'
              +base64.b64encode(payload)+b'\n'
              b'--o\nContent-Type: text/plain\nContent-Transfer-Encoding: quoted-printable\n\n'
              b'--=6F\nx--o\n--o extra\n'
              b'--o--\n')
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body)
        leaves=[p for p in r['parts'] if p['decoded']]
        self.assertEqual(len(leaves),2)
        self.assertEqual(leaves[0]['decoded']['sha256'],hashlib.sha256(payload).hexdigest())
        self.assertEqual(leaves[1]['decoded']['bytes'],len(b'--O\nx--o\n--o extra'))
        self.assertTrue(any('疑似边界行' in n for n in r['parts'][0]['notes']))

    def test_alternative_root_preference(self):
        body=(b'MIME-Version: 1.0\nContent-Type: multipart/related; boundary=o; start="<doc>"\n\n'
              b'--o\nContent-Type: multipart/alternative; boundary=a\nContent-ID: <doc>\n\n'
              b'--a\nContent-Type: text/plain\n\nplain version\n'
              b'--a\nContent-Type: text/html\n\n<html><body>html version</body></html>\n'
              b'--a--\n--o--\n')
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body)
            leaf=r['document']['leaf']
            self.assertEqual(next(p for p in r['parts'] if p['id']==leaf)['content_type'],'text/html')
            alt=next(s for s in r['document']['selection'] if 'alternative' in s)
            self.assertEqual(alt['matched'],'text/html')
            self.assertEqual(len(alt['archived']),1)
            r2=make(d,'m2.mhtml',body,preferred_types=['text/plain'])
            leaf2=r2['document']['leaf']
            self.assertEqual(next(p for p in r2['parts'] if p['id']==leaf2)['content_type'],'text/plain')

    def test_rfc822_opaque(self):
        body=(b'MIME-Version: 1.0\nContent-Type: multipart/related; boundary=o\n\n'
              b'--o\nContent-Type: text/html\nContent-ID: <doc>\n\n<img src="cid:shared">\n'
              b'--o\nContent-Type: message/rfc822\n\n'
              b'MIME-Version: 1.0\nContent-Type: text/plain\nContent-ID: <shared>\n\nnot-a-resource\n'
              b'--o--\n')
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body)
        self.assertEqual(r['containers'][0]['content_ids'],{'doc':['p1']})
        ref=refs_of(r,kind='cid')[0]
        self.assertEqual((ref['status'],ref['reason']),('gap','cid-not-in-scope'))
        mail=next(p for p in r['parts'] if p['content_type']=='message/rfc822')
        self.assertTrue(mail['opaque'])
        self.assertEqual(mail['decoded']['bytes'],len(b'MIME-Version: 1.0\nContent-Type: text/plain\nContent-ID: <shared>\n\nnot-a-resource'))

    def test_srcset_data_url_and_descriptors(self):
        body=(b'MIME-Version: 1.0\nContent-Type: multipart/related; boundary=o\n\n'
              b'--o\nContent-Type: text/html\nContent-ID: <doc>\n\n'
              b'<img srcset="data:image/png;base64,AAAA 1x, b.png 2x, c.png bad">\n'
              b'--o--\n')
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body)
        kinds=[x['kind'] for x in r['references']]
        self.assertEqual(kinds,['data','relative'])
        self.assertEqual(r['references'][0]['status'],'inline-data')
        self.assertEqual(r['references'][1]['original'],'b.png')
        self.assertEqual(len(r['unparsed']),1)
        self.assertIn('c.png',r['unparsed'][0]['snippet'])

    def test_css_grammar(self):
        css=(b'/* c */ a{background:url(plain.png)}\n'
             b'b{background:url(\'quo ted.png\')}\n'
             b'c{background:url(esc\\)aped.png)}\n'
             b'd{background:url(data:image/png;base64,AA==)}\n'
             b'@import url("ignored.css");\n'
             b'e{background:url(bad\'quote.png)}\n'
             b'f{background:url("open.png)}\n')
        body=(b'MIME-Version: 1.0\nContent-Type: multipart/related; boundary=o\n\n'
              b'--o\nContent-Type: text/css\nContent-Location: s.css\n\n'+css+b'\n--o--\n')
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body,base_url='https://x.invalid/')
        got=[x['original'] for x in r['references']]
        self.assertEqual(got,['plain.png','quo ted.png','esc)aped.png','data:image/png;base64,AA=='])
        reasons={u['reason'] for u in r['unparsed']}
        self.assertIn('@import不展开',reasons)
        self.assertIn('url()含非法字符',reasons)
        self.assertIn('字符串未闭合',reasons)

    def test_style_attribute_and_element(self):
        body=(b'MIME-Version: 1.0\nContent-Type: multipart/related; boundary=o\n\n'
              b'--o\nContent-Type: text/html\nContent-ID: <doc>\nContent-Location: https://x.invalid/\n\n'
              b'<div style="background:url(a.png)"></div><style>b{background:url(b.png)}</style>\n'
              b'--o--\n')
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body)
        ctx={(x['context'],x['original']) for x in r['references']}
        self.assertEqual(ctx,{('div[style]','a.png'),('style','b.png')})

    def test_html_entities_and_query_kept(self):
        body=(b'MIME-Version: 1.0\nContent-Type: multipart/related; boundary=o\n\n'
              b'--o\nContent-Type: text/html\nContent-ID: <doc>\nContent-Location: https://x.invalid/\n\n'
              b'<a href="x.png?a=1&amp;b=2#frag">t</a>\n'
              b'--o--\n')
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body)
        ref=r['references'][0]
        self.assertEqual(ref['resolved'],'https://x.invalid/x.png?a=1&b=2#frag')
        self.assertEqual(ref['status'],'gap')

    def test_same_address_different_bytes_conflict(self):
        body=(b'MIME-Version: 1.0\nContent-Type: multipart/related; boundary=o\n\n'
              b'--o\nContent-Type: text/html\nContent-ID: <doc>\nContent-Location: https://x.invalid/\n\n'
              b'<img src="a.png">\n'
              b'--o\nContent-Type: image/png\nContent-Location: a.png\n\none\n'
              b'--o\nContent-Type: image/png\nContent-Location: ./a.png\n\ntwo\n'
              b'--o--\n')
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body,base_url='https://x.invalid/')
        self.assertEqual(r['conflicts'][0]['type'],'same-address-different-bytes')
        ref=refs_of(r,context='img[src]')[0]
        self.assertEqual(ref['status'],'conflict')
        self.assertEqual(len(ref['candidates']),2)

    def test_limits_and_invalid_config(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                make(d,'m.mhtml',b'MIME-Version: 1.0\nContent-Type: multipart/related; boundary=o\n\n--o\nContent-Type: text/plain\n\nx\n--o--\n',max_parts=1)
        v=load('data/invalid-config.json')[0]
        with self.assertRaises(ValueError):collect(v,Path('data'))

    def test_deep_nesting_terminates(self):
        inner=b'Content-Type: text/plain\n\nleaf'
        for i in range(40):
            inner=(b'Content-Type: multipart/related; boundary=b%d\n\n--b%d\n'%(i,i)+inner+b'\n--b%d--\n'%i)
        body=b'MIME-Version: 1.0\n'+inner
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body)
        self.assertLessEqual(r['completeness']['parts'],1000)
        self.assertTrue(any(p['opaque'] for p in r['parts']))
        self.assertTrue(any('深度超限' in n for p in r['parts'] for n in p['notes']))

    def test_missing_close_boundary(self):
        body=(b'MIME-Version: 1.0\nContent-Type: multipart/related; boundary=o\n\n'
              b'--o\nContent-Type: text/plain\n\nhello\n')
        with tempfile.TemporaryDirectory() as d:
            r=make(d,'m.mhtml',body)
        self.assertTrue(any('缺少闭合边界行' in n for n in r['parts'][0]['notes']))
        self.assertEqual(len(r['parts']),2)

if __name__=='__main__':unittest.main()
