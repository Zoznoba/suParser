"""Управление пользователями (регистрации на сайте нет — доступ по списку).

python -m app.cli create-user <login> "<Имя>"      # пароль спросит интерактивно
python -m app.cli set-password <login>
python -m app.cli deactivate <login>
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import Source, User


def _ask_password() -> str:
    password = getpass.getpass("Пароль: ")
    if password != getpass.getpass("Повторите: "):
        sys.exit("Пароли не совпадают")
    if len(password) < 8:
        sys.exit("Минимум 8 символов")
    return password


async def browser_login(source: Source) -> None:
    from app.parsers.browser.base import BrowserParser
    from app.parsers.registry import create_parser

    parser = create_parser(source)
    if not isinstance(parser, BrowserParser):
        sys.exit(f"{source} сейчас не браузерный источник (для SuperJob нужен SUPERJOB_MODE=browser)")
    parser.headless = False
    try:
        await parser.interactive_login()
    finally:
        await parser.close()


async def main(args: argparse.Namespace) -> None:
    if args.command == "browser-login":
        return await browser_login(Source(args.source))
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.login == args.login))
        match args.command:
            case "create-user":
                if user:
                    sys.exit(f"Пользователь {args.login} уже существует")
                password = args.password or _ask_password()
                session.add(User(login=args.login, name=args.name, password_hash=hash_password(password)))
            case "set-password":
                if not user:
                    sys.exit(f"Нет пользователя {args.login}")
                user.password_hash = hash_password(args.password or _ask_password())
                user.is_active = True
            case "deactivate":
                if not user:
                    sys.exit(f"Нет пользователя {args.login}")
                user.is_active = False
        await session.commit()
    print("OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("login")
    create.add_argument("name")
    create.add_argument("--password", help="для скриптов; иначе спросит интерактивно")
    pwd = sub.add_parser("set-password")
    pwd.add_argument("login")
    pwd.add_argument("--password")
    sub.add_parser("deactivate").add_argument("login")
    sub.add_parser("browser-login").add_argument("source", choices=[s.value for s in Source])
    asyncio.run(main(parser.parse_args()))
