"""The CPU fit of a rigid shoe onto a wearer's body (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md``, spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.5).

Task 1 holds the version and the width-cap limits only; the pure numpy fit
(``fit_pair``) lands in Task 9.
"""

#: Bumped when the fit changes what it produces (part of the footwear fsig and
#: ``garment_fit.FIT_VERSION["footwear"]``).
FOOTWEAR_FIT_VERSION = 1
#: The largest width factor a fit may apply (spec § 5.5), also the default cap.
WIDTH_CAP = 1.10
#: The smallest per-fit width cap override.
WIDTH_CAP_MIN = 1.00
