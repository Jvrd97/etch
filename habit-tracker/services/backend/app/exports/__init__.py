# [review:need-review] PHASE-03/96
# summary: exports package — rendering stored days back into the file formats they came from
"""
Renderers that turn stored rows back into files.

The database became the only copy of a day in `#88`. `app.exports` is the half
of the reversal cost ADR-0014 priced at one to two weeks: a stored day that
cannot be written back out is a day that can only be read by this application,
and the rollback to the file mode it replaced would then cost everything
accumulated since the switch.
"""
