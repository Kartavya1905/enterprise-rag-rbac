"""
FILE:         scripts/dataset/employees.py
WHAT IT DOES: Builds the fictional company's staff list (33 people): names, departments,
              titles, managers, salaries, performance ratings, fake tax IDs.
WHERE IT FITS: Phase 2 - STEP 1 of the dataset pipeline. The SAME roster feeds the
              employee directory, the payroll register and the salary checks, so the
              numbers agree across documents - just like real company data.
USED BY:      scripts/dataset/content.py, tests/unit/test_dataset.py.

Deterministic: a fixed random seed (2026) gives the same people and numbers every run.
"""

import random
from dataclasses import dataclass

from app.core.access import Department

SEED = 2026

# =============================================================================
# 1. COMPANY CONSTANTS
# =============================================================================
# Annual base salary bands (USD). Executives are set by the board, not by band.
# Also printed in the "Salary Bands 2026" document.
SALARY_BANDS: dict[str, tuple[int, int]] = {
    "L1": (62_000, 80_000),
    "L2": (80_000, 105_000),
    "L3": (105_000, 140_000),
    "L4": (135_000, 175_000),
    "L5": (170_000, 220_000),
}

OFFICES = ["Austin", "Toronto", "Remote"]


# =============================================================================
# 2. ONE EMPLOYEE RECORD
# =============================================================================
@dataclass(frozen=True)
class Employee:
    employee_id: str  # e.g. "EMP-1007"
    name: str
    department: Department
    title: str
    level: str  # L1-L5, or "EXEC"
    office: str
    manager: str | None  # None only for the CEO
    base_salary: int | None  # None for executives (see executive compensation doc)
    performance_rating: int | None  # 1-5; None for executives
    tax_id: str  # clearly fake: "FAKE-TX-12345"
    bank_last4: str

    # Derived from the name: "Lena Okafor" -> lena.okafor@orbitra.example
    @property
    def email(self) -> str:
        first, last = self.name.lower().split(" ", 1)
        return f"{first}.{last.replace(' ', '')}@orbitra.example"

    @property
    def is_executive(self) -> bool:
        return self.level == "EXEC"


# =============================================================================
# 3. NAMED PEOPLE - personas and characters other documents mention
# =============================================================================
# (name, department, title, level, office, manager). Personas and named characters that
# other documents refer to; everyone else is generated below.
_EXE, _ENG, _SAL, _HR, _FIN = (Department.EXECUTIVE, Department.ENGINEERING,
                               Department.SALES, Department.HR, Department.FINANCE)
_KEY_PEOPLE = [
    ("Helena Voss", _EXE, "Chief Executive Officer", "EXEC", "Austin", None),
    ("Thomas Reed", _EXE, "Chief Financial Officer", "EXEC", "Austin", "Helena Voss"),
    ("Kenji Watanabe", _EXE, "Chief Technology Officer", "EXEC", "Toronto", "Helena Voss"),
    ("Amara Nwosu", _EXE, "Chief People Officer", "EXEC", "Austin", "Helena Voss"),
    ("Priya Raman", _ENG, "Engineering Manager", "L4", "Toronto", "Kenji Watanabe"),
    ("Samuel Osei", _ENG, "Engineering Manager, Platform", "L4", "Remote", "Kenji Watanabe"),
    ("Lena Okafor", _ENG, "Software Engineer II", "L2", "Toronto", "Priya Raman"),
    ("Aarav Mehta", _ENG, "Software Engineering Intern", "L1", "Toronto", "Priya Raman"),
    ("Grace Lindqvist", _SAL, "VP of Sales", "L5", "Austin", "Helena Voss"),
    ("Rafael Castillo", _SAL, "Sales Team Lead", "L4", "Austin", "Grace Lindqvist"),
    ("Marco Bellini", _SAL, "Account Executive", "L2", "Austin", "Rafael Castillo"),
    ("Daniel Kim", _HR, "HR Business Partner", "L3", "Austin", "Amara Nwosu"),
    ("Olivia Brandt", _FIN, "Financial Controller", "L5", "Austin", "Thomas Reed"),
    ("Sofia Alvarez", _FIN, "Senior Financial Analyst", "L3", "Austin", "Olivia Brandt"),
]

