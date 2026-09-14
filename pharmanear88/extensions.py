"""
Shared Flask extension instances.

Kept in their own module (instead of inside app.py) so that models.py can
import `db` without creating a circular import with app.py.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
