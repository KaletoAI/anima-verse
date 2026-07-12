"""UV-Reparatur v2: Dreieck-zu-Dreieck-Matching (identische Topologie),
danach Ecken-Zuordnung innerhalb des Dreiecks. Eliminiert Naht-Ambiguität."""
import json, struct, sys
import numpy as np
from scipy.spatial import cKDTree
from itertools import permutations, product

def read_glb(path):
    data = open(path, 'rb').read()
    ln = struct.unpack('<I', data[12:16])[0]
    j = json.loads(data[20:20+ln])
    off = 20 + ln
    blen = struct.unpack('<I', data[off:off+4])[0]
    return j, bytearray(data[off+8:off+8+blen])

def acc_arr(j, b, idx):
    acc = j['accessors'][idx]
    bv = j['bufferViews'][acc['bufferView']]
    dt = {5126:('<f4',4),5123:('<u2',2),5125:('<u4',4),5121:('<u1',1)}[acc['componentType']]
    n = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[acc['type']]
    s = bv.get('byteOffset',0)+acc.get('byteOffset',0)
    return np.frombuffer(bytes(b[s:s+acc['count']*n*dt[1]]), dtype=dt[0]).reshape(acc['count'],n), (s, acc['count']*n*dt[1])

src_j, src_bin = read_glb(sys.argv[1])
dst_j, dst_bin = read_glb(sys.argv[2])

# Aufruf: fix-rig-uv.py <texturiert.glb> <gerigged.glb> <out.glb>
# (3 Argumente: baseColor wird aus dem texturierten GLB extrahiert;
#  4 Argumente wie bisher: ... <basecolor.png> <out.glb>)
if len(sys.argv) == 4:
    bct = src_j['materials'][0]['pbrMetallicRoughness']['baseColorTexture']['index']
    bv = src_j['bufferViews'][src_j['images'][src_j['textures'][bct]['source']]['bufferView']]
    png_bytes = bytes(src_bin[bv.get('byteOffset',0):bv.get('byteOffset',0)+bv['byteLength']])
    out_path = sys.argv[3]
else:
    png_bytes = open(sys.argv[3], 'rb').read()
    out_path = sys.argv[4]
sp = src_j['meshes'][0]['primitives'][0]
dp = dst_j['meshes'][0]['primitives'][0]
s_pos,_ = acc_arr(src_j, src_bin, sp['attributes']['POSITION'])
s_uv,_  = acc_arr(src_j, src_bin, sp['attributes']['TEXCOORD_0'])
s_idx,_ = acc_arr(src_j, src_bin, sp['indices']); s_idx = s_idx.reshape(-1,3).astype(np.int64)
d_pos,_ = acc_arr(dst_j, dst_bin, dp['attributes']['POSITION'])
d_idx,_ = acc_arr(dst_j, dst_bin, dp['indices']); d_idx = d_idx.reshape(-1,3).astype(np.int64)
_, (uv_start, uv_len) = acc_arr(dst_j, dst_bin, dp['attributes']['TEXCOORD_0'])

# Achsen-Ausrichtung dst->src automatisch
tree_v = cKDTree(s_pos)
sample = d_pos[np.random.RandomState(0).choice(len(d_pos), 3000, replace=False)]
smin, smax = s_pos.min(0), s_pos.max(0)
best = None
for perm in permutations(range(3)):
    for signs in product((1,-1), repeat=3):
        cand = sample[:, perm]*np.array(signs)
        cmin,cmax = cand.min(0), cand.max(0)
        sc = ((cmax-cmin)/np.maximum(smax-smin,1e-9)).mean()
        if not (0.1 < sc < 10): continue
        t = (cmin+cmax)/2 - ((smin+smax)/2)*sc
        d,_ = tree_v.query((cand-t)/sc, k=1)
        if best is None or d.mean() < best[0]: best = (d.mean(), perm, signs)
print('Ausrichtung:', best[1], best[2], f'{best[0]:.5f}')
perm, signs = best[1], best[2]
aligned = d_pos[:, perm]*np.array(signs)
amin,amax = aligned.min(0), aligned.max(0)
sc = ((amax-amin)/np.maximum(smax-smin,1e-9)).mean()
t = (amin+amax)/2 - ((smin+smax)/2)*sc
d_al = (aligned - t)/sc

