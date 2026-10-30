"""
FILE:         app/auth/personas.py
WHAT IT DOES: Loads the 8 demo users of the fictional company from data/org/personas.yaml.
WHERE IT FITS: Phase 2 created it. Phase 3's seed script (scripts/seed_users.py) turns
              these personas into real login accounts; Phase 11 attacks the system as each.
USED BY:      scripts/generate_dataset.py, scripts/seed_users.py, tests.

Flow:  personas.yaml  ->  validated Persona objects  ->  {"u_intern": Persona, ...}
"""

from pathlib import Path

import yaml
from pydantic import BaseModel

from app.auth.schemas import AuthenticatedUser
from app.core.config import DATA_DIR

PERSONAS_PATH = DATA_DIR / "org" / "personas.yaml"


# =============================================================================
# 1. SHAPE OF A PERSONA
# =============================================================================
# A persona has exactly the fields of a logged-in user (user_id, email, name, title,
# role, clearance, departments), so it can be passed straight to can_read() and is
# exactly what the seed script needs to create the account.
class Persona(AuthenticatedUser):
    pass


# The YAML file's top level: {"personas": [...]}
class _PersonaFile(BaseModel):
    personas: list[Persona]


# =============================================================================
# 2. LOAD - read the YAML, validate every field, index by user_id
# =============================================================================
def load_personas(path: Path = PERSONAS_PATH) -> dict[str, Persona]:
    # model_validate raises a clear error if a clearance or department is invalid.
    data = _PersonaFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return {p.user_id: p for p in data.personas}
