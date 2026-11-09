from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def paginate(db: Session, stmt: Select, limit: int, offset: int) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.limit(min(limit, 1000)).offset(offset)).all()
    return rows, total


def like(term: str) -> str:
    return f"%{term.strip()}%"
