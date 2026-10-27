"""The active ontology: the profile file named by config.PROFILE_PATH, loaded and validated at import.

The ontology used to be Python code in this module (v0.1). It is now `profiles/oil_wells.json`, read through the
generic loader in profile.py, so another profile runs the same code (design §4.4, D-29).
"""
from __future__ import annotations

from .config import PROFILE_PATH
from .profile import fraction_size, load_profile, number, same_value, squash

PROFILE = load_profile(PROFILE_PATH)

__all__ = ["PROFILE", "fraction_size", "number", "same_value", "squash"]
