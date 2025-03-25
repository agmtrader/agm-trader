from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
import os

from src.utils.database import DatabaseHandler
from src.utils.logger import logger

class TraderDB:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TraderDB, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            logger.announcement('Initializing Trader Database', 'info')

            db_path = os.path.join(os.path.dirname(__file__), '..', 'db', 'trader.db')
            db_url = f'sqlite:///{db_path}'
            self.engine = create_engine(db_url)

            self.Base = declarative_base()
            self._setup_models()
            self.db = DatabaseHandler(base=self.Base, engine=self.engine, type='sqlite')

            logger.announcement("Successfully initialized Trader Database", type='success')
            self._initialized = True

    def _setup_models(self):
        class Decision(self.Base):
            """Decision table"""
            __tablename__ = 'decision'
            id = Column(Integer, primary_key=True, unique=True)
            decision = Column(String, nullable=False)
            created = Column(String, nullable=False)
            updated = Column(String, nullable=False)

        # Store model classes as attributes of the instance
        self.Decision = Decision

# Create a single instance that can be imported and used throughout the application
db = TraderDB().db 