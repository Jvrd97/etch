# [review:need-review] PHASE-03/86
# summary: the day package — the canon of a day lives here as data (`rules`), not as constants spread over the services
"""
The day as a subject of its own.

`rules` holds everything that can be decided without a database: which rule row
was in force on a date, what kind of day a date is under that rule, and the two
seed rows a fresh installation starts from. Persistence lives in
`app.crud.day`, the wire shapes in `app.schemas.day`.
"""
