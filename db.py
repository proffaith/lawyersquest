import os
import logging
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import urlparse
import socks
import socket

bypass_proxy = os.getenv("BYPASS_PROXY") == "1"

if not bypass_proxy:
    fixie_url = os.getenv("QUOTA_GUARD_HOST")
#    user_pass, host_port = fixie_url.split('@')
#    username, password = user_pass.split(':')
#    host, port = host_port.split(':')

    socks.set_default_proxy(
        socks.SOCKS5,
        host,
        int(port),
        True,
        username,
        password
    )

    socket.socket = socks.socksocket  # override *before* pymysql is imported


from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, ForeignKey, func, Enum, Boolean, UniqueConstraint
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base, relationship
from sqlalchemy.exc import SQLAlchemyError, DBAPIError
import pymysql

from dotenv import load_dotenv
# Load environment variables at the start of the application
load_dotenv()

resolved = socket.getaddrinfo(os.getenv('DB_HOST'), 3306)

def connect():
    # Just connect directly now — socket is already patched
    return pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        ssl={"ssl": {}},
        connect_timeout=10
    )

DB_URI = "mysql+pymysql://"
engine = create_engine(
        DB_URI,
        creator=connect,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=1800
    )


# Scoped session for ORM
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

# Base class for models
Base = declarative_base()
Base.query = db_session.query_property()

# ────────────── Models ──────────────

class Squire(Base):
    __tablename__ = 'squires'

    id = Column(Integer, primary_key=True)
    squire_name = Column(String(255), unique=True, nullable=False)
    email = Column(String(255))
    team_id = Column(Integer)
    experience_points = Column(Integer)
    level = Column(Integer)
    x_coordinate = Column(Integer)
    y_coordinate = Column(Integer)
    work_sessions = Column(Integer)

    map_features  = relationship('MapFeature', back_populates='squire', cascade='all, delete-orphan')
    inventory  = relationship('Inventory', back_populates='squire', cascade='all, delete-orphan')
    quest_statuses = relationship('SquireQuestStatus',back_populates='squire',cascade='all, delete-orphan')
    questions = relationship('SquireQuestion', back_populates='squire', cascade='all, delete-orphan')
    riddle_progress = relationship('SquireRiddleProgress',back_populates='squire',cascade='all, delete-orphan')
    travel_history = relationship('TravelHistory',back_populates='squire', cascade='all, delete-orphan')

class Course(Base):
    __tablename__ = 'courses'

    id           = Column(Integer, primary_key=True)
    course_name  = Column(String(255), nullable=False)
    description  = Column(Text)

    # One course ⇢ many quests
    quests = relationship("Quest", back_populates="course", cascade="all, delete-orphan")

class Team(Base):
    __tablename__ = 'teams'

    id         = Column(Integer, primary_key=True)
    team_name  = Column(String(255), unique=True, nullable=False)
    gold       = Column(Integer, default=0)
    reputation = Column(Integer, default=0)

    def __repr__(self):
        return (f"<Team(name={self.team_name!r}, "
                f"gold={self.gold}, rep={self.reputation})>")

    messages = relationship('TeamMessage',    back_populates='team',    cascade='all, delete-orphan')

class TravelHistory(Base):
    __tablename__ = 'travel_history'

    id           = Column(Integer, primary_key=True)
    squire_id    = Column(Integer, ForeignKey('squires.id'), nullable=False)
    x_coordinate = Column(Integer, nullable=False)
    y_coordinate = Column(Integer, nullable=False)
    visited_at   = Column(DateTime, server_default=func.now())

    # Relationship back to Squire
    squire = relationship('Squire', back_populates='travel_history')

    def __repr__(self):
        ts = self.visited_at.strftime('%Y-%m-%d %H:%M:%S') if self.visited_at else None
        return f"<TravelHistory(squire_id={self.squire_id}, x={self.x_coordinate}, y={self.y_coordinate}, at={ts})>"


class Quest(Base):
    __tablename__ = 'quests'

    id                 = Column(Integer, primary_key=True)
    quest_name         = Column(String(255), nullable=False)
    description        = Column(Text,   nullable=False)
    learning_objective = Column(Text)
    status             = Column(Enum('active','completed','locked'), default='locked')
    reward             = Column(Text)
    effective_against  = Column(String(255))
    course_id          = Column(Integer, ForeignKey('courses.id'), nullable=False)

    # Backlink to course
    course  = relationship("Course", back_populates="quests")
    # One quest ⇢ many riddles
    riddles = relationship("Riddle", back_populates="quest", cascade="all, delete-orphan")
    multiple_choice_questions = relationship('MultipleChoiceQuestion',back_populates='quest', cascade='all, delete-orphan')
    squire_statuses = relationship('SquireQuestStatus',back_populates='quest', cascade='all, delete-orphan')
    riddle_progress = relationship('SquireRiddleProgress',back_populates='quest',cascade='all, delete-orphan')
    true_false_questions = relationship('TrueFalseQuestion',back_populates='quest',cascade='all, delete-orphan')



