M?=


f-git:
	git add .  \
	&& git commit -m "$(M)" \
	&& git push origin main

up:
	cd habit-tracker \
	&& make up

## local run without docker: backend + frontend on the host.
## Anything dev* is forwarded to habit-tracker/Makefile: dev, dev-back,
## dev-front, dev-deps, dev-createdb, dev-migrate, dev-stop.
dev dev-back dev-front dev-deps dev-createdb dev-migrate dev-stop dev-db dev-docker:
	cd habit-tracker \
	&& make $@

upgrade:
	cd habit-tracker/services/backend/alembic \
	&& uv run alembic -c habit-tracker/services/backend/alembic.ini upgrade head
	echo ls

migration:
	cd habit-tracker/services/backend/alembic \
	&& uv run alembic -c habit-tracker/services/backend/alembic.ini revision --autogenerate -m "$(M)" \
	&& uv run alembic -c habit-tracker/services/backend/alembic.ini upgrade head
