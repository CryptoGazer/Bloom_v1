"""Fit a street-only BEZNA wordmark, render candidates and export title/icon.

No font outline is painted: every bright segment is an original OSM street.
The older title and Claude's draft are left intact. Run from the repo:
  ../.venv/Scripts/python -m scripts.pitch.street_word search
  ../.venv/Scripts/python -m scripts.pitch.street_word render
"""
import argparse
from collections import Counter
import gzip
import heapq
import json
import math
from html import escape
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import shapely
from shapely.geometry import LineString, Point
from shapely.ops import unary_union, polygonize

from scripts.pitch import street_letters as draft

ROOT = Path(__file__).resolve().parents[2]
NETWORK = ROOT / 'data/out/city-northwest/segments.geojson.gz'
OUT = ROOT / 'web/pitch/bezna-streets-v2.json'
WORK = ROOT / 'data/cache/pitch-streets'
EXPORT = ROOT / 'docs/pitch'
KX, KY = draft.KX, draft.KY
WORD, ADVANCE = 'BEZNA', 3.25
# The draft B had a tiny 0.4-unit step: both ends often snapped to the same
# junction and deleted an entire letter. Use two complete street-sized bowls.
draft.GLYPHS = {**draft.GLYPHS, 'B': [
    [(0, 0), (0, 4), (2.2, 4), (2.2, 2), (0, 2)],
    [(2.2, 2), (2.2, 0), (0, 0)],
], 'N': [[(0, 0), (0, 4)], [(2.2, 0), (2.2, 4)], [(0, 4), (2.2, 0)]],
   'Z': [[(0, 4), (2.2, 4)], [(0, 0), (2.2, 0)], [(2.2, 4), (0, 0)]]}


def sample_glyph(ch):
    points = []
    for stroke in draft.GLYPHS[ch]:
        for a, b in zip(stroke, stroke[1:]):
            n = max(2, math.ceil(math.dist(a, b) / .18))
            points.extend([(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) for t in np.linspace(0, 1, n)])
    return np.asarray(points) - [1.1, 2]


SAMPLES = {ch: sample_glyph(ch) for ch in WORD}


