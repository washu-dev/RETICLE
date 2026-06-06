"""
Database connection and session management for RETICLE data warehouse.

Provides pooled connections, transaction management, and safe context managers.
"""

import logging
from contextlib import contextmanager
from typing import Optional, Generator, Any
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session
from config import Config

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manages database connections and sessions."""

    _instance: Optional['DatabaseManager'] = None
    _connection_pool: Optional[SimpleConnectionPool] = None
    _sqlalchemy_engine: Optional[Any] = None
    _sqlalchemy_session_factory: Optional[sessionmaker] = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize database manager."""
        if self._initialized:
            return

        self._initialized = True
        logger.info("Initializing DatabaseManager...")

    @classmethod
    def get_psycopg2_connection(cls):
        """Get a raw psycopg2 connection from the pool."""
        if cls._connection_pool is None:
            cls._init_psycopg2_pool()

        try:
            conn = cls._connection_pool.getconn()
            logger.debug("Got connection from pool")
            return conn
        except psycopg2.pool.PoolError as e:
            logger.error(f"Failed to get connection from pool: {e}")
            raise

    @classmethod
    def _init_psycopg2_pool(cls):
        """Initialize psycopg2 connection pool."""
        logger.info(f"Creating psycopg2 connection pool (size={Config.POOL_SIZE})")

        try:
            params = Config.get_psycopg2_params()
            params['gssencmode'] = 'disable'
            cls._connection_pool = SimpleConnectionPool(
                Config.POOL_SIZE,
                Config.POOL_SIZE + Config.MAX_OVERFLOW,
                **params
            )
            logger.info("✓ Connection pool created")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise

    @classmethod
    def release_psycopg2_connection(cls, conn):
        """Return a connection to the pool."""
        if cls._connection_pool:
            cls._connection_pool.putconn(conn)
            logger.debug("Returned connection to pool")

    @classmethod
    def get_sqlalchemy_engine(cls):
        """Get SQLAlchemy engine (lazily initialized)."""
        if cls._sqlalchemy_engine is None:
            cls._init_sqlalchemy_engine()
        return cls._sqlalchemy_engine

    @classmethod
    def _init_sqlalchemy_engine(cls):
        """Initialize SQLAlchemy engine with connection pooling."""
        logger.info("Creating SQLAlchemy engine...")

        try:
            connection_string = Config.get_connection_string()
            cls._sqlalchemy_engine = create_engine(
                connection_string,
                pool_size=Config.POOL_SIZE,
                max_overflow=Config.MAX_OVERFLOW,
                pool_timeout=Config.POOL_TIMEOUT,
                echo=False,
                pool_pre_ping=True,  # Verify connections before using
            )
            logger.info("SQLAlchemy engine created")

            # Test connection
            with cls._sqlalchemy_engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                result.close()

            logger.info("✓ SQLAlchemy engine created and tested")
        except Exception as e:
            logger.error(f"Failed to create SQLAlchemy engine: {e}")
            raise

    @classmethod
    def get_session_factory(cls) -> sessionmaker:
        """Get SQLAlchemy session factory."""
        if cls._sqlalchemy_session_factory is None:
            engine = cls.get_sqlalchemy_engine()
            cls._sqlalchemy_session_factory = sessionmaker(bind=engine)
        return cls._sqlalchemy_session_factory

    @classmethod
    @contextmanager
    def get_session(cls) -> Generator[Session, None, None]:
        """Context manager for SQLAlchemy sessions."""
        session_factory = cls.get_session_factory()
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            session.close()

    @classmethod
    @contextmanager
    def get_connection(cls):
        """Context manager for raw psycopg2 connections."""
        conn = cls.get_psycopg2_connection()
        try:
            yield conn
            conn.commit()
            logger.debug("Connection committed")
        except Exception as e:
            conn.rollback()
            logger.error(f"Connection error: {e}")
            raise
        finally:
            cls.release_psycopg2_connection(conn)

    @classmethod
    def execute_query(cls, query: str, params: Optional[dict] = None) -> list:
        """Execute a query and return results."""
        with cls.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params or {})
                return cur.fetchall()

    @classmethod
    def execute_update(cls, query: str, params: Optional[dict] = None) -> int:
        """Execute an INSERT/UPDATE/DELETE and return row count."""
        with cls.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or {})
                return cur.rowcount

    @classmethod
    def execute_script(cls, script: str):
        """Execute a SQL script (with multiple statements)."""
        with cls.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(script)
                logger.info(f"Script executed successfully")

    @classmethod
    def close_all(cls):
        """Close all connections and cleanup."""
        logger.info("Closing all database connections...")

        if cls._sqlalchemy_engine:
            cls._sqlalchemy_engine.dispose()
            cls._sqlalchemy_engine = None

        if cls._connection_pool:
            cls._connection_pool.closeall()
            cls._connection_pool = None

        logger.info("✓ All connections closed")


def get_db_manager() -> DatabaseManager:
    """Get singleton DatabaseManager instance."""
    return DatabaseManager()


def get_sqlalchemy_session() -> Session:
    """Get a new SQLAlchemy session."""
    factory = DatabaseManager.get_session_factory()
    return factory()


if __name__ == '__main__':
    # Test database connection
    logging.basicConfig(
        level=Config.LOG_LEVEL,
        format=Config.LOG_FORMAT
    )

    print("\n" + "="*80)
    print("Testing Database Connection")
    print("="*80 + "\n")

    try:
        db = get_db_manager()

        # Test psycopg2 connection
        print("Testing psycopg2 connection...")
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()
                print(f"✓ PostgreSQL: {version[0][:60]}...")

        # Test SQLAlchemy connection
        print("\nTesting SQLAlchemy connection...")
        with db.get_session() as session:
            result = session.execute(text("SELECT COUNT(*) as table_count FROM information_schema.tables WHERE table_schema = 'public'"))
            count = result.scalar()
            print(f"✓ Tables in public schema: {count}")

        print("\n✓ All database connections successful\n")

    except Exception as e:
        print(f"\n✗ Database connection failed: {e}\n")
        exit(1)

    finally:
        db.close_all()
