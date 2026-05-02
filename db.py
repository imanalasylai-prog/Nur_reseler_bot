import asyncpg
import os
from typing import Optional

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=10)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def ensure_user(telegram_id: int, username: str | None, first_name: str | None, is_env_admin: bool) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
        if row:
            if is_env_admin and not row["is_admin"]:
                row = await conn.fetchrow(
                    "UPDATE users SET is_admin=true WHERE telegram_id=$1 RETURNING *", telegram_id
                )
            return dict(row)
        row = await conn.fetchrow(
            "INSERT INTO users (telegram_id, username, first_name, is_admin) VALUES ($1,$2,$3,$4) RETURNING *",
            telegram_id, username, first_name, is_env_admin
        )
        return dict(row)


async def get_user(telegram_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
        return dict(row) if row else None


async def set_user_language(telegram_id: int, lang: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET language=$1 WHERE telegram_id=$2", lang, telegram_id)


async def list_categories() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM categories ORDER BY sort_order ASC, id ASC")
        return [dict(r) for r in rows]


async def create_category(name: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("INSERT INTO categories (name) VALUES ($1) RETURNING *", name)
        return dict(row)


async def delete_category(cat_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        products = await conn.fetch("SELECT id FROM products WHERE category_id=$1", cat_id)
        for p in products:
            await conn.execute("DELETE FROM product_keys WHERE product_id=$1", p["id"])
            await conn.execute("DELETE FROM products WHERE id=$1", p["id"])
        await conn.execute("DELETE FROM categories WHERE id=$1", cat_id)


async def get_category(cat_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM categories WHERE id=$1", cat_id)
        return dict(row) if row else None


async def list_products_by_category(category_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM products WHERE category_id=$1 ORDER BY id ASC", category_id)
        return [dict(r) for r in rows]


async def get_product(product_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM products WHERE id=$1", product_id)
        return dict(row) if row else None


async def create_product(category_id: int, name: str, description: str, price_tenge: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO products (category_id, name, description, price_tenge) VALUES ($1,$2,$3,$4) RETURNING *",
            category_id, name, description, price_tenge
        )
        return dict(row)


async def delete_product(product_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM product_keys WHERE product_id=$1", product_id)
        await conn.execute("DELETE FROM products WHERE id=$1", product_id)


async def set_product_price(product_id: int, price_tenge: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE products SET price_tenge=$1 WHERE id=$2", price_tenge, product_id)


async def get_stock_count(product_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*)::int as c FROM product_keys WHERE product_id=$1 AND sold_to_telegram_id IS NULL",
            product_id
        )
        return row["c"] if row else 0


async def add_keys(product_id: int, keys: list[str]) -> dict:
    pool = await get_pool()
    added = 0
    dup = 0
    async with pool.acquire() as conn:
        for key in keys:
            key = key.strip()
            if not key:
                continue
            try:
                await conn.execute(
                    "INSERT INTO product_keys (product_id, key_value) VALUES ($1,$2)", product_id, key
                )
                added += 1
            except asyncpg.UniqueViolationError:
                dup += 1
    return {"added": added, "dup": dup}


async def purchase_product(telegram_id: int, product_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id=$1 FOR UPDATE", telegram_id
            )
            if not user:
                return {"ok": False, "reason": "no_user"}
            product = await conn.fetchrow("SELECT * FROM products WHERE id=$1", product_id)
            if not product:
                return {"ok": False, "reason": "no_product"}
            if user["balance_tenge"] < product["price_tenge"]:
                return {"ok": False, "reason": "not_enough"}
            key_row = await conn.fetchrow(
                "SELECT * FROM product_keys WHERE product_id=$1 AND sold_to_telegram_id IS NULL ORDER BY id ASC LIMIT 1 FOR UPDATE",
                product_id
            )
            if not key_row:
                return {"ok": False, "reason": "no_stock"}
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            await conn.execute(
                "UPDATE product_keys SET sold_to_telegram_id=$1, sold_at=$2 WHERE id=$3",
                telegram_id, now, key_row["id"]
            )
            new_balance = user["balance_tenge"] - product["price_tenge"]
            await conn.execute(
                "UPDATE users SET balance_tenge=$1 WHERE telegram_id=$2", new_balance, telegram_id
            )
            await conn.execute(
                "INSERT INTO transactions (telegram_id, amount_tenge, kind, meta) VALUES ($1,$2,$3,$4)",
                telegram_id, -product["price_tenge"], "purchase",
                f"product={product_id};key={key_row['id']}"
            )
            return {"ok": True, "key": key_row["key_value"], "balance": new_balance, "product": dict(product)}


async def adjust_balance(telegram_id: int, delta: int, kind: str, meta: str = "") -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id=$1 FOR UPDATE", telegram_id
            )
            if not user:
                raise ValueError("user not found")
            new_bal = user["balance_tenge"] + delta
            await conn.execute(
                "UPDATE users SET balance_tenge=$1 WHERE telegram_id=$2", new_bal, telegram_id
            )
            await conn.execute(
                "INSERT INTO transactions (telegram_id, amount_tenge, kind, meta) VALUES ($1,$2,$3,$4)",
                telegram_id, delta, kind, meta
            )
            return new_bal


async def create_topup_request(telegram_id: int, amount: int, proof_file_id: str | None = None, note: str = "") -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO topup_requests (telegram_id, amount_tenge, proof_file_id, note) VALUES ($1,$2,$3,$4) RETURNING *",
            telegram_id, amount, proof_file_id, note
        )
        return dict(row)


async def list_pending_topups(limit: int = 20) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM topup_requests WHERE status='pending' ORDER BY id ASC LIMIT $1", limit
        )
        return [dict(r) for r in rows]


async def get_topup(topup_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM topup_requests WHERE id=$1", topup_id)
        return dict(row) if row else None


async def mark_topup(topup_id: int, status: str, reviewer_id: int):
    from datetime import datetime, timezone
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE topup_requests SET status=$1, reviewed_by_telegram_id=$2, reviewed_at=$3 WHERE id=$4",
            status, reviewer_id, datetime.now(timezone.utc), topup_id
        )


async def get_setting(key: str) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key=$1", key)
        return row["value"] if row else None


async def set_setting(key: str, value: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ($1,$2) ON CONFLICT (key) DO UPDATE SET value=$2",
            key, value
        )


async def get_stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        users = await conn.fetchval("SELECT COUNT(*)::int FROM users")
        cats = await conn.fetchval("SELECT COUNT(*)::int FROM categories")
        prods = await conn.fetchval("SELECT COUNT(*)::int FROM products")
        keys = await conn.fetchval("SELECT COUNT(*)::int FROM product_keys")
        sold = await conn.fetchval("SELECT COUNT(*)::int FROM product_keys WHERE sold_to_telegram_id IS NOT NULL")
        pending = await conn.fetchval("SELECT COUNT(*)::int FROM topup_requests WHERE status='pending'")
        accounts = await conn.fetchval("SELECT COUNT(*)::int FROM accounts")
        return {
            "users": users, "cats": cats, "prods": prods,
            "keys": keys, "sold": sold, "pending": pending, "accounts": accounts
        }


async def list_accounts() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM accounts ORDER BY id ASC")
        return [dict(r) for r in rows]


async def find_account_by_telegram_id(telegram_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM accounts WHERE claimed_by_telegram_id=$1", telegram_id)
        return dict(row) if row else None


async def create_account(username: str, password: str, role: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                "INSERT INTO accounts (username, password, role) VALUES ($1,$2,$3) RETURNING *",
                username, password, role
            )
            return {"ok": True, "account": dict(row)}
        except asyncpg.UniqueViolationError:
            return {"ok": False, "reason": "duplicate"}


async def delete_account(account_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        acc = await conn.fetchrow("SELECT * FROM accounts WHERE id=$1", account_id)
        if acc and acc["claimed_by_telegram_id"]:
            await conn.execute(
                "UPDATE users SET account_id=NULL, is_admin=false WHERE telegram_id=$1",
                acc["claimed_by_telegram_id"]
            )
        await conn.execute("DELETE FROM accounts WHERE id=$1", account_id)


async def login_and_claim(telegram_id: int, username: str, password: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            acc = await conn.fetchrow(
                "SELECT * FROM accounts WHERE username=$1 FOR UPDATE", username
            )
            if not acc:
                return {"ok": False, "reason": "not_found"}
            if acc["password"] != password:
                return {"ok": False, "reason": "wrong_password"}
            if acc["claimed_by_telegram_id"] and acc["claimed_by_telegram_id"] != telegram_id:
                return {"ok": False, "reason": "claimed_by_other"}
            if not acc["claimed_by_telegram_id"]:
                from datetime import datetime, timezone
                await conn.execute(
                    "UPDATE accounts SET claimed_by_telegram_id=NULL, claimed_at=NULL WHERE claimed_by_telegram_id=$1",
                    telegram_id
                )
                await conn.execute(
                    "UPDATE accounts SET claimed_by_telegram_id=$1, claimed_at=$2 WHERE id=$3",
                    telegram_id, datetime.now(timezone.utc), acc["id"]
                )
            is_admin_role = acc["role"] == "admin"
            await conn.execute(
                "UPDATE users SET account_id=$1, is_admin=$2 WHERE telegram_id=$3",
                acc["id"], is_admin_role, telegram_id
            )
            refreshed = await conn.fetchrow("SELECT * FROM accounts WHERE id=$1", acc["id"])
            return {"ok": True, "account": dict(refreshed), "is_admin_role": is_admin_role}


async def list_all_user_telegram_ids() -> list[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT telegram_id FROM users")
        return [r["telegram_id"] for r in rows]
