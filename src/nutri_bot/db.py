from supabase._async.client import AsyncClient, create_client

_client: AsyncClient | None = None


async def create_db_client(url: str, key: str) -> AsyncClient:
    global _client
    _client = await create_client(url, key)
    return _client


def get_client() -> AsyncClient:
    if _client is None:
        raise RuntimeError("Supabase client is not initialised — call create_db_client() first")
    return _client


async def close_client() -> None:
    global _client
    _client = None
