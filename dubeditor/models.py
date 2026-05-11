from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from dubeditor.database import Base

# ─── DubEditor Models ─────────────────────────────────────────────────────────

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
    shortcut_key      = Column(String, nullable=True)
    tts_speed         = Column(Float, default=1.0)
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
    wav_duration = Column(Float, nullable=True)
    tts_speed    = Column(Float, nullable=True)
    project   = relationship("Project",   back_populates="subtitles")
    character = relationship("Character", back_populates="subtitles")

class Chapter(Base):
    __tablename__ = "chapters"
    id              = Column(Integer, primary_key=True, index=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name            = Column(String, nullable=False, default="Đoạn")
    start_sub_index = Column(Integer, nullable=False)
    end_sub_index   = Column(Integer, nullable=False)
    status          = Column(String, default="pending")
    collapsed       = Column(Integer, default=0)
    sort_order      = Column(Integer, default=0)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="chapters")

# ─── VoiceCast Models ─────────────────────────────────────────────────────────

class Admin(Base):
    __tablename__ = "admins"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    username   = Column(String, unique=True, nullable=False)
    password   = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

class Actor(Base):
    __tablename__ = "actors"
    id         = Column(String, primary_key=True)
    name       = Column(String, nullable=False)
    gender     = Column(String, nullable=False, default="nam")
    birth_year = Column(Integer, nullable=True)
    avatar     = Column(String, default="")
    bio        = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    roles      = relationship("Role", back_populates="actor", cascade="all, delete", order_by="Role.sort_order")

class Role(Base):
    __tablename__ = "roles"
    id                   = Column(String, primary_key=True)
    actor_id             = Column(String, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False)
    character_name       = Column(String, nullable=False)
    show_name            = Column(String, default="")
    type                 = Column(String, default="chinh")
    genre                = Column(String, default="hien-dai")
    description          = Column(String, default="")
    audio                = Column(String, default="")
    reference_audio_text = Column(String, default="")
    lora_path            = Column(String, default="")
    sort_order           = Column(Integer, default=0)
    created_at           = Column(DateTime, server_default=func.now())
    actor  = relationship("Actor", back_populates="roles")
    images = relationship("RoleImage", back_populates="role", cascade="all, delete", order_by="RoleImage.sort_order")

class RoleImage(Base):
    __tablename__ = "role_images"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    role_id    = Column(String, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    url        = Column(String, nullable=False)
    sort_order = Column(Integer, default=0)
    role       = relationship("Role", back_populates="images")