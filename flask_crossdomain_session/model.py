# -*- coding: utf-8 -*-
#
# This file is part of Flask-CrossDomain-Session
# Copyright (C) 2020 Jan Dalheimer

from datetime import datetime
from secrets import token_hex
from enum import Enum
from typing import Any, Iterable, Optional, Type

from flask import Request


class SessionType(Enum):
    cookie = 1
    api = 2


class SessionMixin:
    type: SessionType
    token: str
    ip: Optional[str]
    user_agent: Optional[str]
    user: Optional[Any]
    data: dict
    instances: Iterable["SessionInstanceMixin"]

    def __init__(self, *args, **kwargs):
        super(SessionMixin, self).__init__(*args, **kwargs)

    def generate_token(self):
        self.token = token_hex(32)

    @classmethod
    def find_by_token(cls, token: str, type_: SessionType = None):  # pragma: no cover
        raise NotImplementedError()

    def save(self):  # pragma: no cover
        raise NotImplementedError()

    def delete(self):  # pragma: no cover
        raise NotImplementedError()

    def is_new(self):  # pragma: no cover
        raise NotImplementedError()

    @classmethod
    def commit(cls):  # pragma: no cover
        raise NotImplementedError()


def make_session_class(db, user_class):
    class Session(SessionMixin, db.Model):
        id = db.Column(db.Integer, primary_key=True, nullable=False)
        type = db.Column(db.Enum(SessionType), nullable=False)

        token = db.Column(db.String(128), unique=True, nullable=False)

        ip = db.Column(db.String(64), nullable=True)
        user_agent = db.Column(db.String(512), nullable=True)

        user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True)
        user = db.relationship(user_class)

        data = db.Column(db.JSON, nullable=False)

        instances = db.relationship('SessionInstance', back_populates='session',
                                    cascade='all, delete-orphan', passive_deletes=True)

        @classmethod
        def find_by_token(cls, token: str, type_: SessionType = None):
            if type_ is None:
                return cls.query.filter_by(token=token).first()
            else:
                return cls.query.filter_by(token=token, type=type_).first()

        def save(self):
            db.session.add(self)

        def delete(self):
            if self.id:
                db.session.delete(self)
            else:
                db.session.expunge(self)

        def is_new(self):
            return self.id is None

        @classmethod
        def commit(cls):
            db.session.commit()

    return Session


class SessionInstanceMixin:
    created_at: datetime
    domain: str

    session: SessionMixin
    session_class: Type[SessionMixin]

    def __init__(self, *args, **kwargs):
        super(SessionInstanceMixin, self).__init__(*args, **kwargs)

    @classmethod
    def find_by_session_and_domain(cls, session: SessionMixin, domain: str):  # pragma: no cover
        raise NotImplementedError()

    @classmethod
    def from_request(cls, app, request: Request, token=None, host=None, type_=None) -> "SessionInstanceMixin":
        if token and not type_:
            raise ValueError('need to provide type_ if token provided')  # pragma: no cover

        if not token:
            if app.session_cookie_name in request.cookies:
                token = request.cookies[app.session_cookie_name]
                type_ = SessionType.cookie
            elif 'Authorization' in request.headers and request.headers['Authorization'].startswith('Bearer '):
                token = request.headers['Authorization'].split(' ')[1]
                type_ = SessionType.api
            else:
                token = None

        if not host:
            host = request.host
        domain = '.'.join(host.split(':')[0].split('.')[-2:])

        session = cls.session_class.find_by_token(token, type_) if token else None
        if token is None or session is None:
            session = cls.session_class(ip=request.remote_addr or '',
                                        user_agent=request.user_agent.string,
                                        type=SessionType.cookie)
            session.generate_token()
            session.data = dict(_token=session.token)
            session.save()
            instance = None
        else:
            instance = cls.find_by_session_and_domain(session, domain)

        if not instance:
            instance = cls(session=session, created_at=datetime.utcnow(), domain=domain)
            instance.save()

        return instance

    def save(self):
        raise NotImplementedError()  # pragma: no cover


def make_session_instance_class(db, sess_class):
    class SessionInstance(SessionInstanceMixin, db.Model):
        id = db.Column(db.Integer, primary_key=True, nullable=False)

        session_id = db.Column(db.Integer, db.ForeignKey('session.id', ondelete='CASCADE'), nullable=False)
        session = db.relationship('Session', back_populates='instances', lazy='joined')
        session_class = sess_class

        created_at = db.Column(db.DateTime, nullable=False)

        domain = db.Column(db.String(64), nullable=False)

        @classmethod
        def from_request(cls, app, request: Request, token=None, host=None, type_=None):
            with db.session.no_autoflush:
                return super(SessionInstance, cls).from_request(app, request, token, host, type_)

        @classmethod
        def find_by_session_and_domain(cls, session: SessionMixin, domain: str):
            return cls.query.filter_by(session=session, domain=domain).first()

        def save(self):
            db.session.add(self)

    return SessionInstance
