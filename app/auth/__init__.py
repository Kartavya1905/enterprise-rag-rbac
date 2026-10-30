"""
PACKAGE: app.auth - identity: who is asking, and what is their clearance.  (Phase 3)

    schemas.py       AuthenticatedUser (the logged-in user), TokenResponse, Role
    models.py        database tables: users, user_departments
    passwords.py     bcrypt hashing + verification
    tokens.py        create / verify JWT access tokens
    service.py       login check, user lookups, create/update users
    dependencies.py  get_current_user() - the gatekeeper for protected routes
    personas.py      loads the 8 demo users from data/org/personas.yaml

Request flow:
    POST /auth/login -> service.authenticate -> tokens.create_access_token -> JWT
    any protected route -> dependencies.get_current_user -> tokens.decode_access_token
                        -> reload user from DB -> AuthenticatedUser
"""