class SquireQuestion(Base):
    __tablename__ = 'squire_questions'

    id                 = Column(Integer, primary_key=True)
    squire_id          = Column(Integer, ForeignKey('squires.id'), nullable=False)
    question_id        = Column(Integer, nullable=False)
    question_type      = Column(Enum('true_false','riddle','multiple_choice'), nullable=False)
    answered_correctly = Column(Boolean, default=False)

    # Relationship back to Squire
    squire = relationship('Squire', back_populates='questions')

    def __repr__(self):
        return (f"<SquireQuestion(squire_id={self.squire_id}, "
                f"type={self.question_type!r}, id={self.question_id}, "
                f"correct={self.answered_correctly})>")

class SquireRiddleProgress(Base):
    __tablename__ = 'squire_riddle_progress'

    id                 = Column(Integer, primary_key=True)
    squire_id          = Column(Integer, ForeignKey('squires.id'), nullable=False)
    riddle_id          = Column(Integer, ForeignKey('riddles.id'), nullable=False)
    quest_id           = Column(Integer, ForeignKey('quests.id'), nullable=False)
    answered_correctly = Column(Boolean, default=True)

    # Relationships
    squire = relationship('Squire', back_populates='riddle_progress')
    riddle = relationship('Riddle', back_populates='squire_progress')
    quest  = relationship('Quest', back_populates='riddle_progress')


class Riddle(Base):
    __tablename__ = 'riddles'

    id          = Column(Integer, primary_key=True)
    riddle_text = Column(Text,    nullable=False)
    answer      = Column(String(255), nullable=False)
    hint        = Column(Text)
    reward      = Column(Integer, default=50)
    quest_id    = Column(Integer, ForeignKey('quests.id'), nullable=False)
    difficulty  = Column(Enum('Easy','Medium','Hard'), default='Easy')
    word_length_hint = Column(String(255))
    word_count = Column(Integer)

    # Backlink to quest
    quest = relationship("Quest", back_populates="riddles")
    squire_progress = relationship('SquireRiddleProgress',back_populates='riddle',cascade='all, delete-orphan')
    treasure_chests = relationship('TreasureChest',back_populates='riddle',cascade='all, delete-orphan')

class Enemy(Base):
    __tablename__ = 'enemies'

    id           = Column(Integer, primary_key=True)
    enemy_name   = Column(String(255), unique=True, nullable=False)
    description  = Column(Text,   nullable=False)
    weakness     = Column(String(255), nullable=False)
    gold_reward  = Column(Integer, nullable=False)
    xp_reward    = Column(Integer, nullable=False)
    hunger_level = Column(Integer, default=0)
    max_hunger   = Column(Integer, nullable=False)
    is_boss      = Column(Boolean, default=False)
    min_level    = Column(Integer, default=1)
    static_image = Column(String(255))

    true_false_questions = relationship('TrueFalseQuestion',back_populates='enemy', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Enemy(name={self.enemy_name!r}, boss={self.is_boss})>"

class Inventory(Base):
    __tablename__ = 'inventory'

    id               = Column(Integer, primary_key=True)
    squire_id        = Column(Integer, ForeignKey('squires.id'), nullable=False)
    item_name        = Column(String(255), nullable=False)
    description      = Column(Text)
    uses_remaining   = Column(Integer, default=1)
    item_type        = Column(Enum('food','special','gear','arms'), nullable=True)
    effective_against= Column(String(255))

    @property
    def max_uses(self):
        db = db_session()
        shop_item = db.query(ShopItem).filter_by(name=self.item_name).first()
        return shop_item.uses if shop_item else 0

    # relationship back to Squire
    squire = relationship('Squire', back_populates='inventory')

    def __repr__(self):
        return f"<Inventory(item_name={self.item_name!r}, uses={self.uses_remaining})>"

class WizardItem(Base):
    __tablename__ = 'wizard_items'

    id         = Column(Integer, primary_key=True)
    item_name  = Column(String(255))
    uses       = Column(Integer)
    min_level  = Column(Integer, default=1)

    def __repr__(self):
        return f"<WizardItem(name={self.item_name!r}, uses={self.uses}, min_level={self.min_level})>"

class Job(Base):
    __tablename__ = 'jobs'

    id          = Column(Integer, primary_key=True)
    job_name    = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=False)
    min_payout  = Column(Integer, nullable=False)
    max_payout  = Column(Integer, nullable=False)

    def __repr__(self):
        return f"<Job(name={self.job_name!r}, payout_range=({self.min_payout}-{self.max_payout}))>"

class MapFeature(Base):
    __tablename__ = 'map_features'

    id            = Column(Integer, primary_key=True)
    x_coordinate  = Column(Integer, nullable=False)
    y_coordinate  = Column(Integer, nullable=False)
    terrain_type  = Column(String(50), nullable=False)
    squire_id     = Column(Integer, ForeignKey('squires.id'), nullable=True)

    # link back to Squire (if you have a Squire model defined)
    squire = relationship('Squire', back_populates='map_features')

    def __repr__(self):
        return f"<MapFeature(x={self.x_coordinate}, y={self.y_coordinate}, terrain={self.terrain_type!r})>"

