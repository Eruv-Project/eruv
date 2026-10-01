"""Server command line. Today it only bootstraps the first admin.

Admins are otherwise created only by another admin approving them, so a fresh
server needs one admin created here:

    docker compose exec api python -m app.cli create-admin \\
        --email admin@example.org --name "Admin" --phone 050-0000000

The password is read from the ERUV_ADMIN_PASSWORD environment variable, or
prompted for (twice) when it is not set.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Sequence

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory, utcnow
from app.models import ApprovalState, Role, User
from app.security import hash_password

PASSWORD_ENV = "ERUV_ADMIN_PASSWORD"
MIN_PASSWORD_LENGTH = 8  # same rule as registration (app/api/auth.py)


class CliError(Exception):
    pass


def _read_password(prompt: Callable[[str], str]) -> str:
    password = os.environ.get(PASSWORD_ENV)
    if password is None:
        password = prompt("Password: ")
        if prompt("Repeat password: ") != password:
            raise CliError("passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise CliError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return password


def create_admin(settings: Settings, email: str, name: str, phone: str, password: str) -> int:
    """Insert an approved admin and return its id. Refuses an existing email."""
    try:
        email = validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise CliError(f"invalid email: {exc}") from None
    if not name.strip() or not phone.strip():
        raise CliError("name and phone are required")

    engine = make_engine(settings.database_url)
    try:
        with make_session_factory(engine)() as session:
            if session.scalar(select(User.id).where(User.email == email)) is not None:
                raise CliError(f"a user with email {email} already exists")
            user = User(
                name=name.strip(),
                phone=phone.strip(),
                email=email,
                password_hash=hash_password(password),
                role=Role.ADMIN,
                approval_state=ApprovalState.APPROVED,
                approved_at=utcnow(),
            )
            session.add(user)
            session.commit()
            return user.id
    finally:
        engine.dispose()


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Eruv server administration")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser(
        "create-admin", help=f"create an approved admin (password from ${PASSWORD_ENV} or a prompt)"
    )
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    admin.add_argument("--phone", required=True)
    args = parser.parse_args(argv)

    try:
        password = _read_password(prompt)
        user_id = create_admin(settings or get_settings(), args.email, args.name, args.phone, password)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created admin user id={user_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
