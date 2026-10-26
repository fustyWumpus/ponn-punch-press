"""Named constants extracted from magic numbers scattered through the legacy VB.

ENCODER_COUNTS_PER_REV was hardcoded identically for both axes in
MainScreen.vb's Form Load (`XEncoder = 16384 : YEncoder = 16384`) -- it's the
Galil encoder resolution, not something that varies per machine, so it's a
single shared constant here rather than two separate profile fields.
"""

ENCODER_COUNTS_PER_REV = 16384
