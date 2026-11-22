"""Local study-office adapter. Its only outbox is the sandbox database."""

import hashlib
import secrets
import uuid
from datetime import timedelta


def token_hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


class StaffOffice:
    def __init__(self, sandbox):
        self.db = sandbox.db
        self.db.execute("""
            create table if not exists kt3_staff_cards (
                id uuid primary key, owner text not null, topic text not null,
                summary text not null, token_hash text not null,
                expires timestamptz not null, ticket_id uuid unique,
                confirmed_at timestamptz
            )
        """)
        self.db.execute(
            "alter table kt3_staff_cards add column if not exists request_id text"
        )
        self.db.execute(
            "alter table kt3_staff_cards add column if not exists revoked boolean not null default false"
        )

    def lock_owner(self, owner):
        self.db.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s,0))",
            ("staff|" + owner,),
        )

    def preview(self, owner, request_id, topic, summary, now):
        card, secret = uuid.uuid4(), secrets.token_urlsafe(24)
        expires = now + timedelta(minutes=15)
        with self.db.transaction():
            self.lock_owner(owner)
            previous = self.db.execute(
                """select ticket_id from kt3_staff_cards where owner=%s and request_id=%s
                   and ticket_id is not null limit 1""",
                (owner, request_id),
            ).fetchone()
            if previous:
                return 409, {"code": "request_already_confirmed"}
            self.db.execute(
                """update kt3_staff_cards set revoked=true where owner=%s and request_id=%s
                   and ticket_id is null and not revoked""",
                (owner, request_id),
            )
            self.db.execute(
                """insert into kt3_staff_cards(id,owner,request_id,topic,summary,token_hash,expires)
                   values(%s,%s,%s,%s,%s,%s,%s)""",
                (card, owner, request_id, topic, summary, token_hash(secret), expires),
            )
        return 200, {
            "status": "confirmation_required",
            "card_id": str(card),
            "class": topic,
            "summary": summary,
            "confirmation": secret,
            "expires_at": expires.isoformat(),
        }

    def confirm(self, owner, card, secret, now):
        with self.db.transaction():
            self.lock_owner(owner)
            found = self.db.execute(
                """select token_hash,expires,ticket_id,revoked from kt3_staff_cards
                   where id=%s and owner=%s for update""",
                (card, owner),
            ).fetchone()
            if found is None or not secrets.compare_digest(
                found[0], token_hash(secret)
            ):
                return 403, {"code": "invalid_confirmation"}
            if found[2]:
                return 200, {"status": "queued_in_sandbox", "ticket_id": str(found[2])}
            if found[3] or now >= found[1]:
                return 409, {"code": "confirmation_stale"}
            count = self.db.execute(
                """select count(*) from kt3_staff_cards
                   where owner=%s and confirmed_at>%s and confirmed_at<=%s""",
                (owner, now - timedelta(days=7), now),
            ).fetchone()[0]
            if count >= 3:
                return 409, {"code": "weekly_limit_reached"}
            ticket = uuid.uuid4()
            self.db.execute(
                "update kt3_staff_cards set ticket_id=%s, confirmed_at=%s where id=%s",
                (ticket, now, card),
            )
            return 201, {"status": "queued_in_sandbox", "ticket_id": str(ticket)}
