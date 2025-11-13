import argparse
import json
from pathlib import Path
from typing import List
import getpass

from composer import build_message
from smtp_client import SMTPClient

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
DRAFTS_DIR = DATA_DIR / 'drafts'
SENT_DIR = DATA_DIR / 'sent'
ADDRESS_BOOK = ROOT / 'address_book.json'

# 加载本地通讯录（JSON文件）
def load_address_book() -> List[str]:
    if not ADDRESS_BOOK.exists():
        return []
    try:
        data = json.loads(ADDRESS_BOOK.read_text(encoding='utf-8'))
        return [c for c in data.get('contacts', [])]
    except Exception:
        return []

# 保存通讯录
def save_address_book(contacts: List[str]):
    ADDRESS_BOOK.write_text(json.dumps({"contacts": contacts}, ensure_ascii=False, indent=2), encoding='utf-8')

# 交互式编辑主题和正文（命令行输入）
def interactive_edit(subject: str | None, body: str | None) -> tuple[str, str]:
    if subject is None:
        subject = input('主题: ').strip()
    if body is None:
        print('请输入正文，结束请输入单独一行的 "."：')
        lines: List[str] = []
        while True:
            line = input()
            if line == '.':
                break
            lines.append(line)
        body = '\n'.join(lines)
    return subject, body

# 发送/保存邮件主流程
def cmd_send(args: argparse.Namespace):
    sender = args.sender
    recipients = [r.strip() for r in args.to.split(',') if r.strip()]
    cc = [r.strip() for r in (args.cc or '').split(',') if r.strip()]
    subject, body = interactive_edit(args.subject, args.body)

    message = build_message(sender, recipients, subject, body, cc=cc)
    if args.save_draft:
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        draft_path = DRAFTS_DIR / f"draft_{Path(sender).stem}.eml"
        draft_path.write_bytes(message.encode('utf-8'))
        print(f"已保存草稿: {draft_path}")
        return

    client = SMTPClient(host=args.smtp_host, port=args.smtp_port, use_ssl=args.ssl, debug=args.verbose)
    client.send_email(
        username=args.username or sender,
        password=args.password,
        sender=sender,
        recipients=recipients + cc,
        message=message,
        helo_host=args.helo_host,
    )
    print('邮件发送成功。')
    if args.record_sent:
        SENT_DIR.mkdir(parents=True, exist_ok=True)
        (SENT_DIR / 'last_sent.eml').write_bytes(message.encode('utf-8'))

# 通讯录管理（list/add/remove）
def cmd_contacts(args: argparse.Namespace):
    contacts = load_address_book()
    if args.action == 'list':
        if not contacts:
            print('通讯录为空。')
        else:
            for i, c in enumerate(contacts, 1):
                print(f"{i}. {c}")
    elif args.action == 'add':
        contacts.append(args.email)
        save_address_book(contacts)
        print('已添加。')
    elif args.action == 'remove':
        contacts = [c for c in contacts if c != args.email]
        save_address_book(contacts)
        print('已删除。')

