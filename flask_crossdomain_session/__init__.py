# -*- coding: utf-8 -*-
#
# This file is part of Flask-CrossDomain-Session
# Copyright (C) 2020 Jan Dalheimer

from importlib.resources import read_text
from typing import Callable, List, Iterable, Type

from flask import Flask, current_app, render_template_string, url_for, request, jsonify, session
from markupsafe import Markup

from flask_crossdomain_session.model import SessionInstanceMixin, SessionType
from flask_crossdomain_session.session_interface import ServerSessionInterface, SessionValueAccessor

# flask.session is actually a SessionValueAccessor
session: SessionValueAccessor


class CrossDomainSession:
    def __init__(self, app: Flask = None):
        self.app = app
        if app is not None:
            self.init_app(app)

        self._domain_loader = lambda: []
        self._may_set_cookie_loader = lambda: True
        self._session_instance_class = None

    def init_app(self, app: Flask):
        app.config.setdefault('CROSSDOMAIN_PRIMARY_SERVERNAME', app.config.get('SERVER_NAME', None))
        app.config.setdefault('CROSSDOMAIN_PATH', '/crossdomain')

        app.session_interface = ServerSessionInterface(self)

        app.add_url_rule(app.config['CROSSDOMAIN_PATH'], 'flask_crossdomain',
                         self._handle_crossdomain_route, methods=('POST',))

        @app.context_processor
        def context_processor():
            return dict(flask_crossdomain_code=self._html)

        @app.after_request
        def add_crossdomain_headers(response):
            if request.endpoint != 'static':
                if 'Origin' not in request.headers:
                    return response
                origin_domain = request.headers['Origin'].split('/')[-1].split(':')[0]
                is_known_domain = origin_domain in self.domains
                is_localhost = origin_domain == 'localhost'
                if is_known_domain or (app.debug and is_localhost):
                    response.headers['Access-Control-Allow-Origin'] = request.headers['Origin']
                    response.headers['Access-Control-Allow-Credentials'] = 'true'
                    response.headers['Access-Control-Allow-Headers'] = ', '.join(sorted(response.headers.keys()))
                    response.headers['Access-Control-Allow-Methods'] = 'POST, DELETE, HEAD, PATCH, GET, OPTIONS'
            else:
                response.headers.add('Access-Control-Allow-Origin', '*')
            return response

    @property
    def primary_servername(self):
        return current_app.config['CROSSDOMAIN_PRIMARY_SERVERNAME']

    def _html(self):
        url = '{}://{}{}'.format(current_app.config['PREFERRED_URL_SCHEME'],
                                 self.primary_servername,
                                 url_for('flask_crossdomain'))
        return Markup(render_template_string(read_text(__name__, 'injection.html'),
                                             flask_crossdomain_is_primary=self.primary_servername == request.host,
                                             flask_crossdomain_url=url))

    def domain_loader(self, func: Callable[[], Iterable[str]]):
        """
        Register the method that returns the list of valid domain names.
        """
        self._domain_loader = func

    @property
    def domains(self) -> List[str]:
        """
        Returns the list of valid domain names.
        """
        return list(self._domain_loader())

    def may_set_cookie_loader(self, func: Callable[[], bool]):
        """
        Register the method that returns true or false depending on if we may set a cookie or not.

        Usually used to prevent populating a session if the user has not accepted cookies.
        """
        self._may_set_cookie_loader = func

    @property
    def may_set_cookie(self) -> bool:
        """
        Returns true if we may set a cookie.
        """
        return self._may_set_cookie_loader()

    @property
    def session_instance_class(self) -> Type[SessionInstanceMixin]:
        return self._session_instance_class

    @session_instance_class.setter
    def session_instance_class(self, cls: Type[SessionInstanceMixin]):
        self._session_instance_class = cls

    def _handle_crossdomain_route(self):
        if 'action' not in request.json:
            return jsonify(result='error', message='missing "action"'), 400
        action = request.json['action']
        if action == 'check':
            if request.host != self.primary_servername:
                return jsonify(result='error', message='invalid hostname'), 400

            token = request.json.get('current_token')
            is_new = request.json.get('current_is_new')
            if not token or is_new is None:
                return jsonify(result='error',
                               message='missing one or more of "current_token" or "current_is_new"'), 400
            if 'Origin' not in request.headers or request.headers['Origin'].split('/')[-1] not in self.domains:
                return jsonify(result='error', message='invalid or missing Origin'), 400
            origin_session = self.session_instance_class.session_class.find_by_token(token)
            if token == session.instance.session.token:
                # origin token is same as primary server token -> just use it
                result = 'use_current'
            elif session.new:
                # primary server token was created on this request -> use origin token and set primary to origin
                result = 'replace_primary'
            elif is_new or origin_session is None:
                # origin token was just created and primary server token already exists, or origin token doesn't
                # actually match a session -> use primary server token
                result = 'replace'
            else:
                # shouldn't usually happen, either should be new, but may happen in case of failed AJAX requests etc
                origin_user = origin_session.user
                primary_user = session.instance.session.user
                if origin_user and primary_user and origin_user != primary_user:
                    # both origin and primary are logged in differently,
                    # use origin and don't touch the separate login on primary
                    result = 'use_current'
                elif primary_user:
                    # primary logged in (or both and same user), use primary token since it's likely the same as any
                    # other non-primaries we have visited
                    result = 'replace'
                elif origin_user:
                    # origin logged in -> set that token on primary
                    result = 'replace_primary'
                else:
                    # neither logged in -> set token to that of primary in order to not diverge from other domains
                    result = 'replace_primary'

            if result == 'replace_primary':
                new_instance = self.session_instance_class.from_request(
                    current_app, request, token=token, type_=SessionType.cookie)
                session.instance.session.delete()
                session.replace_instance(new_instance)
                result = 'use_current'

            if result == 'use_current':
                return jsonify(result=result)
            elif result == 'replace':
                return jsonify(result=result, new_token=session.instance.session.token)
        elif action == 'replace':
            token = request.json.get('token')
            if not token:
                return jsonify(result='error', message='missing "token"'), 400
            if session['_token'] != token:
                session.instance.session.delete()
                session.replace_instance(
                    self.session_instance_class.from_request(current_app, request,
                                                             token=token, type_=SessionType.cookie))
            return jsonify(result='replaced')
        else:
            return jsonify(result='error', message='invalid value for "action"'), 400
