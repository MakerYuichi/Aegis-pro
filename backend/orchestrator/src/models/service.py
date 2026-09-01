from sqlalchemy import Column, Integer, String, JSON, Boolean, DateTime
from sqlalchemy.sql import func
from src.database import Base

class Service(Base):
    __tablename__ = "services"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True, nullable=False)
    description = Column(String)
    repo_name = Column(String(255))
    repo_url = Column(String(500))
    on_call = Column(JSON, default=list)
    runbook_url = Column(String(500))
    slack_channel = Column(String(255))
    dependencies = Column(JSON, default=list)
    is_critical = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())