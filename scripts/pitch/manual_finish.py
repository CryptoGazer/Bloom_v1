"""Keep the user's selected composition; manually correct B/E/A only."""
import json
import math
from collections import Counter

import numpy as np
from shapely.geometry import LineString
from shapely.ops import unary_union

from scripts.pitch import street_word as art


class Original(art.Streets):
    def __init__(self):
        super().__init__({'street','service','path'})

    def fit(self,ch,cx,cy,unit,angle):
        self.track=[]
        self.part_quality=[]
        lines,error=art.draft.letter(self,ch,cx,cy,unit,angle)
        if lines is None:
            return None
        counts=Counter(self.track)
        repeated=sum(self.lengths[e]*(n-1) for e,n in counts.items())
        total=sum(self.lengths[e] for e in self.track)
        if repeated>.30*total:
            return None
        ideal=unary_union([LineString(art.transform(np.asarray(p)-[1.1,2],cx,cy,unit,angle)) for p in art.draft.GLYPHS[ch]]).buffer(unit*.15)
        actual=unary_union([LineString(p) for p in lines]).buffer(unit*.15)
        iou=ideal.intersection(actual).area/ideal.union(actual).area
        score=(1-iou)*35+min(error,500)*.025+30*repeated/max(1,total)
        return {'letter':ch,'score':float(score),'iou':float(iou),'lines':lines,
                'pose':[cx,cy,unit,angle],'edges':list(counts)}


def recover():
    path=art.WORK/'approved-base.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf8'))
    art.draft.GLYPHS['N']=[[(0,0),(0,4),(2.2,0),(2.2,4)]]
    art.draft.GLYPHS['Z']=[[(0,4),(2.2,4),(0,0),(2.2,0)]]
    art.SAMPLES={ch:art.sample_glyph(ch) for ch in art.WORD}
    st=Original();u=110;angle=math.radians(-45)
    candidates=[]
    for dx in [-240,-120,0,120,240]:
        for dy in [-200,-100,0,100,200]:
            cx,cy=21.229*art.KX+dx,45.756*art.KY+dy
            score=sum(st.coarse(ch,*p,u,angle) for ch,p in zip(art.WORD,art.glyph_centres(cx,cy,u,angle)))
            candidates.append((score,cx,cy))
    _,cx,cy=min(candidates)
    pools=[]
    for ch,p in zip(art.WORD,art.glyph_centres(cx,cy,u,angle)):
        poses=[]
        for scale in [.8,1.,1.2]:
            for dx in [-.75,0,.75]:
                for dy in [-1.,0,1.]:
                    for turn in [-15,0,15]:
                        x,y=art.transform([[dx,dy]],*p,u,angle)[0]
                        pose=[x,y,u*scale,angle+math.radians(turn)]
                        poses.append((st.coarse(ch,*pose),pose))
        fits=[]
        for _,pose in sorted(poses):
            f=st.fit(ch,*pose)
            if f:
                fits.append(f)
                if len(fits)==12:break
        assert fits,ch
        pools.append(sorted(fits,key=lambda f:f['score']))
    c,s=math.cos(angle),math.sin(angle)
    span=lambda f:(min(p[0]*c+p[1]*s for line in f['lines'] for p in line),max(p[0]*c+p[1]*s for line in f['lines'] for p in line))
    beam=[(0.,[],float('-inf'))]
    for pool in pools:
        following=[]
        for score,chosen,right in beam:
            for f in pool:
                left,end=span(f)
                if left>=right+.12*u:
                    following.append((score+f['score'],chosen+[f],end))
        beam=sorted(following,key=lambda p:p[0])[:12]
    score,letters,_=beam[0]
    # Retain exact source geometry, independently of graph indexing in later edits.
    for f in letters:
        f['source_ids']=[st.properties[e]['id'] for e in f['edges']]
    result={'region':'centre','score':score,'angle':angle,'letters':letters}
    path.write_text(json.dumps(result),encoding='utf8')
    art.render(st,result,art.WORK/'approved-base.png')
    print('Recovered chosen composition:',round(score,2),flush=True)
    return result


if __name__=='__main__':
    recover()