class MultipleChoiceQuestion(Base):
    __tablename__ = 'multiple_choice_questions'

    id             = Column(Integer, primary_key=True)
    question_text  = Column(String(255))
    optionA        = Column(String(255))
    optionB        = Column(String(255))
    optionC        = Column(String(255))
    optionD        = Column(String(255))
    correctAnswer  = Column(String(1))
    quest_id       = Column(Integer, ForeignKey('quests.id'))

    # relationship back to Quest
    quest = relationship('Quest', back_populates='multiple_choice_questions')

    def __repr__(self):
        return (f"<MCQ(id={self.id}, quest_id={self.quest_id}, "
                f"correct={self.correctAnswer!r})>")

class TrueFalseQuestion(Base):
    __tablename__ = 'true_false_questions'

    id             = Column(Integer, primary_key=True)
    question       = Column(Text,    nullable=False)
    correct_answer = Column(Boolean, nullable=False)
    quest_id       = Column(Integer, ForeignKey('quests.id'), nullable=False)
    enemy_id       = Column(Integer, ForeignKey('enemies.id'), default=1)

    # Relationships
    quest          = relationship('Quest', back_populates='true_false_questions')
    enemy          = relationship('Enemy', back_populates='true_false_questions')

    def __repr__(self):
        return (f"<TrueFalseQuestion(id={self.id}, quest_id={self.quest_id}, "
                f"enemy_id={self.enemy_id}, correct={self.correct_answer})>")


class ShopItem(Base):
    __tablename__ = 'shop_items'

    id          = Column(Integer, primary_key=True)
    item_name   = Column(String(255), unique=True, nullable=False)
    description = Column(Text, nullable=False)
    price       = Column(Integer, nullable=False)
    uses        = Column(Integer, nullable=False)
    item_type   = Column(Enum('food','special','gear','arms'), nullable=True)
    min_level   = Column(Integer, default=1)
    available_to_trader = Column(Boolean)

    def __repr__(self):
        return (f"<ShopItem(name={self.item_name!r}, price={self.price}, "
                f"uses={self.uses}, min_level={self.min_level})>")

class SquireQuestStatus(Base):
    __tablename__ = 'squire_quest_status'

    id         = Column(Integer, primary_key=True)
    squire_id  = Column(Integer, ForeignKey('squires.id'), nullable=False)
    quest_id   = Column(Integer, ForeignKey('quests.id'), nullable=False)
    status     = Column(Enum('active','completed','locked'), nullable=True)

    # Relationships
    squire     = relationship('Squire', back_populates='quest_statuses')
    quest      = relationship('Quest', back_populates='squire_statuses')
    treasure_chests = relationship('TreasureChest',back_populates='squire_quest',cascade='all, delete-orphan')

    __table_args__ = (
        UniqueConstraint('squire_id', 'quest_id', name='uq_squire_quest'),
    )


class TeamMessage(Base):
    __tablename__ = 'team_messages'

    id         = Column(Integer, primary_key=True)
    team_id    = Column(Integer, ForeignKey('teams.id'), nullable=True)
    message    = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    # Link back to Team
    team       = relationship('Team', back_populates='messages')

    def __repr__(self):
        ts = self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        return f"<TeamMessage(team_id={self.team_id}, created_at={ts})>"

class TreasureChest(Base):
    __tablename__ = 'treasure_chests'

    id               = Column(Integer, primary_key=True)
    x_coordinate     = Column(Integer, nullable=False)
    y_coordinate     = Column(Integer, nullable=False)
    riddle_id        = Column(Integer, ForeignKey('riddles.id'), nullable=False)
    gold_reward      = Column(Integer, default=0)
    xp_reward        = Column(Integer, default=0)
    food_reward      = Column(Integer, default=0)
    special_item     = Column(String(255))
    is_opened        = Column(Boolean, default=False)
    squire_quest_id  = Column(Integer, ForeignKey('squire_quest_status.id'))

    # Relationships
    riddle           = relationship('Riddle', back_populates='treasure_chests')
    squire_quest     = relationship('SquireQuestStatus', back_populates='treasure_chests')

    def __repr__(self):
        return (f"<TreasureChest(x={self.x_coordinate}, y={self.y_coordinate}, "
                f"opened={self.is_opened})>")

class XpThreshold(Base):
    __tablename__ = 'xp_thresholds'

    id    = Column(Integer, primary_key=True)
    level = Column(Integer, nullable=True)
    min   = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<XpThreshold(level={self.level}, min_xp={self.min})>"

# ────────────── Initialize DB ──────────────

def init_db():
    import db  # Ensure models are registered
    Base.metadata.create_all(bind=engine)

# ────────────── Flask Teardown Helper ──────────────

# Add error handling for database operations
def safe_commit():
    try:
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        flash("An error occurred. Please try again.")
        logging.error(f"Database error: {e}")
        raise

# Add this somewhere accessible for debugging
def get_pool_status():
    return {
        'pool_size': engine.pool.size(),
        'checkedin': engine.pool.checkedin(),
        'checkedout': engine.pool.checkedout(),
        'overflow': engine.pool.overflow()
    }
    logging.info(f"Pool status: {status}")
    return status
