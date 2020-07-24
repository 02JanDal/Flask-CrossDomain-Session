# -*- coding: utf-8 -*-
#
# This file is part of Flask-CrossDomain-Session
# Copyright (C) 2020 Jan Dalheimer

from flask import Flask, session, render_template_string
from flask.testing import FlaskClient
from flask_sqlalchemy import SQLAlchemy
from flask_testing import TestCase
from werkzeug.test import _TestCookieJar

from flask_crossdomain_session import CrossDomainSession
from flask_crossdomain_session.model import make_session_class, make_session_instance_class, SessionType


def body(response):
    return response.data.decode(response.charset)


def new_inject_wsgi(self, environ):
    cvals = ["%s=%s" % (c.name, c.value) for c in self if c.domain == ('.' + environ['HTTP_HOST'])]

    if cvals:
        environ["HTTP_COOKIE"] = "; ".join(cvals)
    else:
        environ.pop("HTTP_COOKIE", None)


_TestCookieJar.inject_wsgi = new_inject_wsgi


class CookieTestCase(TestCase):
    def create_app(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.config['TRAP_HTTP_EXCEPTIONS'] = False
        app.config['PROPAGATE_EXCEPTIONS'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.db = SQLAlchemy(app)

        class User(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)

        self.Session = make_session_class(self.db, User)
        self.SessionInstance = make_session_instance_class(self.db, self.Session)
        self.db.create_all()

        @app.route('/')
        def home():
            return render_template_string('{{ flask_crossdomain_code() }}\n\n\nHello, World!')

        @app.route('/set/<key>/<value>')
        def set(key, value):
            session[key] = value
            return session[key]

        @app.route('/get/<key>')
        def get(key):
            return session[key]

        app.config['CROSSDOMAIN_PRIMARY_SERVERNAME'] = 'primary.test'
        self.crossdomain = CrossDomainSession(app)
        self.crossdomain.session_instance_class = self.SessionInstance

        @self.crossdomain.domain_loader
        def domain_loader():
            return ['primary.test', 'secondary.test', 'another.test']

        return app

    def get_cookie(self, name, domain):
        return next((c for c in self.client.cookie_jar if c.name == name and c.value and c.domain == ('.' + domain)),
                    None)

    def get_cookie_value(self, name, domain):
        cookie = self.get_cookie(name, domain)
        return cookie.value if cookie else None

    def assertHasCookie(self, name, domain):
        self.assertIsNotNone(self.get_cookie(name, domain))

    def assertCookieValueEqual(self, name, domain, value):
        self.assertHasCookie(name, domain)
        self.assertEqual(self.get_cookie_value(name, domain), value)


class SimpleTests(CookieTestCase):
    client: FlaskClient

    def test_no_cookie_if_disabled(self):
        self.crossdomain.may_set_cookie_loader(lambda: False)
        resp = self.client.get('/', 'https://primary.test/')
        self.assert200(resp)
        self.assertIsNone(self.get_cookie('session', 'primary.test'))

    def test_first_visit_to_primary_sets_cookie(self):
        resp = self.client.get('/', 'https://primary.test/')
        self.assert200(resp)
        self.assertHasCookie('session', 'primary.test')

    def test_first_visit_to_secondary_sets_cookie(self):
        resp = self.client.get('/', 'https://secondary.test/')
        self.assert200(resp)
        self.assertHasCookie('session', 'secondary.test')

    def test_next_visit_keeps_cookie(self):
        self.client.get('/', 'https://secondary.test/')
        self.assertHasCookie('session', 'secondary.test')
        old_c = self.get_cookie_value('session', 'secondary.test')
        self.client.get('/', 'https://secondary.test/')
        self.assertCookieValueEqual('session', 'secondary.test', old_c)

    def test_session_keeps_data(self):
        self.client.get('/set/foo/bar', 'https://another.test/')
        resp = self.client.get('/get/foo', 'https://another.test/')
        self.assertEqual('bar', resp.data.decode(resp.charset))

    def test_header_auth(self):
        sess = self.Session(type=SessionType.api, data=dict(foo='bar'))
        sess.generate_token()
        self.db.session.add(sess)
        self.db.session.commit()
        headers = dict(Authorization='Bearer ' + sess.token)

        resp = self.client.get('/get/foo', headers=headers)
        self.assert200(resp)
        self.assertEqual('bar', body(resp))
        self.assertIsNone(self.get_cookie('session', 'primary.test'))

        self.client.get('/set/foo/baz', headers=headers)
        resp = self.client.get('/get/foo', headers=headers)
        self.assertEqual('baz', body(resp))


class ErrorTests(CookieTestCase):
    def assertError(self, resp, message):
        self.assert400(resp)
        self.assertDictEqual(dict(result='error', message=message), resp.json)

    def test_invalid_method(self):
        resp = self.client.get('/crossdomain', 'https://secondary.test/')
        self.assert405(resp)

    def test_missing_action(self):
        resp = self.client.post('/crossdomain', 'https://primary.test/', json=dict(foo='bar'))
        self.assertError(resp, 'missing "action"')

    def test_invalid_host(self):
        resp = self.client.post('/crossdomain', 'https://secondary.test/', json=dict(action='check'))
        self.assertError(resp, 'invalid hostname')

    def test_missing_token_or_is_new(self):
        resp = self.client.post('/crossdomain', 'https://primary.test/', json=dict(
            action='check', current_token='', current_is_new=True
        ), headers=dict(Origin='https://secondary.test'))
        self.assertError(resp, 'missing one or more of "current_token" or "current_is_new"')
        resp = self.client.post('/crossdomain', 'https://primary.test/', json=dict(
            action='check', current_token='deadbeef', current_is_new=None
        ))
        self.assertError(resp, 'missing one or more of "current_token" or "current_is_new"')

    def test_missing_or_wrong_origin(self):
        resp = self.client.post('/crossdomain', 'https://primary.test/', json=dict(
            action='check', current_token='deadbeef', current_is_new=False
        ))
        self.assertError(resp, 'invalid or missing Origin')
        resp = self.client.post('/crossdomain', 'https://primary.test/', json=dict(
            action='check', current_token='deadbeef', current_is_new=False
        ), headers=dict(Origin='https://competitor.io'))
        self.assertError(resp, 'invalid or missing Origin')

    def test_missing_token(self):
        resp = self.client.post('/crossdomain', 'https://secondary.test/', json=dict(
            action='replace', foo='bar'
        ))
        self.assertError(resp, 'missing "token"')

    def test_unknown_action(self):
        resp = self.client.post('/crossdomain', 'https://primary.test/', json=dict(
            action='eat'
        ))
        self.assertError(resp, 'invalid value for "action"')


class ScenarioTests(CookieTestCase):
    client: FlaskClient

    def test_visit_primary_then_secondary(self):
        resp = self.client.get('/', 'https://primary.test/')
        primary_token = self.get_cookie_value('session', 'primary.test')
        self.assertNotIn('performCrossDomainSessionCheck', body(resp))
        resp = self.client.get('/', 'https://secondary.test/')
        self.assertIn('performCrossDomainSessionCheck', body(resp))
        # the Javascript results in the following requests:
        resp = self.client.post('/crossdomain', 'https://primary.test/crossdomain', json=dict(
            action='check',
            current_token=self.get_cookie_value('session', 'secondary.test'),
            current_is_new=True
        ), headers=dict(Origin='https://secondary.test'))
        self.assert200(resp)
        self.assertDictEqual(dict(result='replace', new_token=primary_token), resp.json)
        # as a response to that we post:
        resp = self.client.post('/crossdomain', 'https://secondary.test/crossdomain', json=dict(
            action='replace',
            token=primary_token
        ), headers=dict(Origin='https://secondary.test'))
        self.assert200(resp)
        self.assertDictEqual(dict(result='replaced'), resp.json)
        self.assertCookieValueEqual('session', 'secondary.test', primary_token)

    def test_visit_secondary_then_primary(self):
        resp = self.client.get('/', 'https://secondary.test/')
        self.assertIn('performCrossDomainSessionCheck', body(resp))
        secondary_token = self.get_cookie_value('session', 'secondary.test')
        # the Javascript results in the following requests:
        resp = self.client.post('/crossdomain', 'https://primary.test/crossdomain', json=dict(
            action='check',
            current_token=self.get_cookie_value('session', 'secondary.test'),
            current_is_new=False
        ), headers=dict(Origin='https://secondary.test'))
        self.assertDictEqual(dict(result='use_current'), resp.json)

        self.client.get('/', 'https://primary.test/')
        self.assertCookieValueEqual('session', 'primary.test', secondary_token)

    def test_revisit(self):
        self.test_visit_secondary_then_primary()

        self.client.get('/', 'https://secondary.test/')
        # the JavaScript results in the following requests:
        resp = self.client.post('/crossdomain', 'https://primary.test/crossdomain', json=dict(
            action='check',
            current_token=self.get_cookie_value('session', 'secondary.test'),
            current_is_new=False
        ), headers=dict(Origin='https://secondary.test'))
        self.assertDictEqual(dict(result='use_current'), resp.json)

        primary_token = self.get_cookie_value('session', 'primary.test')
        secondary_token = self.get_cookie_value('session', 'secondary.test')
        self.assertEqual(primary_token, secondary_token)
