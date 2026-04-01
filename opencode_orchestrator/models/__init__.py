import aiosqlite

from .database import get_db, init_db, row_to_dict, now

__all__ = ["get_db", "init_db", "row_to_dict", "now", "fetch_one", "fetch_all", "execute"]


async def fetch_one(query: str, params: tuple = ()) -> dict | None:
    """Execute a query and return a single row as dict, or None."""
    async for db in get_db():
        row = await db.execute(query, params)
        result = await row.fetchone()
        return row_to_dict(result) if result else None


async def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    """Execute a query and return all rows as list of dicts."""
    async for db in get_db():
        rows = await db.execute(query, params)
        return [row_to_dict(row) for row in await rows.fetchall()]
    return []


async def execute(query: str, params: tuple = (), commit: bool = True) -> aiosqlite.Cursor:
    """Execute a query and return the cursor. Optionally commits."""
    async for db in get_db():
        cursor = await db.execute(query, params)
        if commit:
            await db.commit()
        return cursor
