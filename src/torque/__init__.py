"""Torque — revenue-leakage recovery agent.

Milestone 1 delivers the core data model only: enums, multi-tenancy scoping,
identity/consent, the event log, the RevenueLeakCase spine with typed leg
contexts and its state machine, and the CaseEvent append-only history with its
atomic-write primitive. No ingestion, diagnosis, playbook, execution, scoring,
or reporting logic exists yet — those are Modules 2-13.

Source of truth: Torque_Blueprint_v7_FullSystem.md.
"""

__version__ = "0.1.0"
