from sqlalchemy import create_engine, Column, Integer, ForeignKey, String, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from decouple import config
import datetime

DATABASE_URL = config('DATABASE_URL')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
engine = create_engine(DATABASE_URL)

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    is_banned = Column(Boolean, default=False)  # Add ban status
    songs = relationship('SongRequest', backref='user')
    subscriptions = relationship('Subscription', backref='user')

class SongRequest(Base):
    __tablename__ = 'songs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    spotify_id = Column(String, nullable=False)
    song_id_in_group = Column(Integer)
    group_id = Column(Integer)

class Subscription(Base):
    __tablename__ = 'subscriptions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    start_date = Column(DateTime, default=datetime.datetime.utcnow)
    end_date = Column(DateTime)
    approved = Column(Integer, default=0)

Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)
session = Session()
