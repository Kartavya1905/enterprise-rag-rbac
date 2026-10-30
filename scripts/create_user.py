"""
FILE:         scripts/create_user.py
WHAT IT DOES: Creates (or updates) ONE real login account. This is how users get into a
              production deployment, where the demo personas are refused (Phase 3).
WHERE IT FITS: Phase 12. Uses the same upsert_user() as the persona seeder, so the same
              rules apply (real departments only, bcrypt-hashed password).
RUN (inside Docker, so it uses the deployment's own database):
    docker compose exec api python -m scripts.create_user --user-id u_jdoe \
        --email jane.doe@example.com --name "Jane Doe" --title "Analyst" \
        --role finance --clearance 3 --department finance
    (with the prod stack: docker compose -p enterprise-rag-prod exec api ...)

The password is generated randomly and printed ONCE - nothing stores it in plain text.
Running again for the same --user-id updates the account and sets a new password.
Changes to clearance or departments take effect on the user's next request.
"""

import argparse
import secrets
from typing import get_args

from app.auth.schemas import Role
from app.core.access import Clearance, Department


def main() -> None:
    real_departments = [d.value for d in Department if d is not Department.ALL]
    parser = argparse.ArgumentParser(description="Create or update one login account.")
    parser.add_argument("--user-id", required=True, help="stable id, e.g. u_jdoe")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--title", required=True, help="job title (shown in the UI)")
    parser.add_argument("--role", required=True, choices=get_args(Role))
    parser.add_argument("--clearance", required=True, type=int,
                        choices=[c.value for c in Clearance],
                        help="1 public, 2 internal, 3 confidential, 4 restricted")
    parser.add_argument("--department", required=True, action="append",
                        choices=real_departments, help="repeat for several departments")
    args = parser.parse_args()

    from app.auth.service import upsert_user
    from app.core.database import get_session_factory, init_db

    password = secrets.token_urlsafe(16)  # ~128 bits of randomness
    init_db()
    with get_session_factory()() as db:
        upsert_user(db, user_id=args.user_id, email=args.email, name=args.name,
                    title=args.title, role=args.role, clearance=Clearance(args.clearance),
                    departments=frozenset(Department(d) for d in args.department),
                    password=password)
        db.commit()

    print(f"Saved {args.user_id} <{args.email}>: role {args.role}, clearance "
          f"{args.clearance}, departments {', '.join(sorted(args.department))}")
    print(f"Password (shown once, give it to the user securely): {password}")


if __name__ == "__main__":
    main()
