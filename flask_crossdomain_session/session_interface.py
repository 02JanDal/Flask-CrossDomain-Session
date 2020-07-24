# -*- coding: utf-8 -*-
#
# This file is part of Flask-CrossDomain-Session
# Copyright (C) 2020 Jan Dalheimer

from flask import request
from flask.sessions import SessionInterface, SecureCookieSession

from flask_crossdomain_session.model import SessionInstanceMixin, SessionMixin, SessionType


class SessionValueAccessor(SecureCookieSession):
    def __init__(self, instance: SessionInstanceMixin, is_new):
        self._instance = instance
        self._session = instance.session
        super(SessionValueAccessor, self).__init__(self._session.data)
        self.new = is_new

    @property
    def instance(self) -> SessionInstanceMixin:
        return self._instance

    def replace_instance(self, new_instance):
        self._instance = new_instance
        self._session = self._instance.session
        self.clear()
        self.update(self._session.data)
        self.modified = False
        self.accessed = False


class DummySession(SecureCookieSession):
    pass


class ServerSessionInterface(SessionInterface):
    def __init__(self, extension):
        self._extension = extension

    def open_session(self, app, request_):
        is_static_endpoint = request_.endpoint and (
            request_.endpoint.endswith('.static') or request_.endpoint == 'static'
        )
        if is_static_endpoint or request_.method == 'OPTIONS' or not self._extension.may_set_cookie:
            return DummySession()

        instance = self._extension.session_instance_class.from_request(app, request_)
        is_new = instance.session.is_new()
        instance.session.commit()
        return SessionValueAccessor(instance, is_new)

    def save_session(self, app, session, response):
        if isinstance(session, DummySession):
            return

        sess: SessionMixin = session.instance.session

        if session.accessed and sess.type == SessionType.cookie:
            response.vary.add('Cookie')

        if session.new or (session.modified and dict(session) != sess.data):
            # TODO: is this still needed?
            # db.session.rollback()
            sess.data = dict(session)
            sess.commit()

        cookie_name = app.session_cookie_name
        token_changed = sess.token != request.cookies.get(cookie_name)
        if sess.type == SessionType.cookie and (session.new or cookie_name not in request.cookies or token_changed):
            response.set_cookie(
                cookie_name,
                sess.token,
                expires=self.get_expiration_time(app, session),
                domain=session.instance.domain,
                secure=self.get_cookie_secure(app),
                httponly=self.get_cookie_httponly(app),
                path=self.get_cookie_path(app),
                samesite=self.get_cookie_samesite(app)
            )
