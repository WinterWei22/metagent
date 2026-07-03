#!/usr/bin/env python3
"""给 perturbation benchmark 代谢物名补 InChIKey/SMILES(RefMet 中性名→PubChem),重建 benchmark。
修复 name-only 输入导致的 RaMP/mummichog 解析丢失(3/14→应接近全)。
用法：python scripts/metagent/resolve_and_rebuild_bench.py <v0.jsonl> <out_synthetic.jsonl> <cache.json>
"""
import json, sys, urllib.request, urllib.parse, time
from pathlib import Path

def get(url):
    try:
        with urllib.request.urlopen(url, timeout=25) as r: return r.read().decode()
    except Exception: return None
def refmet(n):
    t=get('https://www.metabolomicsworkbench.org/rest/refmet/match/'+urllib.parse.quote(n)+'/name')
    try: return json.loads(t).get('refmet_name') or None
    except Exception: return None
def pubchem(n):
    t=get('https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/'+urllib.parse.quote(n)+'/property/InChIKey,CanonicalSMILES/JSON')
    try:
        p=json.loads(t)['PropertyTable']['Properties'][0]; return p.get('InChIKey'), p.get('CanonicalSMILES')
    except Exception: return None, None

GOLD={'TCA/oncometabolite':'Citrate cycle (TCA cycle)','Urea cycle':'Urea cycle / arginine biosynthesis',
      'Phenylalanine':'Phenylalanine metabolism','BCAA':'Valine, leucine and isoleucine degradation'}

def main():
    v0, out, cachef = sys.argv[1], sys.argv[2], sys.argv[3]
    tasks=[json.loads(l) for l in open(v0) if l.strip()]
    cache=json.load(open(cachef)) if Path(cachef).exists() else {}
    names=set()
    import re
    MZ=re.compile(r'^[\d.]+_[\d.]+(m/z|n)$|^X\s*-\s*\d|^-p$')
    ABBR={'phe':'phenylalanine','suc':'succinate','fum':'fumarate','mal':'malate','cit':'citrate','isocit':'isocitrate','cisac':'cis-aconitate','keto':'2-oxoglutarate','2hg':'2-hydroxyglutarate','lac':'lactate','pyr':'pyruvate','glu':'glutamate','gln':'glutamine','asp':'aspartate','asn':'asparagine','succinate/methylmalonate':'succinate','fumarate/maleate/alpha-ketoisovalerate':'fumarate'}
    def norm(n): return ABBR.get(n.lower().strip(), n.strip())
    for t in tasks:
        for m in t['input']['differential_metabolites']:
            n=norm(m['name'])
            if not MZ.match(n): names.add(n)
    print(f'{len(names)} unique names to resolve', flush=True)
    for i,n in enumerate(sorted(names)):
        if n in cache: continue
        rn=refmet(n) or n
        ik,sm=pubchem(rn)
        cache[n]={'refmet':rn,'inchikey':ik,'smiles':sm}
        if (i+1)%20==0:
            json.dump(cache,open(cachef,'w'))
            print(f'  {i+1}/{len(names)} resolved', flush=True)
        time.sleep(0.1)
    json.dump(cache,open(cachef,'w'))
    nres=sum(1 for v in cache.values() if v.get('inchikey'))
    print(f'resolved {nres}/{len(cache)} to InChIKey', flush=True)
    # rebuild
    lines=[]
    for t in tasks:
        mets=[]; seen=set()
        for m in t['input']['differential_metabolites']:
            n=norm(m['name'])
            if MZ.match(n): continue
            c=cache.get(n,{})
            if not c.get('inchikey'): continue  # 只留能解析的
            key=c['inchikey']
            if key in seen: continue
            seen.add(key)
            mets.append({'name':c.get('refmet') or n,'smiles':c.get('smiles') or '','inchikey':c['inchikey']})
        if len(mets)<3: 
            print(f"  SKIP {t['task_id']}: only {len(mets)} resolved", flush=True); continue
        fam=t.get('pathway_family','')
        goldname = GOLD.get(fam) or GOLD.get(next((k for k in GOLD if k.split('/')[0] in fam),''), t['gold']['perturbed_pathway'])
        lines.append(json.dumps({'task_id':'sub6_easy_'+t['task_id'],'orig_task_id':t['task_id'],'pathway_family':fam,
            'input':{'differential_metabolites':mets[:15]},
            'ground_truth':{'perturbed_pathway':{'id':'','name':goldname,'ontology':'curated'}}},ensure_ascii=False))
    open(out,'w').write('\n'.join(lines)+'\n')
    print(f'wrote {len(lines)} tasks -> {out}', flush=True)

if __name__=='__main__': main()
