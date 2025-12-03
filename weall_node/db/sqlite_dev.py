import os, aiosqlite, asyncio
DB_PATH = os.getenv("WEALL_DB","weall_dev.sqlite")

class DB:
    _pool = None

    @classmethod
    async def init(cls):
        if cls._pool: return
        cls._pool = await aiosqlite.connect(DB_PATH)
        await cls._pool.execute("PRAGMA journal_mode=WAL;")
        await cls._pool.execute("PRAGMA synchronous=NORMAL;")
        await cls._pool.commit()

    @classmethod
    async def execute(cls, sql, *params):
        await cls.init()
        cur = await cls._pool.execute(sql, params)
        await cls._pool.commit()
        return cur.lastrowid

    @classmethod
    async def query_all(cls, sql, *params):
        await cls.init()
        cur = await cls._pool.execute(sql, params)
        rows = await cur.fetchall()
        cols = [c[0] for c in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in rows]

    @classmethod
    async def query_one(cls, sql, *params):
        rows = await cls.query_all(sql, *params)
        return rows[0] if rows else None