# =============================================================================
# 4. GENERATED PEOPLE - random filler staff per department
# =============================================================================
# department -> (how many, possible managers, possible (level, title) pairs)
_GENERATED = {
    Department.ENGINEERING: (
        10,
        ["Priya Raman", "Samuel Osei"],
        [("L1", "Software Engineer I"), ("L2", "Software Engineer II"),
         ("L3", "Senior Software Engineer"), ("L3", "Site Reliability Engineer")],
    ),
    Department.SALES: (
        5,
        ["Rafael Castillo"],
        [("L1", "Sales Development Representative"), ("L2", "Account Executive"),
         ("L3", "Senior Account Executive")],
    ),
    Department.HR: (2, ["Daniel Kim"], [("L1", "HR Coordinator"), ("L2", "Technical Recruiter")]),
    Department.FINANCE: (
        2, ["Olivia Brandt"], [("L1", "Accounts Payable Specialist"), ("L2", "Financial Analyst")]
    ),
}

# Name pools for random filler staff (first + last combined at random).
_FIRST = ["Noah", "Mei", "Tobias", "Zara", "Ivan", "Chloe", "Omar", "Hana", "Lucas", "Nia",
          "Felix", "Ana", "Ravi", "Elena", "Jonah", "Yuki", "Mateo", "Ingrid", "Kofi", "Leah",
          "Arjun", "Sara"]
_LAST = ["Fischer", "Tanaka", "Moreau", "Haddad", "Novak", "Laurent", "Mensah", "Park",
         "Ferreira", "Iyer", "Kowalski", "Duarte", "Larsen", "Quinn", "Sato", "Abara",
         "Lindgren", "Cruz", "Nakamura", "Petrov"]


# =============================================================================
# 5. BUILD THE ROSTER
# =============================================================================
def build_roster(seed: int = SEED) -> list[Employee]:
    rng = random.Random(seed)  # seeded -> same "random" choices every run

    # --- 5a. Start with the named people, then add random filler staff ---
    people = list(_KEY_PEOPLE)
    used = {p[0] for p in people}
    for dept, (count, managers, roles) in _GENERATED.items():
        for _ in range(count):
            # Keep drawing until we get a name nobody has yet.
            while (name := f"{rng.choice(_FIRST)} {rng.choice(_LAST)}") in used:
                pass
            used.add(name)
            level, title = rng.choice(roles)
            people.append((name, dept, title, level, rng.choice(OFFICES), rng.choice(managers)))

    # --- 5b. Give everyone an ID, a salary inside their band, a rating, fake IDs ---
    roster = []
    for i, (name, dept, title, level, office, manager) in enumerate(people, start=1):
        if level == "EXEC":
            salary = rating = None  # executive pay lives only in the restricted exec doc
        else:
            lo, hi = SALARY_BANDS[level]
            salary = rng.randrange(lo, hi + 1, 500)  # within band, multiple of $500
            # Ratings are mostly 3-4, rarely 1 or 5 (like a real distribution).
            rating = rng.choices([1, 2, 3, 4, 5], weights=[2, 8, 45, 35, 10])[0]
        roster.append(
            Employee(
                employee_id=f"EMP-{1000 + i}",
                name=name,
                department=dept,
                title=title,
                level=level,
                office=office,
                manager=manager,
                base_salary=salary,
                performance_rating=rating,
                tax_id=f"FAKE-TX-{rng.randint(10000, 99999)}",
                bank_last4=f"{rng.randint(0, 9999):04d}",
            )
        )
    return roster


# =============================================================================
# 6. PAYROLL HELPER
# =============================================================================
def q3_commission(employee: Employee, rng: random.Random) -> int:
    """Q3 2026 commission paid; only sales staff (excluding the VP) earn it."""
    if employee.department is Department.SALES and employee.level != "L5":
        return rng.randrange(2_000, 9_001, 50)
    return 0
