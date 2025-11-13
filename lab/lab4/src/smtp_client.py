import socket
import ssl
import base64
from typing import List, Tuple, Optional, Callable

CRLF = "\r\n"

# SMTP协议错误类，带响应码和消息
class SMTPError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"SMTP error {code}: {message}")
        self.code = code
        self.message = message

class SMTPClient:
    """
    基于socket实现的最小SMTP客户端。
    支持：
    - EHLO/HELO 握手
    - STARTTLS（587端口显式TLS升级）
    - AUTH LOGIN认证
    - MAIL FROM/RCPT TO（支持群发）
    - DATA发送邮件内容
    - QUIT安全退出
    """
    def __init__(self, host: str, port: int = 587, timeout: float = 20.0, use_ssl: bool = False, debug: bool = False, logger: Optional[Callable[[str], None]] = None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.use_ssl = use_ssl
        self.debug = debug
        self.logger = logger
        self.sock: socket.socket | ssl.SSLSocket | None = None
        self.file = None  # 用于按行读取响应

    # --- 低层socket操作 ---
    def _connect(self):
        # 建立TCP连接，必要时升级为SSL
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.use_ssl:
            context = ssl.create_default_context()
            self.sock = context.wrap_socket(raw, server_hostname=self.host)
        else:
            self.sock = raw
        # 包装为文件对象，方便按行读取
        self.file = self.sock.makefile('rb')  # type: ignore
        code, msg = self._read_response()
        if code != 220:
            raise SMTPError(code, msg)

    def _starttls(self):
        # 启动TLS加密
        self._send_cmd("STARTTLS")
        code, msg = self._read_response()
        if code != 220:
            raise SMTPError(code, msg)
        assert isinstance(self.sock, socket.socket)
        context = ssl.create_default_context()
        self.sock = context.wrap_socket(self.sock, server_hostname=self.host)
        self.file = self.sock.makefile('rb')  # type: ignore

    def _sendline(self, data: str):
        # 发送一行SMTP命令（自动加CRLF）
        assert self.sock is not None
        if not data.endswith(CRLF):
            data += CRLF
        if self.debug:
            printable = data[:-2] if data.endswith(CRLF) else data
            self._log(f"C: {printable}")
        self.sock.sendall(data.encode('utf-8'))

    def _send_sensitive_line(self, hint: str = "<redacted>"):
        """发送敏感内容（如base64用户名/密码），日志只显示提示。"""
        if self.debug:
            self._log(f"C: {hint}")

    def _log(self, msg: str):
        # 日志输出（可重定向到GUI/CLI）
        if not self.debug:
            return
        try:
            if self.logger:
                self.logger(msg)
            else:
                print(msg)
        except Exception:
            pass

    def _send_cmd(self, cmd: str):
        self._sendline(cmd)

    def _read_response(self) -> Tuple[int, str]:
        """
        读取SMTP响应，自动处理多行回复。
        返回(code, message)。
        """
        assert self.file is not None
        lines: List[bytes] = []
        while True:
            line = self.file.readline()
            if not line:
                raise ConnectionError("服务器关闭连接")
            lines.append(line.rstrip(b"\r\n"))
            if self.debug:
                try:
                    self._log(f"S: {line.decode('utf-8', errors='replace').rstrip()}")
                except Exception:
                    pass
            if len(line) < 4:
                break
            try:
                code = int(line[:3])
            except ValueError:
                break
            # 多行响应以'-'分隔，最后一行是空格
            if line[3:4] == b' ':
                break
        message = b"\n".join(lines).decode('utf-8', errors='replace')
        try:
            code = int(lines[-1][:3])
        except Exception:
            code = -1
        return code, message

    # --- SMTP协议流程 ---
    def ehlo_or_helo(self, hostname: str = 'localhost'):
        # 发送EHLO（优先）或HELO（兼容老服务器）
        self._send_cmd(f"EHLO {hostname}")
        code, msg = self._read_response()
        if code != 250:
            # EHLO失败，尝试HELO
            self._send_cmd(f"HELO {hostname}")
            code, msg = self._read_response()
            if code != 250:
                raise SMTPError(code, msg)
        return msg

    def login_auth_login(self, username: str, password: str):
        # AUTH LOGIN认证流程（base64编码用户名和密码）
        self._send_cmd("AUTH LOGIN")
        code, msg = self._read_response()
        if code != 334:
            raise SMTPError(code, msg)
        u = base64.b64encode(username.encode('utf-8')).decode('ascii')
        # 发送用户名，避免打印真实内容
        assert self.sock is not None
        if self.debug:
            self._send_sensitive_line("<base64(username)> [redacted]")
        self.sock.sendall((u + CRLF).encode('utf-8'))
        code, msg = self._read_response()
        if code != 334:
            raise SMTPError(code, msg)
        p = base64.b64encode(password.encode('utf-8')).decode('ascii')
        if self.debug:
            self._send_sensitive_line("<base64(password)> [redacted]")
        self.sock.sendall((p + CRLF).encode('utf-8'))
        code, msg = self._read_response()
        if code != 235:
            raise SMTPError(code, msg)

    def mail_from(self, sender: str):
        # 指定发件人
        self._send_cmd(f"MAIL FROM:<{sender}>")
        code, msg = self._read_response()
        if code != 250:
            raise SMTPError(code, msg)

    def rcpt_to(self, recipients: List[str]):
        # 指定收件人（支持群发）
        for rcpt in recipients:
            self._send_cmd(f"RCPT TO:<{rcpt}>")
            code, msg = self._read_response()
            if code not in (250, 251):
                raise SMTPError(code, msg)

    def data(self, message: str):
        # 发送邮件内容（DATA阶段，正文+头部）
        self._send_cmd("DATA")
        code, msg = self._read_response()
        if code != 354:
            raise SMTPError(code, msg)
        # dot-stuffing处理，确保以.开头的行加一个点
        message_bytes = message.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        out_lines: List[str] = []
        for line in message_bytes:
            if line.startswith('.'):
                out_lines.append('.' + line)
            else:
                out_lines.append(line)
        final = CRLF.join(out_lines) + CRLF + "." + CRLF
        self._sendline(final)
        code, msg = self._read_response()
        if code != 250:
            raise SMTPError(code, msg)

    def quit(self):
        # 发送QUIT安全退出
        try:
            self._send_cmd("QUIT")
            try:
                self._read_response()
            except Exception:
                pass
        finally:
            try:
                if self.file:
                    self.file.close()
            except Exception:
                pass
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass

    # --- 主入口 ---
    def send_email(self, username: str, password: str, sender: str, recipients: List[str], message: str, helo_host: str = 'localhost'):
        """
        连接并发送一封邮件（RFC5322格式），支持群发/抄送。
        """
        self._connect()
        try:
            self.ehlo_or_helo(helo_host)
            if not self.use_ssl and self.port == 587:
                # 587端口需先EHLO再STARTTLS升级
                self._starttls()
                self.ehlo_or_helo(helo_host)
            self.login_auth_login(username, password)
            self.mail_from(sender)
            self.rcpt_to(recipients)
            self.data(message)
        finally:
            self.quit()
