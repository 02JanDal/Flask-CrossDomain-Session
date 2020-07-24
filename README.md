# Flask-CrossDomain-Session

[![GitHub Workflow Status](https://img.shields.io/github/workflow/status/02JanDal/Flask-CrossDomain-Session/Test%20and%20publish?logo=github)](https://github.com/02JanDal/Flask-CrossDomain-Session/actions)
[![Codacy branch grade](https://img.shields.io/codacy/grade/142626ba133e4df1a65dd5d7159764cd/master?logo=codacy)](https://app.codacy.com/manual/02JanDal/Flask-CrossDomain-Session/dashboard)
[![Codacy branch coverage](https://img.shields.io/codacy/coverage/142626ba133e4df1a65dd5d7159764cd/master?logo=codacy)](https://app.codacy.com/manual/02JanDal/Flask-CrossDomain-Session/dashboard)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/Flask-CrossDomain-Session?logo=python)](https://pypi.org/project/Flask-CrossDomain-Session/)
[![PyPI - Status](https://img.shields.io/pypi/status/Flask-CrossDomain-Session)](https://pypi.org/project/Flask-CrossDomain-Session/)
[![PyPI](https://img.shields.io/pypi/v/Flask-CrossDomain-Session)](https://pypi.org/project/Flask-CrossDomain-Session/)
[![License](https://img.shields.io/github/license/02JanDal/Flask-CrossDomain-Session)](https://github.com/02JanDal/Flask-CrossDomain-Session/blob/master/LICENSE)

## About

Flask-CrossDomain-Session is a Flask extension that simplifies the task of keeping sessions spanning multiple domains.

## Installation

Simply run:

```bash
pip install Flask-CrossDomain-Session
```

## Usage

Normal usage looks something like this:

```python
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_crossdomain_session import CrossDomainSession, make_session_class, make_session_instance_class

app = Flask(__name__)
app.config['CROSSDOMAIN_PRIMARY_SERVERNAME'] = 'primary.tld'

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

Session = make_session_class(db, User)
SessionInstance = make_session_instance_class(db, Session)

crossdomain = CrossDomainSession(app)
crossdomain.session_instance_class = SessionInstance

@crossdomain.domain_loader
def domain_loader():
    return ['primary.tld', 'secondary.tld', 'another.tld']
```

And add this somewhere in your Jinja2 templates: `{{ flask_crossdomain_session_code() }}`

You can then use `flask.session` like normal, and if everything works correctly it'll have the same content
regardless of which of your domains you visit.

### Configuration

| Option                           | Default        | Description                                                        |
|----------------------------------|----------------|--------------------------------------------------------------------|
| `CROSSDOMAIN_PRIMARY_SERVERNAME` | `SERVER_NAME`  | The primary domain name, other domains make AJAX calls to this one |
| `CROSSDOMAIN_PATH`               | `/crossdomain` | The path of the page to which AJAX calls are made                  |

## How it works

All sessions are stored in a database (convenience functions to use SQLAlchemy are included, but you should be able
to use any other by manually inheriting from `SessionMixin` and `SessionInstanceMixin`). When loading a page that
contains a cookie with a session token a session matching that token is loaded from the database. If no such cookie
is present, or if no matching session can be found, a new session is created and its token returned in a new cookie.

When loading a page that is not the primary a bit of JavaScript is injected into the page. It first checks in
`localStorage` if a recent AJAX check has been made, and if not an AJAX request is sent. That AJAX request has an
action called `check`, the current session token and a boolean indicating if the session is new (was created in the
most recent request). It is sent to the primary domain, that way any session cookie already set on the primary domain
is also included in the request. The server then does one of these things:

1.  If both the token of the current domain (as sent in the AJAX body) and of the primary domain (as included in the
    cookies) are equal the server just returns `use_current`, nothing then needs to be done by the client.
2.  If the session on the primary domain didn't already exist it is replaced by the one that the token from the current
    domain (as sent in the AJAX body) represents, and `use_current` is returned.
3.  If a session on the primary domain already existed and the session on the current domain was new we instead
    return `replace` with the token of the primary domains session. The JavaScript then sends a new AJAX request
    to the current domain with the action `replace` and the token of the primary domains session, which replaces
    the cookie of the current domain. Once that is done the page is reloaded to reflect the new session.
4.  If neither session is new we have run into a bit of a problem. Usually that shouldn't happen, but could
    theoretically in case of broken connections and other issues. In that case we use the session that has a user
    set (that has been used to login), and if both have a user set we use the primary session.

The primary domain used is determined using the `CONSENT_PRIMARY_SERVERNAME` configuration option,
which by default is set to `SERVER_NAME`.

Since it is needed for the AJAX requests this extension also sets the CORS headers (`Access-Control-*`) for the
given domains.

## Development and Testing

1.  Get the code: `git clone https://github.com/02JanDal/Flask-CrossDomain-Session.git`
2.  Do your changes
3.  Test the result: `tox -e py`
