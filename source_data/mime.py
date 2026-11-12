"""MIME层级解析：合法边界行、折叠头、传输解码与原字节范围。

边界只按完整分隔行识别（--boundary或--boundary--，可带空白尾垫），
不在正文子串处切分；message/rfc822作为不透明叶部件，不展开其内部头。
"""
import base64,binascii,hashlib,quopri,re

MAX_DEPTH=24
HEADER_RE=re.compile(rb'^[!-9;-~]+:')

def msg_id(value):
    """Content-ID或start参数去外部尖括号，保持大小写。"""
    v=value.strip()
    if len(v)>=2 and v.startswith('<') and v.endswith('>'):return v[1:-1]
    return v

class _Limits:
    def __init__(self,max_parts,max_decoded):
        self.max_parts=max_parts;self.max_decoded=max_decoded
        self.count=0;self.decoded=0
    def part(self):
        self.count+=1
        if self.count>self.max_parts:raise ValueError('部件数超过max_parts')
    def bytes(self,n):
        self.decoded+=n
        if self.decoded>self.max_decoded:raise ValueError('解码字节超过max_decoded_bytes')

def _lines(raw):
    """切行，返回(行首,内容尾,下一行行首)；行尾识别CRLF或LF。"""
    out=[];i=0;n=len(raw)
    while i<n:
        j=raw.find(b'\n',i)
        if j<0:out.append((i,n,n));break
        out.append((i,j-1 if j>i and raw[j-1]==13 else j,j+1));i=j+1
    return out

def _delimiter(content,boundary):
    """整行恰为--boundary或--boundary--（允许空白尾垫）才算分隔行。"""
    if not content.startswith(b'--'+boundary):return None
    rest=content[2+len(boundary):];kind='open'
    if rest.startswith(b'--'):kind='close';rest=rest[2:]
    if all(c in (32,9) for c in rest):return kind
    return None

def _headers(raw,lines,a,b,notes):
    """解析[a,b)行区为头字典；续行展开并留痕，重复头取首值。"""
    hs=[]
    for k in range(a,b):
        c=raw[lines[k][0]:lines[k][1]]
        if c[:1] in (b' ',b'\t'):
            if hs:hs[-1][1]+=c;hs[-1][2]=True
            else:notes.append('首行前出现续行@%d'%lines[k][0])
            continue
        if not HEADER_RE.match(c):notes.append('无法识别的头行@%d'%lines[k][0]);continue
        name,value=c.split(b':',1)
        hs.append([name.decode('ascii').lower(),value,False])
    out={}
    for name,value,folded in hs:
        if folded:notes.append('展开折叠头:'+name)
        if name in out:notes.append('重复头取首值:'+name)
        else:out[name]=value.decode('latin-1').strip(' \t')
    return out

def _params(value,notes):
    """拆分主类型与参数；引号串内分号保留，反斜杠转义还原。"""
    segs=[];buf=[];quote=False;i=0
    while i<len(value):
        c=value[i]
        if quote:
            if c=='\\' and i+1<len(value):buf.append(value[i+1]);i+=2;continue
            if c=='"':quote=False;i+=1;continue
            buf.append(c);i+=1;continue
        if c=='"':quote=True;i+=1;continue
        if c==';':segs.append(''.join(buf));buf=[];i+=1;continue
        buf.append(c);i+=1
    if quote:notes.append('引号未闭合')
    segs.append(''.join(buf))
    params={}
    for seg in segs[1:]:
        if '=' not in seg:
            if seg.strip():notes.append('忽略无值参数:'+seg.strip()[:40])
            continue
        k,v=seg.split('=',1);k=k.strip().lower()
        if k in params:notes.append('重复参数取首值:'+k);continue
        params[k]=v.strip()
    return segs[0].strip().lower(),params

def _decode(body,cte,notes):
    if cte in (None,'7bit','8bit','binary'):return body
    if cte=='base64':
        cleaned=bytes(c for c in body if c not in b' \t\r\n')
        try:return base64.b64decode(cleaned,validate=True)
        except binascii.Error:
            notes.append('base64按宽松方式解码')
            return base64.b64decode(cleaned+b'='*(-len(cleaned)%4),validate=False)
    if cte=='quoted-printable':return quopri.decodestring(body)
    notes.append('未知传输编码按原样留存:'+cte)
    return body

