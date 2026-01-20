"""
SQLAlchemy models for the database.
Django-style ORM approach for data persistence.
"""
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Index
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime, timezone
from typing import Optional
import streamlit as st

Base = declarative_base()


class GoldStandard(Base):
    """Model for accepted job descriptions (gold standards)."""
    __tablename__ = "gold_standards"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), nullable=False, index=True)
    job_title = Column(String(500), nullable=False, index=True)
    job_body_json = Column(Text, nullable=False)
    config_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    
    __table_args__ = (
        Index("idx_gold_user_title", "user_id", "job_title"),
    )


class UserFeedback(Base):
    """Model for user feedback (rejections, edits, gripes)."""
    __tablename__ = "user_feedback"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), nullable=False, index=True)
    job_title = Column(String(500), nullable=True)
    feedback_type = Column(String(50), nullable=False, index=True)  # 'accepted', 'rejected', 'edited', 'gripe'
    feedback_text = Column(Text, nullable=True)
    job_body_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    __table_args__ = (
        Index("idx_feedback_user_type", "user_id", "feedback_type"),
    )


class Interaction(Base):
    """Model for interaction history."""
    __tablename__ = "interactions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), nullable=False, index=True)
    session_id = Column(String(255), nullable=True)
    interaction_type = Column(String(50), nullable=False)  # 'generation', 'edit', 'chat', 'feedback'
    job_title = Column(String(500), nullable=True)
    input_data = Column(Text, nullable=True)  # JSON
    output_data = Column(Text, nullable=True)  # JSON
    metadata_json = Column(Text, nullable=True)  # JSON (renamed from 'metadata' to avoid SQLAlchemy conflict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    __table_args__ = (
        Index("idx_interactions_user_created", "user_id", "created_at"),
    )


