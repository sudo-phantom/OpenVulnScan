from sqlalchemy import Column, Integer, String, Boolean, DateTime
from database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)  # ✅ Add this line
    created_at = Column(DateTime, default=datetime.utcnow)
    auth_provider = Column(String, default="manual")  # 'google', 'github', 'wallet', 'manual'
    wallet_address = Column(String, unique=True, nullable=True)
