from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from personal_dashboard.config import settings

core_engine = create_async_engine(
    settings.core_database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},
)
core_session = async_sessionmaker(core_engine, class_=AsyncSession, expire_on_commit=False)


async def get_core_db():
    async with core_session() as session:
        yield session


@asynccontextmanager
async def get_core_db_context():
    async with core_session() as session:
        yield session
