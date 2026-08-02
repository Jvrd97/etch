M?=


f-git:
	git add .  \
	&& git commit -m "$(M)" \
	&& git push origin main

up:
	cd habit-tracker \
	&& make up

upgrade:
	cd habit-tracker/services/backend/alembic \
	&& uv run alembic -c habit-tracker/services/backend/alembic.ini upgrade head
	echo ls

migration:
	cd habit-tracker/services/backend/alembic \
	&& uv run alembic -c habit-tracker/services/backend/alembic.ini revision --autogenerate -m "$(M)" \
	&& uv run alembic -c habit-tracker/services/backend/alembic.ini upgrade head
