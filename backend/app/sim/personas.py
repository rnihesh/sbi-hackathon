"""Synthetic Indian banking personas.

Zero real customer data is ever used anywhere in Sarathi's demo: every
persona, name, employer, and transaction is generated here from a seeded
`Faker("en_IN")` + `random.Random` pipeline. Same seed -> byte-identical
cohort, every time, on every machine.

Do not use the builtin ``hash()`` anywhere in this package to derive seeds:
CPython randomizes ``str`` hashing per-process (``PYTHONHASHSEED``), which
would silently break determinism across runs. Use :func:`derived_seed`
instead, which is stable SHA-256-based.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from enum import StrEnum
from typing import Any, Final

from faker import Faker
from pydantic import BaseModel, ConfigDict, Field

_PERSONA_NAMESPACE: Final[uuid.UUID] = uuid.uuid5(uuid.NAMESPACE_DNS, "sarathi.sim.persona")


def derived_seed(*parts: str | int) -> int:
    """Deterministic 32-bit int seed derived from arbitrary parts.

    Safe substitute for ``hash()`` -- SHA-256 based, stable across
    processes and Python versions (unlike str hash randomization).
    """
    joined = ":".join(str(p) for p in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % (2**32)


class Archetype(StrEnum):
    """Indian retail-banking customer archetypes used by the sim engine."""

    YOUNG_SALARIED_TECHIE = "young_salaried_techie"
    GIG_WORKER = "gig_worker"
    SMALL_BUSINESS_OWNER = "small_business_owner"
    STUDENT = "student"
    HOMEMAKER = "homemaker"
    RETIREE = "retiree"


# ---------------------------------------------------------------------------
# Reference pools (public: reused by app.sim.events for life-event mutations)
# ---------------------------------------------------------------------------

TECH_CITIES: Final[list[str]] = ["Bengaluru", "Hyderabad", "Pune"]
METRO_CITIES: Final[list[str]] = [
    "Mumbai",
    "Delhi",
    "Chennai",
    "Kolkata",
    "Ahmedabad",
    "Jaipur",
    "Lucknow",
    "Surat",
    "Nagpur",
    "Bengaluru",
    "Hyderabad",
    "Pune",
    "Indore",
    "Bhopal",
    "Chandigarh",
    "Kochi",
]
SMALL_TOWNS: Final[list[str]] = [
    "Nashik",
    "Coimbatore",
    "Vadodara",
    "Rajkot",
    "Varanasi",
    "Patna",
    "Ranchi",
    "Guwahati",
    "Mysuru",
    "Amritsar",
]

TECH_EMPLOYERS: Final[list[str]] = [
    "Infosys",
    "TCS",
    "Wipro",
    "Flipkart",
    "Swiggy",
    "Razorpay",
    "Amazon India",
    "Microsoft India",
    "Google India",
    "Freshworks",
    "Zoho Corporation",
    "Accenture",
    "Cognizant",
]
GIG_PLATFORMS: Final[list[str]] = [
    "Swiggy",
    "Zomato",
    "Uber",
    "Ola",
    "Rapido",
    "Urban Company",
    "Dunzo",
    "Porter",
]
SMALL_BIZ_TYPES: Final[list[str]] = [
    "Kirana Store",
    "Textile Trading Co",
    "Mobile Repair Shop",
    "Tiffin Service",
    "Hardware Store",
    "Family Salon",
    "Auto Parts Shop",
    "Stationery Mart",
]
RETIREE_FORMER_EMPLOYERS: Final[list[str]] = [
    "Indian Railways",
    "State Bank of India",
    "LIC of India",
    "BSNL",
    "Central Govt Pension Office",
    "Tata Steel",
    "ONGC",
    "Indian Army",
]
COLLEGES: Final[list[str]] = [
    "IIT Bombay",
    "Delhi University",
    "Osmania University",
    "Anna University",
    "Savitribai Phule Pune University",
    "BITS Pilani",
    "NIT Trichy",
    "Christ University",
]
UPI_HANDLES: Final[list[str]] = ["okhdfcbank", "oksbi", "okicici", "okaxis", "ybl", "paytm"]

PRODUCT_POOL: Final[dict[Archetype, list[str]]] = {
    Archetype.YOUNG_SALARIED_TECHIE: [
        "savings_account",
        "credit_card",
        "mutual_fund_sip",
        "term_insurance",
    ],
    Archetype.GIG_WORKER: ["savings_account", "personal_accident_cover"],
    Archetype.SMALL_BUSINESS_OWNER: ["current_account", "od_facility", "gst_linked_account"],
    Archetype.STUDENT: ["savings_account", "zero_balance_account"],
    Archetype.HOMEMAKER: ["savings_account", "recurring_deposit"],
    Archetype.RETIREE: [
        "savings_account",
        "fixed_deposit",
        "senior_citizen_scheme",
        "pension_account",
    ],
}

# Cohort archetype distribution (must sum to 1.0).
ARCHETYPE_WEIGHTS: Final[dict[Archetype, float]] = {
    Archetype.YOUNG_SALARIED_TECHIE: 0.30,
    Archetype.GIG_WORKER: 0.15,
    Archetype.SMALL_BUSINESS_OWNER: 0.15,
    Archetype.STUDENT: 0.15,
    Archetype.HOMEMAKER: 0.15,
    Archetype.RETIREE: 0.10,
}


class Persona(BaseModel):
    """A single synthetic retail-banking customer."""

    model_config = ConfigDict(validate_assignment=True)

    id: str
    name: str
    age: int = Field(ge=0, le=120)
    gender: str
    city: str
    occupation: str
    employer: str | None
    monthly_income_paise: int = Field(ge=0)
    archetype: Archetype
    digital_maturity: float = Field(ge=0.0, le=1.0)
    products_held: list[str]
    upi_active: bool
    upi_vpa: str | None
    is_renter: bool
    monthly_rent_paise: int = Field(default=0, ge=0)
    emi_paise: int = Field(default=0, ge=0)
    dependents: int = Field(default=0, ge=0)
    family: dict[str, Any]

    @property
    def customer_id(self) -> str:
        return self.id


def _rupees_to_paise(rupees: int) -> int:
    return rupees * 100


def _family_json(
    rng: random.Random, *, marital_status: str, num_children: int, fake: Faker
) -> dict[str, Any]:
    children = [{"relation": "child", "age": rng.randint(0, 17)} for _ in range(num_children)]
    spouse_name = fake.name() if marital_status == "married" else None
    return {
        "marital_status": marital_status,
        "dependents": num_children,
        "spouse_name": spouse_name,
        "children": children,
    }


def _upi_vpa(rng: random.Random, name: str) -> str:
    handle = name.split()[0].lower().replace(".", "")
    return f"{handle}{rng.randint(1, 9999)}@{rng.choice(UPI_HANDLES)}"


def _pick_products(rng: random.Random, archetype: Archetype) -> list[str]:
    pool = PRODUCT_POOL[archetype]
    held = [pool[0]]  # everyone gets the core product (savings/current account)
    for product in pool[1:]:
        if rng.random() < 0.5:
            held.append(product)
    return held


def _build_young_salaried_techie(rng: random.Random, fake: Faker, gender: str) -> dict[str, Any]:
    age = rng.randint(22, 32)
    married = age >= 26 and rng.random() < 0.35
    num_children = rng.randint(0, 2) if married and rng.random() < 0.4 else 0
    is_renter = rng.random() < 0.6
    return {
        "age": age,
        "city": rng.choice(TECH_CITIES),
        "occupation": rng.choice(
            [
                "Software Engineer",
                "Product Analyst",
                "Data Scientist",
                "DevOps Engineer",
                "UX Designer",
            ]
        ),
        "employer": rng.choice(TECH_EMPLOYERS),
        "monthly_income_paise": _rupees_to_paise(rng.randint(60_000, 250_000)),
        "digital_maturity": round(rng.uniform(0.75, 0.98), 2),
        "is_renter": is_renter,
        "monthly_rent_paise": _rupees_to_paise(rng.randint(9_000, 35_000)) if is_renter else 0,
        "emi_paise": _rupees_to_paise(rng.randint(3_000, 15_000)) if rng.random() < 0.25 else 0,
        "upi_active": rng.random() < 0.97,
        "dependents": num_children,
        "family": _family_json(
            rng,
            marital_status="married" if married else "single",
            num_children=num_children,
            fake=fake,
        ),
    }


def _build_gig_worker(rng: random.Random, fake: Faker, gender: str) -> dict[str, Any]:
    age = rng.randint(20, 40)
    married = rng.random() < 0.45
    num_children = rng.randint(0, 2) if married else 0
    is_renter = rng.random() < 0.4
    return {
        "age": age,
        "city": rng.choice(METRO_CITIES),
        "occupation": rng.choice(["Delivery Partner", "Cab Driver", "Home-Service Professional"]),
        "employer": rng.choice(GIG_PLATFORMS),
        "monthly_income_paise": _rupees_to_paise(rng.randint(12_000, 45_000)),
        "digital_maturity": round(rng.uniform(0.55, 0.85), 2),
        "is_renter": is_renter,
        "monthly_rent_paise": _rupees_to_paise(rng.randint(4_000, 12_000)) if is_renter else 0,
        "emi_paise": _rupees_to_paise(rng.randint(2_000, 8_000)) if rng.random() < 0.3 else 0,
        "upi_active": rng.random() < 0.95,
        "dependents": num_children,
        "family": _family_json(
            rng,
            marital_status="married" if married else "single",
            num_children=num_children,
            fake=fake,
        ),
    }


def _build_small_business_owner(rng: random.Random, fake: Faker, gender: str) -> dict[str, Any]:
    age = rng.randint(28, 55)
    married = rng.random() < 0.75
    num_children = rng.randint(0, 3) if married else 0
    is_renter = rng.random() < 0.3
    business = rng.choice(SMALL_BIZ_TYPES)
    return {
        "age": age,
        "city": rng.choice(METRO_CITIES + SMALL_TOWNS),
        "occupation": f"Proprietor, {business}",
        "employer": f"{fake.last_name()} {business}",
        "monthly_income_paise": _rupees_to_paise(rng.randint(40_000, 180_000)),
        "digital_maturity": round(rng.uniform(0.35, 0.7), 2),
        "is_renter": is_renter,
        "monthly_rent_paise": _rupees_to_paise(rng.randint(8_000, 30_000)) if is_renter else 0,
        "emi_paise": _rupees_to_paise(rng.randint(5_000, 25_000)) if rng.random() < 0.4 else 0,
        "upi_active": rng.random() < 0.6,
        "dependents": num_children,
        "family": _family_json(
            rng,
            marital_status="married" if married else "single",
            num_children=num_children,
            fake=fake,
        ),
    }


def _build_student(rng: random.Random, fake: Faker, gender: str) -> dict[str, Any]:
    age = rng.randint(18, 24)
    is_renter = rng.random() < 0.7  # hostel/PG
    return {
        "age": age,
        "city": rng.choice(METRO_CITIES + SMALL_TOWNS),
        "occupation": "Student",
        "employer": rng.choice(COLLEGES),
        "monthly_income_paise": _rupees_to_paise(rng.randint(3_000, 15_000)),
        "digital_maturity": round(rng.uniform(0.7, 0.95), 2),
        "is_renter": is_renter,
        "monthly_rent_paise": _rupees_to_paise(rng.randint(3_000, 9_000)) if is_renter else 0,
        "emi_paise": 0,
        "upi_active": rng.random() < 0.9,
        "dependents": 0,
        "family": _family_json(rng, marital_status="single", num_children=0, fake=fake),
    }


def _build_homemaker(rng: random.Random, fake: Faker, gender: str) -> dict[str, Any]:
    age = rng.randint(25, 55)
    num_children = rng.randint(0, 3)
    is_renter = rng.random() < 0.2
    return {
        "age": age,
        "city": rng.choice(METRO_CITIES + SMALL_TOWNS),
        "occupation": "Homemaker",
        "employer": None,
        "monthly_income_paise": _rupees_to_paise(rng.randint(10_000, 30_000)),
        "digital_maturity": round(rng.uniform(0.2, 0.55), 2),
        "is_renter": is_renter,
        "monthly_rent_paise": _rupees_to_paise(rng.randint(6_000, 15_000)) if is_renter else 0,
        "emi_paise": 0,
        "upi_active": rng.random() < 0.5,
        "dependents": num_children,
        "family": _family_json(rng, marital_status="married", num_children=num_children, fake=fake),
    }


def _build_retiree(rng: random.Random, fake: Faker, gender: str) -> dict[str, Any]:
    age = rng.randint(60, 78)
    widowed = rng.random() < 0.2
    is_renter = rng.random() < 0.05
    retired_role = rng.choice(["Officer", "Clerk", "Manager", "Engineer", "Teacher"])
    return {
        "age": age,
        "city": rng.choice(METRO_CITIES + SMALL_TOWNS),
        "occupation": f"Retired {retired_role}",
        "employer": rng.choice(RETIREE_FORMER_EMPLOYERS),
        "monthly_income_paise": _rupees_to_paise(rng.randint(15_000, 60_000)),
        "digital_maturity": round(rng.uniform(0.05, 0.35), 2),
        "is_renter": is_renter,
        "monthly_rent_paise": _rupees_to_paise(rng.randint(6_000, 15_000)) if is_renter else 0,
        "emi_paise": 0,
        "upi_active": rng.random() < 0.15,
        "dependents": 0,
        "family": _family_json(
            rng,
            marital_status="widowed" if widowed else "married",
            num_children=0,
            fake=fake,
        ),
    }


_BUILDERS: Final[dict[Archetype, Any]] = {
    Archetype.YOUNG_SALARIED_TECHIE: _build_young_salaried_techie,
    Archetype.GIG_WORKER: _build_gig_worker,
    Archetype.SMALL_BUSINESS_OWNER: _build_small_business_owner,
    Archetype.STUDENT: _build_student,
    Archetype.HOMEMAKER: _build_homemaker,
    Archetype.RETIREE: _build_retiree,
}


def _build_persona(
    index: int, archetype: Archetype, seed: int, rng: random.Random, fake: Faker
) -> Persona:
    gender = rng.choice(["male", "female"])
    name = fake.name_male() if gender == "male" else fake.name_female()
    fields = _BUILDERS[archetype](rng, fake, gender)
    upi_active = bool(fields["upi_active"])
    persona_id = str(uuid.uuid5(_PERSONA_NAMESPACE, f"persona:{seed}:{index}"))
    return Persona(
        id=persona_id,
        name=name,
        gender=gender,
        archetype=archetype,
        products_held=_pick_products(rng, archetype),
        upi_vpa=_upi_vpa(rng, name) if upi_active else None,
        **fields,
    )


def make_cohort(n: int, seed: int) -> list[Persona]:
    """Build a deterministic cohort of ``n`` personas for the given ``seed``.

    Same ``(n, seed)`` always yields byte-identical personas -- this is the
    root of determinism for the entire sim engine (generator.py and
    events.py both derive their own randomness from ``seed`` + ``persona.id``).
    """
    if n <= 0:
        return []
    rng = random.Random(derived_seed(seed, "cohort"))
    fake = Faker("en_IN")
    fake.seed_instance(derived_seed(seed, "cohort", "faker"))
    archetypes = rng.choices(
        list(ARCHETYPE_WEIGHTS.keys()), weights=list(ARCHETYPE_WEIGHTS.values()), k=n
    )
    return [_build_persona(i, archetype, seed, rng, fake) for i, archetype in enumerate(archetypes)]