def transform(points, cx, cy, unit, angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.asarray(points) @ np.array([[c, s], [-s, c]]) * unit + [cx, cy]


class Streets(draft.Streets):
    def __init__(self, kinds=None):
        draft.SEGMENTS = NETWORK
        draft.KINDS = kinds or {'street', 'service', 'path', 'sidewalk', 'crossing'}
        super().__init__()
        self.ids = list(self.xy)
        self.node_points = np.array([self.xy[n] for n in self.ids])
        self.node_tree = shapely.STRtree(shapely.points(self.node_points))
        self.road_tree = shapely.STRtree([LineString(line) for line, _, _ in self.edges])
        self.edge_samples = np.array([[p[0], p[len(p)//2], p[-1]] for p, _, _ in self.edges])
        self.lengths = np.array([e[1] for e in self.edges])
        self.track = []
        with gzip.open(NETWORK, 'rt', encoding='utf8') as stream:
            self.properties = [f['properties'] for f in json.load(stream)['features'] if f['properties'].get('kind') in draft.KINDS]

    def nearest(self, p, limit):
        ix, distances = self.node_tree.query_nearest(Point(p), return_distance=True, all_matches=False)
        d, i = float(distances[0]), int(ix[0])
        return (d, self.ids[i] if d < max(limit, 70) else None)

    def coarse(self, ch, cx, cy, unit, angle):
        points = transform(SAMPLES[ch], cx, cy, unit, angle)
        _, distances = self.road_tree.query_nearest(shapely.points(points), return_distance=True, all_matches=False)
        distance = distances / unit
        return float(np.mean(distance**2) + .4*np.quantile(distance, .9)**2)

    def along(self, start, target, a, b, d0):
        d0 *= 2.1  # allow the staircase diagonals of a street grid, then score their silhouette
        a, b = np.asarray(a), np.asarray(b)
        delta = b - a
        nearby = self.road_tree.query(LineString([a,b]).buffer(4*d0),predicate='intersects')
        samples = self.edge_samples[nearby]
        t = np.clip(np.sum((samples - a)*delta, axis=2) / max(1, np.sum(delta**2)), 0, 1)
        far = np.max(np.linalg.norm(samples - (a + t[..., None]*delta), axis=2), axis=1)
        weights = np.full(len(self.edges), np.inf)
        weights[nearby] = self.lengths[nearby] * (1 + (far/d0)**3)
        if self.track:
            weights[np.asarray(self.track)] *= 12
        allowed = np.zeros(len(self.edges), dtype=bool)
        allowed[nearby] = far < 4*d0
        tx, ty = self.xy[target]
        costs, previous, queue = {start: 0.}, {start: None}, [(0., 0., start)]
        while queue:
            _, cost, node = heapq.heappop(queue)
            if cost > costs[node]:
                continue
            if node == target:
                break
            for neighbour, edge in self.adj[node]:
                if not allowed[edge]:
                    continue
                nc = cost + weights[edge]
                if nc < costs.get(neighbour, math.inf):
                    costs[neighbour], previous[neighbour] = nc, (node, edge)
                    x, y = self.xy[neighbour]
                    heapq.heappush(queue, (nc + math.hypot(x-tx, y-ty), nc, neighbour))
        if target not in previous:
            return None, math.inf
        chain, edges, node = [], [], target
        while previous[node] is not None:
            parent, edge = previous[node]
            points = self.edges[edge][0]
            chain.append(points if self.xy[parent] == points[0] else points[::-1])
            edges.append(edge)
            node = parent
        self.track.extend(reversed(edges))
        line = []
        for points in reversed(chain):
            line.extend(points if not line else points[1:])
        self.part_quality.append(sum(math.dist(x,y) for x,y in zip(line,line[1:])) / max(1,math.dist(self.xy[start],self.xy[target])))
        return line, costs[target]

    def fit(self, ch, cx, cy, unit, angle):
        self.track = []
        self.part_quality = []
        lines, error = draft.letter(self, ch, cx, cy, unit, angle)
        if lines is None:
            return None
        counts = Counter(self.track)
        repeated = sum(self.lengths[e] * (n-1) for e, n in counts.items())
        total = sum(self.lengths[e] for e in self.track)
        if repeated > (.10 if ch in 'NZ' else .30)*total:
            return None
        parents = {}
        def find(n):
            parents.setdefault(n,n)
            while parents[n] != n:
                n=parents[n]
            return n
        for edge in counts:
            p=self.properties[edge]
            u,v=find(p['u']),find(p['v'])
            parents[u]=v
        if len({find(n) for n in parents}) != 1:
            return None
        degree=Counter()
        for edge in counts:
            p=self.properties[edge]
            degree[p['u']]+=1
            degree[p['v']]+=1
        tips=sum(d==1 for d in degree.values())
        if tips != {'B':0,'E':3,'Z':2,'N':2,'A':2}[ch]:
            return None
        if ch in 'BA':
            holes=[p for p in polygonize(unary_union([LineString(self.edges[i][0]) for i in counts])) if p.area>unit*unit*.15]
            if len(holes)<(2 if ch=='B' else 1):
                return None
        if ch=='E' and self.part_quality[1]>1.3:
            return None
        ideal = []
        for stroke in draft.GLYPHS[ch]:
            ideal.append(LineString(transform(np.asarray(stroke)-[1.1, 2], cx, cy, unit, angle)))
        ideal = unary_union(ideal).buffer(unit*.15)
        actual = unary_union([LineString(p) for p in lines]).buffer(unit*.15)
        iou = ideal.intersection(actual).area / ideal.union(actual).area
        score = (1-iou)*35 + min(error, 500)*.025 + 30*repeated/max(1,total)
        return {'letter': ch, 'score': float(score), 'iou': float(iou), 'lines': lines,
                'pose': [cx, cy, unit, angle], 'edges': list(counts)}


def glyph_centres(cx, cy, unit, angle):
    return transform([[i*ADVANCE-2*ADVANCE, 0] for i in range(5)], cx, cy, unit, angle)


def optimize(st, name, lon, lat):
    candidates = []
    for unit in [65, 85, 110, 140]:
        for degrees in [-45, -30, -15, 0, 15, 30, 45]:
            angle = math.radians(degrees)
            for dx in [-240, -120, 0, 120, 240]:
                for dy in [-200, -100, 0, 100, 200]:
                    cx, cy = lon*KX + dx, lat*KY + dy
                    centres = glyph_centres(cx, cy, unit, angle)
                    score = sum(st.coarse(ch, *p, unit, angle) for ch, p in zip(WORD, centres))
                    candidates.append((score, cx, cy, unit, angle))
    shortlisted = [min((p for p in candidates if p[3] == unit), key=lambda p:p[0]) for unit in [65,85,110,140]]
    for candidate in sorted(candidates):
        _, cx, cy, unit, angle = candidate
        if any(math.hypot(cx-p[1],cy-p[2]) < 130 and abs(unit-p[3]) < 25 and abs(angle-p[4]) < .2 for p in shortlisted):
            continue
        shortlisted.append(candidate)
        if len(shortlisted) == 7:
            break
    results = []
    print(name, 'coarse shortlist ready', flush=True)
    for _, cx, cy, unit, angle in shortlisted:
        pools = []
        for ch, p in zip(WORD, glyph_centres(cx, cy, unit, angle)):
            poses = []
            for scale in [.8, 1., 1.2]:
                for dx in [-.75, 0, .75]:
                    for dy in [-1., 0, 1.]:
                        for turn in [-15, 0, 15]:
                            x, y = transform([[dx, dy]], *p, unit, angle)[0]
                            pose = [x, y, unit*scale, angle+math.radians(turn)]
                            poses.append((st.coarse(ch, *pose), pose))
            fits = []
            for _, pose in sorted(poses):
                fit = st.fit(ch, *pose)
                if fit is not None:
                    fits.append(fit)
                    if len(fits) == 12:
                        break
            if not fits:
                print(name, 'no fit for', ch, 'unit', unit, flush=True)
                break
            pools.append(sorted(fits,key=lambda f:f['score']))
        if len(pools) == 5:
            c,s=math.cos(angle),math.sin(angle)
            def span(f):
                xs=[p[0]*c+p[1]*s for line in f['lines'] for p in line]
                return min(xs),max(xs)
            beam=[(0.,[],float('-inf'))]
            for pool in pools:
                next_beam=[]
                for score,chosen,right in beam:
                    for f in pool:
                        left,end=span(f)
                        if left<right+.12*unit:
                            continue
                        next_beam.append((score+f['score'],chosen+[f],end))
                beam=sorted(next_beam,key=lambda p:p[0])[:12]
                if not beam:
                    break
            if not beam:
                print(name, 'rejected overlapping letters', flush=True)
                continue
            score,letters,_=beam[0]
            result = {'region': name, 'score': score, 'angle': angle, 'letters': letters}
            results.append(result)
            print(name, 'unit', unit, 'angle', round(math.degrees(angle)), 'score', round(score,2),
                  'IoU', [round(f['iou'],2) for f in letters], flush=True)
    return sorted(results, key=lambda r:r['score'])


def font(size):
    return ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', size)


def render(st, result, filename, size=(1920,1080), icon=None, caption=True):
    scale = 2
    width, height = [v*scale for v in size]
    angle = -result.get('angle', 0)
    if icon:
        glyph = next(f for f in result['letters'] if f['letter']==icon)
        angle = -glyph.get('pose',[0,0,0,result.get('angle',0)])[3]
    c, s = math.cos(angle), math.sin(angle)
    rotate = lambda p:(p[0]*c-p[1]*s, p[0]*s+p[1]*c)
    letters = result['letters'] if icon is None else [next(f for f in result['letters'] if f['letter']==icon)]
    points = [rotate(p) for f in letters for line in f['lines'] for p in line]
    xs,ys=zip(*points)
    w,h=max(xs)-min(xs),max(ys)-min(ys)
    factor=min(width*(.76 if icon else .85)/w,height*(.72 if icon else .56)/h)
    mx,my=(max(xs)+min(xs))/2,(max(ys)+min(ys))/2
    py=height*(.50 if icon else .46)
    def project(p):
        x,y=rotate(p)
        return (round(width/2+(x-mx)*factor),round(py-(y-my)*factor))
    image=Image.new('RGB',(width,height),'#090D0F')
    draw=ImageDraw.Draw(image)
    background, foreground = [], []
    def svg_path(points):
        return 'M' + 'L'.join(str(x)+','+str(y) for x,y in points)
    for points, length, _ in st.edges:
        p=[project(q) for q in points]
        if max(q[0] for q in p)<0 or min(q[0] for q in p)>width or max(q[1] for q in p)<0 or min(q[1] for q in p)>height:
            continue
        draw.line(p,fill='#273034',width=max(1,round(scale*.9)),joint='curve')
        background.append('<path d="'+svg_path(p)+'"/>')
    glow=Image.new('RGBA',(width,height))
    gd=ImageDraw.Draw(glow)
    lw=round(width*.025) if icon else round(5*scale)
    for f in letters:
        for line in f['lines']:
            gd.line([project(p) for p in line],fill=(237,247,247,100),width=lw*3,joint='curve')
    image=Image.alpha_composite(image.convert('RGBA'),glow.filter(ImageFilter.GaussianBlur(7*scale)))
    draw=ImageDraw.Draw(image)
    for f in letters:
        for line in f['lines']:
            p=[project(q) for q in line]
            foreground.append('<path d="'+svg_path(p)+'"/>')
            draw.line(p,fill='#F2F6F6',width=lw,joint='curve')
            for x,y in [p[0],p[-1]]:
                r=lw/2
                draw.ellipse((x-r,y-r,x+r,y+r),fill='#F2F6F6')
    if caption and not icon:
        draw.text((width*.07,height*.82),'Prin beznă, spre casă.',font=font(round(28*scale)),fill='#D5DDDF')
        draw.text((width*.07,height*.88),'TIMIȘOARA  /  UNIHACK 2026',font=font(round(12*scale)),fill='#68767C')
        draw.text((width*.93,height*.94),'© OpenStreetMap contributors',font=font(round(9*scale)),fill='#526066',anchor='rs')
    filename.parent.mkdir(parents=True,exist_ok=True)
    image.convert('RGB').resize(size,Image.Resampling.LANCZOS).save(filename)
    if filename.parent == EXPORT and filename.stem in ['title-streets', 'app-icon-streets']:
        caption_svg = ''
        if caption and not icon:
            caption_svg = '<g font-family="Segoe UI,Arial,sans-serif"><text x="'+str(width*.07)+'" y="'+str(height*.82+28*scale)+'" font-size="'+str(28*scale)+'" fill="#D5DDDF">Prin beznă, spre casă.</text><text x="'+str(width*.07)+'" y="'+str(height*.88+12*scale)+'" font-size="'+str(12*scale)+'" fill="#68767C">TIMIȘOARA / UNIHACK 2026</text><text text-anchor="end" x="'+str(width*.93)+'" y="'+str(height*.94)+'" font-size="'+str(9*scale)+'" fill="#526066">© OpenStreetMap contributors</text></g>'
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="'+str(size[0])+'" height="'+str(size[1])+'" viewBox="0 0 '+str(width)+' '+str(height)+'"><title>BEZNA drawn with real Timișoara streets</title><defs><filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="'+str(7*scale)+'"/></filter></defs><rect width="100%" height="100%" fill="#090D0F"/><g fill="none" stroke="#273034" stroke-width="'+str(max(1,round(scale*.9)))+'">'+''.join(background)+'</g><g fill="none" stroke-linejoin="round" stroke-linecap="round" stroke="#EDF7F7" stroke-opacity=".4" stroke-width="'+str(lw*3)+'" filter="url(#glow)">'+''.join(foreground)+'</g><g fill="none" stroke-linejoin="round" stroke-linecap="round" stroke="#F2F6F6" stroke-width="'+str(lw)+'">'+''.join(foreground)+'</g>'+caption_svg+'</svg>'
        svg_name = 'street-icon-v2.svg' if icon else 'street-title-v2.svg'
        (ROOT/'web/pitch'/svg_name).write_text(svg,encoding='utf8')


def export(result, st):
    features=[]
    for f in result['letters']:
        features.append({'type':'Feature','properties':{'letter':f['letter'],'fit_iou':round(f['iou'],3),
                         'segment_ids':[st.properties[i]['id'] for i in f['edges']],
                         'street_names':sorted({st.properties[i].get('name') for i in f['edges'] if st.properties[i].get('name')})},
                         'geometry':{'type':'MultiLineString','coordinates':[[[round(p[0]/KX,6),round(p[1]/KY,6)] for p in line] for line in f['lines']]}})
    output={'type':'FeatureCollection','meta':{'word':WORD,'region':result['region'],
            'map_rotation_deg':round(math.degrees(result['angle']),3),'source':'data/out/city-northwest/segments.geojson.gz',
            'street_only':True,'score':round(result['score'],3)},'features':features}
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=1),encoding='utf8')
    # A bright polyline may join original consecutive source points only.
    pair = lambda a,b: tuple(sorted((tuple(a),tuple(b))))
    allowed = {pair([round(a[0]/KX,6),round(a[1]/KY,6)], [round(b[0]/KX,6),round(b[1]/KY,6)])
               for line,_,_ in st.edges for a,b in zip(line,line[1:])}
    for f in features:
        for line in f['geometry']['coordinates']:
            assert all(pair(a,b) in allowed for a,b in zip(line,line[1:])), 'Synthetic connection found'


def polish(st, result):
    pools=[]
    for f in result['letters']:
        ch=f['letter'];cx,cy,u,angle=f['pose']
        proposals=[]
        for scale in [.8,.95,1.1,1.25]:
            for dx in [-1.,-.5,0,.5,1.]:
                for dy in [-1.5,-.75,0,.75,1.5]:
                    for turn in [-30,-15,0,15,30]:
                        x,y=transform([[dx,dy]],cx,cy,u,angle)[0]
                        pose=[x,y,u*scale,angle+math.radians(turn)]
                        proposals.append((st.coarse(ch,*pose),pose))
        fits=[]
        for _,pose in sorted(proposals):
            fit=st.fit(ch,*pose)
            if fit is not None:
                fits.append(fit)
                if len(fits)==40:
                    break
        if not fits:
            raise RuntimeError('No readable '+ch+' at this placement; choose another candidate')
        pools.append(fits)
        print('polish pool',ch,len(fits),flush=True)
    (WORK/'polish-pools.json').write_text(json.dumps({'base':result,'pools':pools}),encoding='utf8')
    return compose(result,pools)


def compose(result,pools):
    c,s=math.cos(result['angle']),math.sin(result['angle'])
    def span(f):
        xs=[p[0]*c+p[1]*s for line in f['lines'] for p in line]
        return min(xs),max(xs)
    for overlap_share in [.15,.25,.35]:
        beam=[(0.,[],None)]
        for pool in pools:
            following=[]
            for score,chosen,prior in beam:
                for f in pool:
                    left,right=span(f)
                    penalty=0
                    if prior:
                        pl,pr=prior
                        overlap=max(0,pr-left)
                        if overlap>min(pr-pl,right-left)*overlap_share:
                            continue
                        penalty=3*overlap/max(1,f['pose'][2])
                    following.append((score+f['score']+penalty,chosen+[f],(left,right)))
            beam=sorted(following,key=lambda x:x[0])[:100]
            if not beam:
                break
        if beam:
            score,letters,_=beam[0]
            print('layout overlap allowed',overlap_share,flush=True)
            return {**result,'letters':letters,'score':score}
    raise RuntimeError('Letters still collide too much; choose a different placement')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['search','render','draft','polish','compose'])
    parser.add_argument('--pick',type=int,default=0)
    parser.add_argument('--region',choices=['all','centre','south','northwest','northeast'],default='all')
    args=parser.parse_args()
    st=Streets()
    WORK.mkdir(parents=True,exist_ok=True)
    if args.phase=='draft':
        data=json.loads((ROOT/'web/pitch/bezna-streets.json').read_text(encoding='utf8'))
        result={'angle':0,'letters':[{'letter':f['properties']['letter'],'lines':[[(p[0]*KX,p[1]*KY) for p in line] for line in f['geometry']['coordinates']]} for f in data['features']]}
        render(st,result,WORK/'claude-draft.png')
        return
    if args.phase=='search':
        results=[]
        for region,lon,lat in [('centre',21.229,45.756),('south',21.226,45.745),('northwest',21.215,45.762),('northeast',21.247,45.763)]:
            if args.region != 'all' and args.region != region:
                continue
            results.extend(optimize(st,region,lon,lat))
        results.sort(key=lambda r:r['score'])
        if not results:
            raise RuntimeError('No legible complete word found in this street network')
        (WORK/'candidates.json').write_text(json.dumps(results),encoding='utf8')
        for i,result in enumerate(results):
            render(st,result,WORK/f'candidate-{i:02d}.png',size=(1200,675))
    else:
        results=json.loads((WORK/'candidates.json').read_text(encoding='utf8'))
    result=results[args.pick]
    if args.phase=='polish':
        result=polish(st,result)
        (WORK/'polished.json').write_text(json.dumps(result),encoding='utf8')
    if args.phase=='compose':
        cached=json.loads((WORK/'polish-pools.json').read_text(encoding='utf8'))
        result=compose(cached['base'],cached['pools'])
        (WORK/'polished.json').write_text(json.dumps(result),encoding='utf8')
    export(result,st)
    render(st,result,EXPORT/'title-streets.png')
    render(st,result,EXPORT/'app-icon-streets.png',size=(1024,1024),icon='B',caption=False)
    render(st,result,EXPORT/'app-icon-streets-192.png',size=(192,192),icon='B',caption=False)
    print('Selected',args.pick,result['region'],'score',round(result['score'],2),flush=True)


if __name__=='__main__':
    main()