def parse(raw,max_parts,max_decoded):
    """解析整篇报文，返回(部件列表,叶部件解码字节映射)。

    部件含id/parent/content_type/params/content_id/content_location/
    content_base/transfer_encoding/mime_range/body_range/children/decoded/
    opaque/notes；multipart递归有深度上限，关联扫描均为线性保证终止。
    """
    limits=_Limits(max_parts,max_decoded)
    lines=_lines(raw);parts=[];decoded={}

    def scan(a,b,boundary,notes):
        """在[a,b)行区内按boundary扫描子部件行区，遇闭合行或区尾结束。"""
        kids=[];start=None;k=a
        while k<b:
            c=raw[lines[k][0]:lines[k][1]]
            d=_delimiter(c,boundary)
            if d=='open':
                if start is not None:kids.append((start,k))
                start=k+1
            elif d=='close':
                if start is not None:kids.append((start,k))
                return kids
            elif c.startswith(b'--'+boundary):
                notes.append('忽略疑似边界行@%d'%lines[k][0])
            k+=1
        if start is not None:
            kids.append((start,b));notes.append('缺少闭合边界行,按区尾截断')
        return kids

    def entity(a,b,mime_start,mime_end,parent,depth):
        notes=[];pid='p%d'%len(parts);limits.part()
        blank=None
        for k in range(a,b):
            if raw[lines[k][0]:lines[k][1]]==b'':blank=k;break
        if blank is not None:
            headers=_headers(raw,lines,a,blank,notes);body_first=blank+1
        else:
            probe=[raw[lines[k][0]:lines[k][1]] for k in range(a,b)]
            ok=bool(probe)
            for idx,c in enumerate(probe):
                if HEADER_RE.match(c):continue
                if idx>0 and c[:1] in (b' ',b'\t'):continue
                ok=False;break
            if ok:headers=_headers(raw,lines,a,b,notes);body_first=b
            else:headers={};notes.append('缺少头尾空行,区域按正文留存');body_first=a
        if body_first<b:bs,be=lines[body_first][0],lines[b-1][1]
        else:bs=be=mime_end
        ct=headers.get('content-type')
        if ct is None:main,params='text/plain',{};notes.append('缺省Content-Type按text/plain')
        else:
            main,params=_params(ct,notes)
            if '/' not in main:
                notes.append('Content-Type无法识别按不透明留存:'+main[:40])
                main,params='application/octet-stream',{}
        cte=headers.get('content-transfer-encoding')
        cte=cte.strip().lower() if cte else None
        part={'id':pid,'parent':parent,'content_type':main,'params':params,
              'content_id':msg_id(headers['content-id']) if 'content-id' in headers else None,
              'content_location':headers.get('content-location') or None,
              'content_base':headers.get('content-base') or None,
              'transfer_encoding':cte,'mime_range':[mime_start,mime_end],
              'body_range':[bs,be],'children':None,'decoded':None,
              'resolved_location':None,'opaque':False,'notes':notes}
        parts.append(part)
        if main.startswith('multipart/'):
            boundary=params.get('boundary');bb=None
            if not boundary:notes.append('multipart缺少boundary,按不透明部件留存')
            elif depth>=MAX_DEPTH:notes.append('嵌套深度超限,按不透明部件留存')
            elif cte not in (None,'7bit','8bit','binary'):notes.append('multipart带传输编码,按不透明部件留存')
            else:
                try:bb=boundary.encode('ascii')
                except UnicodeEncodeError:notes.append('boundary非ASCII,按不透明部件留存')
            if bb is None:part['opaque']=True
            else:
                kids=[]
                for ka,kb in scan(body_first,b,bb,notes):
                    kids.append(entity(ka,kb,lines[ka][0],lines[kb][0] if kb<len(lines) else len(raw),pid,depth+1))
                part['children']=kids
                return pid
        data=_decode(raw[bs:be],cte,notes)
        limits.bytes(len(data));decoded[pid]=data
        part['decoded']={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
        if main=='message/rfc822':part['opaque']=True
        return pid

    entity(0,len(lines),0,len(raw),None,0)
    return parts,decoded
