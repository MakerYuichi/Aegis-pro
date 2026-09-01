from sqlalchemy import Column, Integer, String, JSON, DateTime, Text, Float
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from src.database import Base

class Incident(Base):
    __tablename__ = "incidents"
    
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(String(50), unique=True, index=True, nullable=False)
    service_name = Column(String(255), index=True, nullable=False)
    severity = Column(String(10), default="P1")
    status = Column(String(20), default="active")
    
    title = Column(Text)
    description = Column(Text)
    stack_trace = Column(Text)
    exception_type = Column(String(255))
    file_path = Column(String(500))
    line_number = Column(Integer)
    
    commit_hash = Column(String(40))
    pr_number = Column(Integer)
    pr_url = Column(String(500))
    author = Column(String(255))
    
    root_cause = Column(Text)
    suggested_fix = Column(Text)
    rollback_command = Column(Text)
    confidence_score = Column(Float, default=0.0)
    
    # Vector embedding for RAG (384 dimensions from sentence-transformers)
    embedding = Column(Vector(384))
    
    declared_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    extra_metadata = Column(JSON, default=dict)
    affected_services = Column(JSON, default=list)
    resolution_steps = Column(JSON, default=list)
