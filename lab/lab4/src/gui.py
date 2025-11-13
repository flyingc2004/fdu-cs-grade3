import threading
import tkinter as tk
from tkinter import ttk, messagebox
import os
from tkinter.scrolledtext import ScrolledText
from pathlib import Path
from datetime import datetime

from composer import build_message, parse_message
from smtp_client import SMTPClient

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
DRAFTS_DIR = DATA_DIR / 'drafts'
SENT_DIR = DATA_DIR / 'sent'

# 主窗口类，负责整个GUI应用
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('SMTP 客户端（Socket + STARTTLS + AUTH LOGIN）')
        self.geometry('900x640')
        self._build_ui()  # 构建界面

    # 构建所有UI控件和布局
    def _build_ui(self):
        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # SMTP服务器设置区
        sfrm = ttk.LabelFrame(frm, text='服务器设置')
        sfrm.pack(fill=tk.X, pady=4)

        ttk.Label(sfrm, text='SMTP主机:').grid(row=0, column=0, sticky='e', padx=4, pady=2)
        self.smtp_host = ttk.Entry(sfrm, width=24)
        self.smtp_host.grid(row=0, column=1, sticky='w', padx=4, pady=2)
        self.smtp_host.insert(0, 'smtp.qq.com')

        ttk.Label(sfrm, text='端口:').grid(row=0, column=2, sticky='e', padx=4, pady=2)
        self.smtp_port = ttk.Entry(sfrm, width=8)
        self.smtp_port.grid(row=0, column=3, sticky='w', padx=4, pady=2)
        self.smtp_port.insert(0, '587')

        self.ssl_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(sfrm, text='SSL直连(465)', variable=self.ssl_var).grid(row=0, column=4, sticky='w', padx=8)

        ttk.Label(sfrm, text='HELO主机名:').grid(row=0, column=5, sticky='e', padx=4)
        self.helo_host = ttk.Entry(sfrm, width=18)
        self.helo_host.grid(row=0, column=6, sticky='w', padx=4)
        self.helo_host.insert(0, 'localhost')

        # 邮箱账号与鉴权区
        cfrm = ttk.LabelFrame(frm, text='账号与鉴权')
        cfrm.pack(fill=tk.X, pady=4)

        ttk.Label(cfrm, text='发件人(邮箱):').grid(row=0, column=0, sticky='e', padx=4, pady=2)
        self.sender = ttk.Entry(cfrm, width=32)
        self.sender.grid(row=0, column=1, sticky='w', padx=4, pady=2)

        ttk.Label(cfrm, text='显示发件用户名(可选):').grid(row=0, column=2, sticky='e', padx=4, pady=2)
        self.display_name = ttk.Entry(cfrm, width=28)
        self.display_name.grid(row=0, column=3, sticky='w', padx=4, pady=2)

        ttk.Label(cfrm, text='授权码/密码:').grid(row=0, column=4, sticky='e', padx=4, pady=2)
        self.password = ttk.Entry(cfrm, width=24, show='*')
        self.password.grid(row=0, column=5, sticky='w', padx=4, pady=2)

        # 收件人、抄送区
        efrm = ttk.LabelFrame(frm, text='收件信息')
        efrm.pack(fill=tk.X, pady=4)

        ttk.Label(efrm, text='收件人(To):').grid(row=0, column=0, sticky='e', padx=4, pady=2)
        self.to = ttk.Entry(efrm)
        self.to.grid(row=0, column=1, columnspan=5, sticky='we', padx=4, pady=2)
        efrm.columnconfigure(1, weight=1)

        ttk.Label(efrm, text='抄送(Cc):').grid(row=1, column=0, sticky='e', padx=4, pady=2)
        self.cc = ttk.Entry(efrm)
        self.cc.grid(row=1, column=1, columnspan=5, sticky='we', padx=4, pady=2)

        # 邮件内容区
        mfrm = ttk.LabelFrame(frm, text='邮件内容')
        mfrm.pack(fill=tk.BOTH, expand=True, pady=4)

        ttk.Label(mfrm, text='主题:').grid(row=0, column=0, sticky='e', padx=4, pady=2)
        self.subject = ttk.Entry(mfrm)
        self.subject.grid(row=0, column=1, sticky='we', padx=4, pady=2)
        mfrm.columnconfigure(1, weight=1)

        ttk.Label(mfrm, text='正文:').grid(row=1, column=0, sticky='ne', padx=4, pady=2)
        self.body = ScrolledText(mfrm, wrap=tk.WORD, height=14)
        self.body.grid(row=1, column=1, sticky='nsew', padx=4, pady=2)
        mfrm.rowconfigure(1, weight=1)

        # 操作按钮区
        bfrm = ttk.Frame(frm)
        bfrm.pack(fill=tk.X, pady=4)
        self.btn_send = ttk.Button(bfrm, text='发送', command=self.on_send)  # 发送邮件
        self.btn_send.pack(side=tk.LEFT, padx=4)
        self.btn_draft = ttk.Button(bfrm, text='保存草稿', command=self.on_save_draft)  # 保存草稿
        self.btn_draft.pack(side=tk.LEFT, padx=4)
        self.btn_open_drafts = ttk.Button(bfrm, text='打开草稿箱', command=self.on_open_drafts)  # 打开草稿箱
        self.btn_open_drafts.pack(side=tk.LEFT, padx=4)

        # 底部区域：草稿箱和日志
        bottom = ttk.Frame(frm)
        bottom.pack(fill=tk.BOTH, expand=True, pady=4)

        # 草稿箱列表区
        dfrm = ttk.LabelFrame(bottom, text='草稿箱 (.eml)')
        dfrm.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=4)
        dtop = ttk.Frame(dfrm)
        dtop.pack(fill=tk.X)
        self.btn_refresh_drafts = ttk.Button(dtop, text='刷新草稿', command=self.refresh_drafts)  # 刷新草稿列表
        self.btn_refresh_drafts.pack(side=tk.LEFT, padx=4)
        self.btn_import_draft = ttk.Button(dtop, text='导入选中草稿', command=self.import_selected_draft)  # 导入草稿
        self.btn_import_draft.pack(side=tk.LEFT, padx=4)
        self.drafts_list = tk.Listbox(dfrm, height=10, width=32)
        self.drafts_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.drafts_list.bind('<Double-1>', lambda e: self.import_selected_draft())  # 双击导入
        self.refresh_drafts()  # 初始化草稿列表

        # SMTP日志区，显示命令与响应
        lfrm = ttk.LabelFrame(bottom, text='SMTP 日志 (C:/S: 命令与响应)')
        lfrm.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log = ScrolledText(lfrm, wrap=tk.WORD, height=10, state=tk.NORMAL)
        self.log.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # 日志区追加内容
    def append_log(self, text: str):
        self.log.insert(tk.END, text + '\n')
        self.log.see(tk.END)

    # 切换UI控件可用/禁用（发送时防止误操作）
    def _toggle_ui(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in [self.smtp_host, self.smtp_port, self.helo_host, self.sender, self.display_name, self.password, self.to, self.cc, self.subject, self.body, self.btn_send, self.btn_draft, self.btn_open_drafts, self.drafts_list]:
            try:
                w.configure(state=state)
            except Exception:
                pass

    # 保存草稿事件处理
    def on_save_draft(self):
        sender = self.sender.get().strip()
        recipients = [r.strip() for r in self.to.get().split(',') if r.strip()]
        cc = [r.strip() for r in self.cc.get().split(',') if r.strip()]
        subject = self.subject.get()
        body = self.body.get('1.0', tk.END).rstrip('\n')
        display_name = self.display_name.get().strip()

        if not sender or not recipients:
            messagebox.showwarning('提示', '请填写发件人和至少一个收件人(To)。')
            return

        header_sender = f"{display_name} <{sender}>" if display_name else sender
        msg = build_message(header_sender, recipients, subject, body, cc=cc)
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        path = DRAFTS_DIR / f"draft_{Path(sender).stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}.eml"
        path.write_bytes(msg.encode('utf-8'))
        messagebox.showinfo('草稿已保存', str(path))

    # 打开草稿箱（Windows下用资源管理器打开）
    def on_open_drafts(self):
        try:
            DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
            # On Windows, os.startfile opens Explorer
            if hasattr(os, 'startfile'):
                os.startfile(str(DRAFTS_DIR))
            else:
                # Fallback for other OS if needed
                messagebox.showinfo('草稿箱路径', str(DRAFTS_DIR))
        except Exception as e:
            messagebox.showerror('无法打开草稿箱', str(e))

    # 发送邮件事件处理（多线程防止卡死UI）
    def on_send(self):
        # 收集输入
        smtp_host = self.smtp_host.get().strip() or 'smtp.qq.com'
        try:
            smtp_port = int(self.smtp_port.get().strip() or '587')
        except ValueError:
            messagebox.showerror('错误', '端口必须是数字')
            return
        use_ssl = bool(self.ssl_var.get())
        helo_host = self.helo_host.get().strip() or 'localhost'

        sender = self.sender.get().strip()
        display_name = self.display_name.get().strip()
        password = self.password.get()
        recipients = [r.strip() for r in self.to.get().split(',') if r.strip()]
        cc = [r.strip() for r in self.cc.get().split(',') if r.strip()]
        subject = self.subject.get()
        body = self.body.get('1.0', tk.END).rstrip('\n')

        if not (sender and recipients and password):
            messagebox.showwarning('提示', '请至少填写 发件人、收件人(To) 和 授权码/密码。')
            return

        header_sender = f"{display_name} <{sender}>" if display_name else sender
        message = build_message(header_sender, recipients, subject, body, cc=cc)

        # 邮件发送线程，避免阻塞主界面
        def worker():
            self._toggle_ui(False)
            self.append_log('开始发送...\n')
            try:
                client = SMTPClient(host=smtp_host, port=smtp_port, use_ssl=use_ssl, debug=True, logger=self.append_log)
                client.send_email(
                    username=sender,
                    password=password,
                    sender=sender,
                    recipients=recipients + cc,
                    message=message,
                    helo_host=helo_host,
                )
                self.append_log('发送完成。')
                SENT_DIR.mkdir(parents=True, exist_ok=True)
                (SENT_DIR / 'last_sent.eml').write_bytes(message.encode('utf-8'))
                self.after(0, lambda: messagebox.showinfo('成功', '邮件发送成功。'))
            except Exception as e:
                self.append_log(f'错误: {e}')
                self.after(0, lambda: messagebox.showerror('发送失败', str(e)))
            finally:
                self._toggle_ui(True)

        threading.Thread(target=worker, daemon=True).start()

    # 刷新草稿箱列表
    def refresh_drafts(self):
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            files = sorted(DRAFTS_DIR.glob('*.eml'), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            files = list(DRAFTS_DIR.glob('*.eml'))
        self._draft_paths = files
        self.drafts_list.delete(0, tk.END)
        for p in files:
            self.drafts_list.insert(tk.END, p.name)

    # 导入选中草稿到编辑区
    def import_selected_draft(self):
        sel = self.drafts_list.curselection()
        if not sel:
            messagebox.showinfo('提示', '请选择一封草稿(.eml)。')
            return
        idx = sel[0]
        path = self._draft_paths[idx]
        try:
            raw_bytes = path.read_bytes()
        except Exception as e:
            messagebox.showerror('读取失败', str(e))
            return
        # 解析邮件内容并填充到编辑区
        try:
            info = parse_message(raw_bytes)
            # 填充各字段
            self.sender.delete(0, tk.END)
            self.sender.insert(0, info.get('from_email', ''))
            self.display_name.delete(0, tk.END)
            self.display_name.insert(0, info.get('from_name', ''))
            self.to.delete(0, tk.END)
            self.to.insert(0, ','.join(info.get('to_list', [])))
            self.cc.delete(0, tk.END)
            self.cc.insert(0, ','.join(info.get('cc_list', [])))
            self.subject.delete(0, tk.END)
            self.subject.insert(0, info.get('subject', ''))
            self.body.delete('1.0', tk.END)
            self.body.insert('1.0', info.get('body', ''))
            messagebox.showinfo('已导入', f'已导入草稿：{path.name}')
        except Exception as e:
            messagebox.showerror('解析失败', f'{path.name}: {e}')

# 程序入口
if __name__ == '__main__':
    app = App()
    app.mainloop()
