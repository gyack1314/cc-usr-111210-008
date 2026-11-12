"""核对网页留存原字节和选择配置。"""
from .io import asset,integer

def summarize(v,root):
    raw,digest=asset(root,v['source']);integer(v['max_parts'],1)
    if not raw.startswith(b'MIME-Version:'):raise ValueError('缺少MIME版本前导')
    return {'raw_bytes':len(raw),'sha256':digest,'preferred_types':v['preferred_types'],'base_url':v['base_url']}
