"""Synthetic RAG knowledge base for recall/precision measurement.

Mirrors the method in firstmate/data/dejaq-knowledge-base-review/report.md
section 3.1: each document carries one invented, unambiguous fact (so
retrieval can be graded objectively) padded with filler drawn from a pool
that is DISJOINT per document, so boilerplate can't create false similarity
between documents. One document (onboarding handbook) is deliberately made
~80% of the total chunk count to reproduce the "large document crowds out
small ones" failure the report measured.

Deterministic (fixed seed) so before/after runs are comparable.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

_RNG_SEED = 20260822

# Five disjoint filler-sentence pools. Each is used by exactly one document,
# and shares no subject matter with any other pool or with any planted fact,
# so embedding similarity between documents comes only from generic
# office-English structure, never from topical overlap.
_FILLER_POOLS: dict[str, list[str]] = {
    "catering": [
        "The cafeteria rotates its lunch menu every {n} weeks.",
        "Vending machines on floor {n} accept contactless payment only.",
        "Catering requests for team events need {n} business days notice.",
        "The coffee bar restocks oat milk every {n} days.",
        "Snack baskets are refilled on {n} designated weekdays.",
        "The kitchen committee meets every {n} weeks to review menu feedback.",
        "Compostable cups replaced plastic ones in the break room {n} months ago.",
        "The salad bar closes {n} minutes earlier on Fridays.",
        "Catering vendors rotate through a list of {n} approved suppliers.",
        "The espresso machine on floor {n} needs a service ticket for repairs.",
    ],
    "facilities": [
        "HVAC filters are replaced across the building every {n} months.",
        "Conference room {n} has a standing desk and a whiteboard wall.",
        "The facilities team inspects fire extinguishers {n} times a year.",
        "Building thermostats are centrally managed on floor {n}.",
        "The loading dock accepts deliveries until {n} PM on weekdays.",
        "Elevator maintenance is scheduled for the {n}th of each month.",
        "Floor {n} restrooms were renovated last quarter.",
        "The facilities helpdesk responds to tickets within {n} hours.",
        "Emergency lighting is tested on floor {n} every quarter.",
        "The building's recycling bins are collected {n} times per week.",
    ],
    "it_hardware": [
        "Printer toner cartridges are stocked in the supply closet on floor {n}.",
        "The IT helpdesk replaces laptop batteries after {n} years of service.",
        "Monitor mounts are available on request from floor {n} IT.",
        "The printer on floor {n} supports duplex printing by default.",
        "Loaner laptops are checked out for a maximum of {n} days.",
        "Docking stations are inventoried every {n} months.",
        "The IT asset tag scanner covers floor {n} equipment.",
        "Webcam covers are distributed to new hires in batches of {n}.",
        "Wireless keyboards are replaced after {n} reported failures.",
        "The print queue on floor {n} is cleared automatically overnight.",
    ],
    "transportation": [
        "Parking permits are renewed every {n} months at the front desk.",
        "The shuttle to the annex runs every {n} minutes during peak hours.",
        "Bike racks near entrance {n} were expanded last year.",
        "Carpool spots are reserved for groups of {n} or more.",
        "The parking garage on level {n} is reserved for visitors.",
        "Electric vehicle chargers are available at {n} stations in the garage.",
        "Shuttle passes expire after {n} months of inactivity.",
        "The bike-share kiosk near entrance {n} accepts the building badge.",
        "Overflow parking opens on lot {n} during large events.",
        "The commuter benefits program covers up to {n} transit trips a month.",
    ],
    "onboarding_misc": [
        "New hires receive a welcome kit within {n} days of their start date.",
        "The employee handbook is reviewed and reissued every {n} years.",
        "Payroll setup forms are due within {n} business days of hire.",
        "Benefits enrollment windows close {n} days after the start date.",
        "New hire orientation sessions run for {n} consecutive mornings.",
        "IT provisioning tickets are opened {n} days before a new hire's start date.",
        "The mentorship program pairs new hires within their first {n} weeks.",
        "Direct deposit changes take effect after {n} pay cycles.",
        "Org chart updates are published every {n} weeks.",
        "The new-hire survey is sent out {n} days after the start date.",
        "Manager check-ins are scheduled every {n} days during the first quarter.",
        "The equipment request form has a {n}-day fulfillment target.",
        "Building access badges are activated within {n} hours of approval.",
        "The company intranet lists {n} internal mailing lists for new teams.",
        "Expense report training is offered {n} times per quarter.",
    ],
}


@dataclass(frozen=True)
class Document:
    key: str
    title: str
    fact: str
    text: str


def _filler_block(pool_key: str, rng: random.Random, target_chars: int) -> str:
    sentences = _FILLER_POOLS[pool_key]
    out: list[str] = []
    total = 0
    while total < target_chars:
        template = sentences[rng.randrange(len(sentences))]
        sentence = template.format(n=rng.randint(2, 30))
        out.append(sentence)
        total += len(sentence) + 1
    return " ".join(out)


def build_corpus() -> list[Document]:
    """Five documents, one planted fact each, sizes shaped so the onboarding
    handbook alone is ~80% of the total chunk count (matches the report)."""
    rng = random.Random(_RNG_SEED)

    docs = [
        Document(
            key="vacation_policy",
            title="Aurora Vacation Policy",
            fact=(
                "Full-time employees at the Marbella office receive 27 paid "
                "vacation days per year under the Aurora Vacation Policy."
            ),
            text="",
        ),
        Document(
            key="product_roadmap",
            title="Falcon Module Roadmap",
            fact=(
                "The Falcon module reaches general availability in Q3, "
                "launching first in the Nordics region with quantum-safe "
                "encryption enabled by default."
            ),
            text="",
        ),
        Document(
            key="badge_procedures",
            title="Building 7 Access Procedures",
            fact="Building 7 badge access codes rotate automatically every 90 days.",
            text="",
        ),
        Document(
            key="travel_policy",
            title="Corporate Travel Policy",
            fact="The hotel reimbursement cap for tier-1 cities is $340 per night.",
            text="",
        ),
        Document(
            key="onboarding_handbook",
            title="New Hire Onboarding Handbook",
            fact=(
                "New hires must complete Helios Security Training within 14 "
                "days of their start date."
            ),
            text="",
        ),
    ]

    sizes = {
        "vacation_policy": 300,
        "product_roadmap": 700_000,
        "badge_procedures": 45_000,
        "travel_policy": 6_000,
        "onboarding_handbook": 3_300_000,
    }
    pools = {
        "vacation_policy": "catering",
        "product_roadmap": "facilities",
        "badge_procedures": "it_hardware",
        "travel_policy": "transportation",
        "onboarding_handbook": "onboarding_misc",
    }

    out: list[Document] = []
    for doc in docs:
        target = sizes[doc.key]
        pool = pools[doc.key]
        before = _filler_block(pool, rng, target // 2)
        after = _filler_block(pool, rng, target // 2)
        # Plant the fact roughly in the middle so it isn't a trivial
        # first-chunk hit, mirroring a fact buried inside a real document.
        text = f"{before}\n\n{doc.fact}\n\n{after}"
        out.append(Document(key=doc.key, title=doc.title, fact=doc.fact, text=text))
    return out


@dataclass(frozen=True)
class Question:
    doc_key: str
    kind: str  # "paraphrase" | "topical" | "vague"
    text: str


QUESTIONS: list[Question] = [
    # vacation_policy
    Question("vacation_policy", "paraphrase",
              "How many paid vacation days do employees get under the Aurora policy at the Marbella office?"),
    Question("vacation_policy", "topical",
              "What's our annual leave allowance at the Marbella location?"),
    Question("vacation_policy", "vague",
              "How much vacation do I get?"),
    # product_roadmap
    Question("product_roadmap", "paraphrase",
              "When does the Falcon module become generally available, and where does it launch first?"),
    Question("product_roadmap", "topical",
              "Tell me about the product roadmap for Falcon."),
    Question("product_roadmap", "vague",
              "What's the encryption story for the new module?"),
    # badge_procedures
    Question("badge_procedures", "paraphrase",
              "How often do the badge access codes for Building 7 rotate?"),
    Question("badge_procedures", "topical",
              "What's the security procedure for entering Building 7?"),
    Question("badge_procedures", "vague",
              "How does badge access work there?"),
    # travel_policy
    Question("travel_policy", "paraphrase",
              "What is the maximum hotel rate I can expense in a tier-1 city?"),
    Question("travel_policy", "topical",
              "What's our corporate travel reimbursement policy?"),
    Question("travel_policy", "vague",
              "How much can I spend on a hotel?"),
    # onboarding_handbook
    Question("onboarding_handbook", "paraphrase",
              "How many days after starting do new hires have to finish Helios Security Training?"),
    Question("onboarding_handbook", "topical",
              "What training do new employees have to complete when they join?"),
    Question("onboarding_handbook", "vague",
              "What do I need to finish in my first couple weeks?"),
]

DISTRACTOR_QUESTIONS: list[str] = [
    "What's the weather like in Marbella this time of year?",
    "Can you recommend a good book on distributed systems?",
    "What's the capital of Portugal?",
    "How do I convert a CSV file to JSON?",
    "What's a good icebreaker question for a team offsite?",
]
