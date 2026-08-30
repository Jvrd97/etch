# [review:need-review] PHASE-03/134
# summary: the roles package — the seeded directory (`catalog`) and the rule resolver (`matcher`), both free of the database so the taxonomy can be tested without one
"""
Roles as data: the directory that is seeded and the markup that is resolved.

Nothing in here touches a session. `catalog` is the four rows a fresh database
starts from, `matcher` is the pure answer to «какая роль у этого образца» —
which is what lets the conflict of two rules be tested with two literals instead
of a fixture.
"""
