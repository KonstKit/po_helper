from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func
import aiosqlite
import asyncio
from app.core.config_simple import settings

Base = declarative_base()

# Simple synchronous database for now
engine = create_engine("sqlite:///po_helper.db", echo=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Simple models
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    full_name = Column(String)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())


class Project(Base):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    jira_key = Column(String, unique=True, index=True)
    name = Column(String)
    description = Column(Text)
    status = Column(String, default="active")
    budget = Column(Float)
    created_at = Column(DateTime, default=func.now())


class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    jira_id = Column(String, unique=True, index=True)
    key = Column(String, index=True)
    summary = Column(String)
    description = Column(Text)
    task_type = Column(String)
    status = Column(String)
    priority = Column(String)
    project_id = Column(Integer)
    assignee_email = Column(String)
    assignee_name = Column(String)
    estimate_hours = Column(Float)
    spent_hours = Column(Float)
    created_at = Column(DateTime, default=func.now())


def create_tables():
    Base.metadata.create_all(bind=engine)