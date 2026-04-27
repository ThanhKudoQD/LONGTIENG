from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class Project(Base):
    __tablename__ = "projects"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, nullable=False)
    video_path = Column(String, nullable=True)
    video_name = Column(String, nullable=True)
    duration   = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    subtitles  = relationship("Subtitle",  back_populates="project", cascade="all, delete")
    characters = relationship("Character", back_populates="project", cascade="all, delete")


class Character(Base):
    __tablename__ = "characters"

    id          = Column(Integer, primary_key=True, index=True)
    project_id  = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name        = Column(String, nullable=False)
    description = Column(String, default="")
    color       = Column(String, default="#378ADD")
    voice_id    = Column(String, default="vi-VN-HoaiMyNeural")
    avatar      = Column(String, default="")

    project    = relationship("Project",  back_populates="characters")
    subtitles  = relationship("Subtitle", back_populates="character")


class Subtitle(Base):
    __tablename__ = "subtitles"

    id           = Column(Integer, primary_key=True, index=True)
    project_id   = Column(Integer, ForeignKey("projects.id"), nullable=False)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    index        = Column(Integer, nullable=False)
    start_time   = Column(Float, nullable=False)
    end_time     = Column(Float, nullable=False)
    text         = Column(Text, default="")
    audio_path   = Column(String, nullable=True)
    audio_offset = Column(Float, default=0.0)
    tts_done     = Column(Boolean, default=False)

    project   = relationship("Project",   back_populates="subtitles")
    character = relationship("Character", back_populates="subtitles")
