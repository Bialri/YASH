from motor.core import AgnosticClientSession
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Coroutine, Any
from config import DB_URI

client = AsyncIOMotorClient(DB_URI)


async def get_db_session() -> Coroutine[Any, Any, AgnosticClientSession]:
    session = await client.start_session()
    return session
