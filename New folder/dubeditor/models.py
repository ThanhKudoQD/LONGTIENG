from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from dubeditor.database import Base

class Project(Base):
    __tablename__ = "projects"
    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, nullable=False)
    video_path = Column(String, nullable=True)
    video_name = Column(String, nullable=True)
    duration   = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    current_chapter_id = Column(Integer, nullable=True)
    subtitles  = relationship("Subtitle",  back_populates="project", cascade="all, delete")
    characters = relationship("Character", back_populates="project", cascade="all, delete")
    chapters   = relationship("Chapter",   back_populates="project", cascade="all, delete", order_by="Chapter.sort_order")

class Character(Base):
    __tablename__ = "characters"
    id                = Column(Integer, primary_key=True, index=True)
    project_id        = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name              = Column(String, nullable=False)
    description       = Column(String, default="")
    color             = Column(String, default="#378ADD")
    avatar            = Column(String, default="")
    voxcpm_role_id    = Column(String, nullable=True)
    voxcpm_actor_name = Column(String, default="")
    voxcpm_role_name  = Column(String, default="")
    audio             = Column(String, nullable=True)
    shortcut_key      = Column(String, nullable=True)  # Phím tắt gán nhanh (1, 2, q, w, Shift+1...)
    tts_speed         = Column(Float, default=1.0)  # Tốc độ TTS mặc định (0.5-2.0)
    project   = relationship("Project",  back_populates="characters")
    subtitles = relationship("Subtitle", back_populates="character")

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
    wav_duration  = Column(Float, nullable=True)  # thời lượng thực tế của file WAV
    tts_speed     = Column(Float, nullable=True)  # Tốc độ TTS override (NULL = kế thừa từ character)
    project   = relationship("Project",   back_populates="subtitles")
    character = relationship("Character", back_populates="subtitles")


class Chapter(Base):
    __tablename__ = "chapters"
    id              = Column(Integer, primary_key=True, index=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name            = Column(String, nullable=False, default="Đoạn")
    start_sub_index = Column(Integer, nullable=False)
    end_sub_index   = Column(Integer, nullable=False)
    status          = Column(String, default="pending")  # pending | in_progress | done
    collapsed       = Column(Integer, default=0)
    sort_order      = Column(Integer, default=0)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="chapters")
