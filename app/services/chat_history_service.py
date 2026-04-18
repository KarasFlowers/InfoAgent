from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.domain import ChatMessage
from app.core.db import engine

async def save_chat_message(article_url: str, role: str, content: str):
    """Save a single chat message to the database."""
    async with AsyncSession(engine) as session:
        message = ChatMessage(article_url=article_url, role=role, content=content)
        session.add(message)
        await session.commit()

async def get_chat_history(article_url: str) -> list[ChatMessage]:
    """Retrieve all chat messages for a given article, ordered by timestamp."""
    async with AsyncSession(engine) as session:
        statement = select(ChatMessage).where(ChatMessage.article_url == article_url).order_by(ChatMessage.timestamp)
        result = await session.execute(statement)
        return result.scalars().all()