class DatabaseManager:
    """Django-style ORM database manager."""
    
    def __init__(self, db_path: str = "jd_database.sqlite"):
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
    
    def get_session(self) -> Session:
        """Get a database session."""
        return self.SessionLocal()
    
    def save_gold_standard(
        self,
        user_id: str,
        job_title: str,
        job_body_json: str,
        config_json: Optional[str] = None
    ) -> int:
        """Save an accepted job description as a gold standard."""
        session = self.get_session()
        try:
            gold_standard = GoldStandard(
                user_id=user_id,
                job_title=job_title,
                job_body_json=job_body_json,
                config_json=config_json
            )
            session.add(gold_standard)
            session.commit()
            return gold_standard.id
        finally:
            session.close()
    
    def get_gold_standards(
        self,
        user_id: str,
        job_title: Optional[str] = None,
        limit: int = 10
    ) -> list[dict]:
        """Retrieve gold standards for a user."""
        session = self.get_session()
        try:
            query = session.query(GoldStandard).filter(GoldStandard.user_id == user_id)
            if job_title:
                query = query.filter(GoldStandard.job_title.like(f"%{job_title}%"))
            query = query.order_by(GoldStandard.updated_at.desc()).limit(limit)
            
            results = []
            for gs in query.all():
                results.append({
                    "id": gs.id,
                    "user_id": gs.user_id,
                    "job_title": gs.job_title,
                    "job_body_json": gs.job_body_json,
                    "config_json": gs.config_json,
                    "created_at": gs.created_at.isoformat() if gs.created_at else None,
                    "updated_at": gs.updated_at.isoformat() if gs.updated_at else None,
                })
            return results
        finally:
            session.close()
    
    def save_user_feedback(
        self,
        user_id: str,
        feedback_type: str,
        feedback_text: Optional[str] = None,
        job_title: Optional[str] = None,
        job_body_json: Optional[str] = None
    ) -> int:
        """Save user feedback."""
        session = self.get_session()
        try:
            feedback = UserFeedback(
                user_id=user_id,
                job_title=job_title,
                feedback_type=feedback_type,
                feedback_text=feedback_text,
                job_body_json=job_body_json
            )
            session.add(feedback)
            session.commit()
            return feedback.id
        finally:
            session.close()
    
    def get_user_feedback(
        self,
        user_id: str,
        feedback_type: Optional[str] = None,
        limit: int = 20
    ) -> list[dict]:
        """Retrieve user feedback."""
        session = self.get_session()
        try:
            query = session.query(UserFeedback).filter(UserFeedback.user_id == user_id)
            if feedback_type:
                query = query.filter(UserFeedback.feedback_type == feedback_type)
            query = query.order_by(UserFeedback.created_at.desc()).limit(limit)
            
            results = []
            for fb in query.all():
                results.append({
                    "id": fb.id,
                    "user_id": fb.user_id,
                    "job_title": fb.job_title,
                    "feedback_type": fb.feedback_type,
                    "feedback_text": fb.feedback_text,
                    "job_body_json": fb.job_body_json,
                    "created_at": fb.created_at.isoformat() if fb.created_at else None,
                })
            return results
        finally:
            session.close()
    
    def save_interaction(
        self,
        user_id: str,
        interaction_type: str,
        input_data: Optional[dict] = None,
        output_data: Optional[dict] = None,
        metadata: Optional[dict] = None,
        session_id: Optional[str] = None,
        job_title: Optional[str] = None
    ) -> int:
        """Save an interaction record."""
        import json
        session = self.get_session()
        try:
            interaction = Interaction(
                user_id=user_id,
                session_id=session_id,
                interaction_type=interaction_type,
                job_title=job_title,
                input_data=json.dumps(input_data) if input_data else None,
                output_data=json.dumps(output_data) if output_data else None,
                metadata_json=json.dumps(metadata) if metadata else None
            )
            session.add(interaction)
            session.commit()
            return interaction.id
        finally:
            session.close()
    
    def get_interaction_history(
        self,
        user_id: str,
        interaction_type: Optional[str] = None,
        limit: int = 50
    ) -> list[dict]:
        """Retrieve interaction history."""
        import json
        session = self.get_session()
        try:
            query = session.query(Interaction).filter(Interaction.user_id == user_id)
            if interaction_type:
                query = query.filter(Interaction.interaction_type == interaction_type)
            query = query.order_by(Interaction.created_at.desc()).limit(limit)
            
            results = []
            for h in query.all():
                result = {
                    "id": h.id,
                    "user_id": h.user_id,
                    "session_id": h.session_id,
                    "interaction_type": h.interaction_type,
                    "job_title": h.job_title,
                    "created_at": h.created_at.isoformat() if h.created_at else None,
                }
                # Parse JSON fields
                if h.input_data:
                    result["input_data"] = json.loads(h.input_data)
                if h.output_data:
                    result["output_data"] = json.loads(h.output_data)
                if h.metadata_json:
                    result["metadata"] = json.loads(h.metadata_json)
                results.append(result)
            return results
        finally:
            session.close()
    
    def delete_gold_standard(self, gold_standard_id: int, user_id: str) -> bool:
        """Delete a gold standard by ID. Returns True if deleted, False if not found."""
        session = self.get_session()
        try:
            gold_standard = session.query(GoldStandard).filter(
                GoldStandard.id == gold_standard_id,
                GoldStandard.user_id == user_id
            ).first()
            if gold_standard:
                session.delete(gold_standard)
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    def delete_user_feedback(self, feedback_id: int, user_id: str) -> bool:
        """Delete user feedback by ID. Returns True if deleted, False if not found."""
        session = self.get_session()
        try:
            feedback = session.query(UserFeedback).filter(
                UserFeedback.id == feedback_id,
                UserFeedback.user_id == user_id
            ).first()
            if feedback:
                session.delete(feedback)
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    def delete_interaction(self, interaction_id: int, user_id: str) -> bool:
        """Delete an interaction by ID. Returns True if deleted, False if not found."""
        session = self.get_session()
        try:
            interaction = session.query(Interaction).filter(
                Interaction.id == interaction_id,
                Interaction.user_id == user_id
            ).first()
            if interaction:
                session.delete(interaction)
                session.commit()
                return True
            return False
        finally:
            session.close()


@st.cache_resource
def get_db_manager(db_path: str = "jd_database.sqlite", _version: int = 3) -> DatabaseManager:
    """Get cached database manager instance.
    
    _version parameter is used to invalidate cache when database methods change.
    Increment this number when adding new methods to force cache refresh.
    """
    return DatabaseManager(db_path)