# Dreieck-Matching über Zentroiden
s_cent = s_pos[s_idx].mean(axis=1)
d_cent = d_al[d_idx].mean(axis=1)
tree_f = cKDTree(s_cent)
fd, fmap = tree_f.query(d_cent, k=1)
print(f'Face-Matching: mean={fd.mean():.6f} max={fd.max():.6f} | eindeutig: {len(np.unique(fmap))}/{len(fmap)}')

# Ecken innerhalb des Dreiecks zuordnen, UV pro dst-Vertex setzen
new_uv = np.zeros((len(d_pos),2), dtype='<f4')
s_tri_pos = s_pos[s_idx[fmap]]          # (F,3,3)
s_tri_uv  = s_uv[s_idx[fmap]]           # (F,3,2)
d_tri_pos = d_al[d_idx]                 # (F,3,3)
# Distanzmatrix je Face: (F,3dst,3src)
dm = np.linalg.norm(d_tri_pos[:,:,None,:] - s_tri_pos[:,None,:,:], axis=-1)
corner = dm.argmin(axis=2)              # (F,3)
for c in range(3):
    new_uv[d_idx[:,c]] = s_tri_uv[np.arange(len(fmap)), corner[:,c]]
dst_bin[uv_start:uv_start+uv_len] = new_uv.tobytes()

# Weight-Welding: positionsgleiche Vertices (UV-Naht-Duplikate) bekommen
# identische, gemittelte Skinning-Gewichte — behebt "klebende" Vertices an
# Naehten (Ellenbogen/Knie/Fuesse), da MIA Duplikate unabhaengig gewichtet.
ja = dp['attributes'].get('JOINTS_0')
wa = dp['attributes'].get('WEIGHTS_0')
if ja is not None and wa is not None:
    joints, (j_start, j_len) = acc_arr(dst_j, dst_bin, ja)
    weights, (w_start, w_len) = acc_arr(dst_j, dst_bin, wa)
    joints = joints.copy(); weights = weights.copy()
    key = np.round(d_pos * 1e5).astype(np.int64)
    _, inv, counts = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    welded = 0
    from collections import defaultdict
    groups = defaultdict(list)
    for vi, gi in enumerate(inv):
        if counts[gi] > 1:
            groups[gi].append(vi)
    for vids in groups.values():
        acc = {}
        for v in vids:
            for j, w in zip(joints[v], weights[v]):
                if w > 0: acc[int(j)] = acc.get(int(j), 0.0) + float(w)
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:4]
        total = sum(w for _, w in top) or 1.0
        jj = [j for j, _ in top] + [0] * (4 - len(top))
        ww = [w / total for _, w in top] + [0.0] * (4 - len(top))
        for v in vids:
            joints[v] = jj
            weights[v] = ww
        welded += len(vids)
    j_dt = {5126:'<f4',5123:'<u2',5125:'<u4',5121:'<u1'}[dst_j['accessors'][ja]['componentType']]
    dst_bin[j_start:j_start+j_len] = joints.astype(j_dt).tobytes()
    dst_bin[w_start:w_start+w_len] = weights.astype('<f4').tobytes()
    print(f'Weight-Welding: {welded} Naht-Vertices in {len(groups)} Gruppen vereinheitlicht')

# Textur einbetten + Material aufhellen
png = png_bytes
img_bv = dst_j['images'][0]['bufferView']
chunks = []; offset = 0
for i,bv in enumerate(dst_j['bufferViews']):
    chunk = png if i==img_bv else bytes(dst_bin[bv.get('byteOffset',0):bv.get('byteOffset',0)+bv['byteLength']])
    bv['byteOffset']=offset; bv['byteLength']=len(chunk)
    pad=(4-len(chunk)%4)%4
    chunks.append(chunk+b'\x00'*pad); offset+=len(chunk)+pad
nb=b''.join(chunks)
dst_j['buffers'][0]['byteLength']=len(nb)
dst_j['images'][0]['mimeType']='image/png'
for m in dst_j.get('materials',[]):
    m.get('pbrMetallicRoughness',{})['baseColorFactor']=[1,1,1,1]
jb=json.dumps(dst_j,separators=(',',':')).encode(); jb+=b' '*((4-len(jb)%4)%4)
out=b'glTF'+struct.pack('<II',2,12+8+len(jb)+8+len(nb))
out+=struct.pack('<I',len(jb))+b'JSON'+jb+struct.pack('<I',len(nb))+b'BIN\x00'+nb
open(out_path,'wb').write(out)
print('geschrieben:', out_path, len(out))