# --- 交互式菜单模式 ---
def interactive_menu():
    """
    交互式菜单：在无参数运行 cli.py 时进入。
    支持循环执行多项操作，直到用户选择退出。
    """
    def prompt(msg: str, default: str | None = None) -> str:
        tip = f"{msg}{' [' + default + ']' if default is not None else ''}: "
        s = input(tip).strip()
        return s if s else (default or '')

    def prompt_bool(msg: str, default: bool = False) -> bool:
        d = 'Y/n' if default else 'y/N'
        s = input(f"{msg} ({d}): ").strip().lower()
        if not s:
            return default
        return s in ('y', 'yes', '1', 'true')

    while True:
        print("\n=== SMTP CLI 菜单 ===")
        print("1) 发送邮件")
        print("2) 保存为草稿")
        print("3) 通讯录：查看")
        print("4) 通讯录：添加")
        print("5) 通讯录：删除")
        print("6) 退出")
        choice = input("请选择(1-6): ").strip()

        if choice == '1':
            # 发送邮件
            smtp_host = prompt('SMTP主机', 'smtp.qq.com')
            try:
                smtp_port = int(prompt('端口', '587'))
            except ValueError:
                print('端口必须是数字。')
                continue
            use_ssl = prompt_bool('SSL直连(465)?', False)
            helo_host = prompt('HELO主机名', 'localhost')
            verbose = prompt_bool('显示SMTP日志?', True)

            sender = prompt('发件人邮箱(同时作为登录用户)')
            if not sender:
                print('发件人不能为空。')
                continue
            username = prompt('登录用户名(留空=发件人)', sender) or sender
            password = getpass.getpass('授权码/密码: ').strip()
            if not password:
                print('授权码不能为空。')
                continue
            to = prompt('收件人(逗号分隔)')
            recipients = [r.strip() for r in to.split(',') if r.strip()]
            if not recipients:
                print('至少需要一个收件人。')
                continue
            cc_raw = prompt('抄送(可留空，逗号分隔)', '')
            cc = [r.strip() for r in cc_raw.split(',') if r.strip()]
            subject = prompt('主题', '')
            print('请输入正文，结束请输入单独一行的 "."：')
            lines: List[str] = []
            while True:
                line = input()
                if line == '.':
                    break
                lines.append(line)
            body = '\n'.join(lines)

            header_sender = sender
            message = build_message(header_sender, recipients, subject, body, cc=cc)
            try:
                client = SMTPClient(host=smtp_host, port=smtp_port, use_ssl=use_ssl, debug=verbose)
                client.send_email(
                    username=username,
                    password=password,
                    sender=sender,
                    recipients=recipients + cc,
                    message=message,
                    helo_host=helo_host,
                )
                print('邮件发送成功。')
                if prompt_bool('保存一份到 data/sent/last_sent.eml ?', True):
                    SENT_DIR.mkdir(parents=True, exist_ok=True)
                    (SENT_DIR / 'last_sent.eml').write_bytes(message.encode('utf-8'))
            except Exception as e:
                print(f'发送失败: {e}')

        elif choice == '2':
            # 保存为草稿
            sender = prompt('发件人邮箱')
            to = prompt('收件人(逗号分隔)')
            recipients = [r.strip() for r in to.split(',') if r.strip()]
            if not sender or not recipients:
                print('需要填写发件人与至少一个收件人。')
                continue
            cc_raw = prompt('抄送(可留空，逗号分隔)', '')
            cc = [r.strip() for r in cc_raw.split(',') if r.strip()]
            subject = prompt('主题', '')
            print('请输入正文，结束请输入单独一行的 "."：')
            lines: List[str] = []
            while True:
                line = input()
                if line == '.':
                    break
                lines.append(line)
            body = '\n'.join(lines)
            msg = build_message(sender, recipients, subject, body, cc=cc)
            DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
            draft_path = DRAFTS_DIR / f"draft_{Path(sender).stem}.eml"
            draft_path.write_bytes(msg.encode('utf-8'))
            print(f"已保存草稿: {draft_path}")

        elif choice == '3':
            # 通讯录查看
            contacts = load_address_book()
            if not contacts:
                print('通讯录为空。')
            else:
                for i, c in enumerate(contacts, 1):
                    print(f"{i}. {c}")

        elif choice == '4':
            # 通讯录添加
            email = prompt('邮箱地址')
            if not email:
                print('邮箱不能为空。')
                continue
            contacts = load_address_book()
            contacts.append(email)
            save_address_book(contacts)
            print('已添加。')

        elif choice == '5':
            # 通讯录删除
            email = prompt('要删除的邮箱地址')
            if not email:
                print('邮箱不能为空。')
                continue
            contacts = load_address_book()
            contacts = [c for c in contacts if c != email]
            save_address_book(contacts)
            print('已删除。')

        elif choice == '6':
            print('已退出。')
            break
        else:
            print('无效选择，请输入 1-6。')

# 主入口：解析命令行参数，分派子命令
def main():
    parser = argparse.ArgumentParser(description='基于Socket的SMTP客户端（QQ邮箱示例）')
    sub = parser.add_subparsers(dest='cmd')
    # 发送邮件子命令
    p_send = sub.add_parser('send', help='发送邮件（支持群发：逗号分隔多个地址）')
    p_send.add_argument('--smtp-host', default='smtp.qq.com')
    p_send.add_argument('--smtp-port', type=int, default=587)
    p_send.add_argument('--ssl', action='store_true', help='使用SSL直连（端口465），通常不需要，587端口会使用STARTTLS')
    p_send.add_argument('--helo-host', default='localhost')
    p_send.add_argument('--verbose', action='store_true', help='输出SMTP命令与响应（凭据打码）')
    p_send.add_argument('--username', help='登录用户名，缺省为发件人邮箱')
    p_send.add_argument('--password', required=True, help='QQ邮箱SMTP授权码（不是QQ密码）')
    p_send.add_argument('--sender', required=True, help='发件人邮箱')
    p_send.add_argument('--to', required=True, help='收件人，多个用逗号分隔')
    p_send.add_argument('--cc', help='抄送，多个用逗号分隔')
    p_send.add_argument('--subject', help='主题；留空进入交互输入')
    p_send.add_argument('--body', help='正文；留空进入交互输入')
    p_send.add_argument('--save-draft', action='store_true', help='保存为草稿，不发送')
    p_send.add_argument('--record-sent', action='store_true', help='保存已发送副本')
    p_send.set_defaults(func=cmd_send)
    # 通讯录子命令
    p_ab = sub.add_parser('contacts', help='通讯录管理')
    p_ab.add_argument('action', choices=['list', 'add', 'remove'])
    p_ab.add_argument('--email', help='要添加/删除的邮箱地址')
    p_ab.set_defaults(func=cmd_contacts)
    args = parser.parse_args()
    if not args.cmd:
        # 无子命令时进入交互式菜单
        interactive_menu()
        return
    args.func(args)

if __name__ == '__main__':
    main()
