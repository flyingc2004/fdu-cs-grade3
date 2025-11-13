from datetime import datetime, timezone
import base64
import quopri
import re
from typing import List, Optional, Dict, Any, cast

# 标准库email用于解析和组装邮件
from email import message_from_string
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr

CRLF = "\r\n"

# RFC2047编码：用于主题等非ASCII头部
def encode_header(value: str, charset: str = 'utf-8') -> str:
    try:
        value.encode('ascii')
        return value  # 纯ASCII无需编码
    except UnicodeEncodeError:
        b = base64.b64encode(value.encode(charset)).decode('ascii')
        return f"=?{charset}?B?{b}?="

# 生成邮件头部的日期字段
def format_date(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    # 格式如：Sat, 25 Oct 2025 10:20:30 +0000
    return dt.astimezone().strftime('%a, %d %b %Y %H:%M:%S %z')

# 地址拼接
def join_addresses(addresses: List[str]) -> str:
    return ', '.join(addresses)

# 构造RFC5322格式邮件（头部+正文base64）
def build_message(sender: str, recipients: List[str], subject: str, body: str, cc: Optional[List[str]] = None, bcc: Optional[List[str]] = None) -> str:
    """
    组装MIME邮件（text/plain, base64编码）。
    """
    cc = cc or []
    bcc = bcc or []

    # Headers
    headers = [
        f"From: {sender}",
        f"To: {join_addresses(recipients)}",
    ]
    if cc:
        headers.append(f"Cc: {join_addresses(cc)}")
    headers.extend([
        f"Subject: {encode_header(subject)}",
        f"Date: {format_date()}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "Content-Transfer-Encoding: base64",
    ])
    # 正文base64编码，76字符换行
    body_b64 = base64.b64encode(body.encode('utf-8')).decode('ascii')
    body_wrapped = CRLF.join(re.findall(r'.{1,76}', body_b64))
    message = CRLF.join(headers) + CRLF + CRLF + body_wrapped + CRLF
    return message

# 解析.eml邮件，提取头部和正文
# 支持str和bytes输入，自动处理Windows换行问题
# 返回dict: from_email, from_name, to_list, cc_list, subject, body

def parse_message(raw: str | bytes) -> Dict[str, Any]:
    """
    解析RFC5322邮件，自动提取发件人、收件人、主题、正文。
    支持base64/quoted-printable编码，兼容多种格式。
    """
    if isinstance(raw, bytes):
        raw_bytes = raw.replace(b'\r\r\n', b'\r\n')
        try:
            raw_str = raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            raw_str = raw_bytes.decode('utf-8', errors='replace')
    else:
        raw_str = cast(str, raw).replace('\r\r\n', '\r\n')

    msg = message_from_string(raw_str)

    def dec_header(val: Optional[str]) -> str:
        if not val:
            return ''
        try:
            return str(make_header(decode_header(val)))
        except Exception:
            return val

    subj = dec_header(msg.get('Subject'))

    # 发件人
    from_raw = msg.get('From') or ''
    name, email = parseaddr(from_raw)
    from_name = dec_header(name) if name else ''
    from_email = email or ''

    # 收件人和抄送
    to_raw = msg.get('To') or ''
    cc_raw = msg.get('Cc') or ''
    def _extract_addresses(raw_value: str) -> List[str]:
        if not raw_value:
            return []
        # 逗号分隔，兼容body里误出现To:等行
        parts = [p.strip() for p in re.split(r',\s*', raw_value) if p.strip()]
        addresses: List[str] = []
        for part in parts:
            name, email = parseaddr(part)
            if email:
                addresses.append(email)
            else:
                if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', part):
                    addresses.append(part)
        return addresses

    to_list = _extract_addresses(to_raw)
    cc_list = _extract_addresses(cc_raw)

    # 正文提取（优先text/plain分部，兼容base64/qp编码）
    body_text = ''
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                if part.get_content_type() == 'text/plain':
                    p_bytes = part.get_payload(decode=True)
                    if p_bytes is None:
                        body_text = part.get_payload() or ''
                    else:
                        p_charset = part.get_content_charset() or 'utf-8'
                        try:
                            body_text = cast(bytes, p_bytes).decode(p_charset, errors='replace')
                        except Exception:
                            body_text = cast(bytes, p_bytes).decode('utf-8', errors='replace')
                    break
            if not body_text:
                try:
                    body_text = msg.get_body(preferencelist=('plain',)).get_content()  # type: ignore[attr-defined]
                except Exception:
                    body_text = ''
        else:
            body_bytes = msg.get_payload(decode=True)
            if body_bytes is None:
                body_text = msg.get_payload() or ''
            else:
                charset = msg.get_content_charset() or 'utf-8'
                try:
                    body_text = cast(bytes, body_bytes).decode(charset, errors='replace')
                except Exception:
                    body_text = cast(bytes, body_bytes).decode('utf-8', errors='replace')
    except Exception:
        body_text = ''

    # 手动兜底：按首个空行分头部/正文，按Content-Transfer-Encoding解码
    if not isinstance(body_text, str):
        body_text = ''
    try:
        header_part, body_part = '', ''
        parts = re.split(r"\r?\n\r?\n", raw_str, maxsplit=1)
        if len(parts) == 2:
            header_part, body_part = parts
        else:
            body_part = raw_str
        headers_map: Dict[str, str] = {}
        if header_part:
            unfolded: List[str] = []
            for line in header_part.splitlines():
                if line.startswith((' ', '\t')) and unfolded:
                    unfolded[-1] += ' ' + line.strip()
                else:
                    unfolded.append(line)
            for line in unfolded:
                if ':' in line:
                    k, v = line.split(':', 1)
                    headers_map[k.strip().lower()] = v.strip()
        # 补全头部信息
        if (not to_list) and (val := headers_map.get('to')):
            to_list = _extract_addresses(val)
        if (not cc_list) and (val := headers_map.get('cc')):
            cc_list = _extract_addresses(val)
        if not from_email and (val := headers_map.get('from')):
            name, email = parseaddr(val)
            from_name = dec_header(name) if name else from_name
            from_email = email or from_email
        if not subj and (val := headers_map.get('subject')):
            subj = dec_header(val)
        # 正文解码
        if (not body_text) or re.search(r"^\s*(?:to|subject|date|mime-version|content-type|content-transfer-encoding):", body_text, flags=re.I | re.M):
            cte = (headers_map.get('content-transfer-encoding') or '').lower()
            ctype = (headers_map.get('content-type') or '')
            charset = 'utf-8'
            m = re.search(r'charset\s*=\s*([\w\-]+)', ctype, flags=re.I)
            if m:
                charset = m.group(1)
            try:
                if cte == 'base64':
                    bb = base64.b64decode(body_part, validate=False)
                    body_text = bb.decode(charset, errors='replace')
                elif cte in ('quoted-printable', 'qp'):
                    bb = quopri.decodestring(body_part)
                    body_text = bb.decode(charset, errors='replace') if isinstance(bb, (bytes, bytearray)) else str(bb)
                else:
                    body_text = body_part
            except Exception:
                body_text = body_part
    except Exception:
        pass
    # 如果正文仍像头部，则清空，避免导入时粘贴整封邮件
    if body_text and re.match(r"^\s*(?:to|cc|subject|date|mime-version|content-type|content-transfer-encoding):", body_text.strip(), flags=re.I):
        body_text = ''
    return {
        'from_email': from_email,
        'from_name': from_name,
        'to_list': to_list,
        'cc_list': cc_list,
        'subject': subj,
        'body': body_text,
    }
