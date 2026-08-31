#!/usr/bin/env bash
# [review:need-review] PHASE-03/120
# summary: post-`up` proof that the running containers are this commit's build — four checks (no dev mount shadows the app dir, image label == HEAD, container content == image content, and the backend image actually carries its alembic revisions), any failure exits non-zero
#
# Why this exists
# ---------------
# `make deploy` reported success three times in a row while the frontend served a
# month-old interface. Nothing lied on purpose: `git pull` succeeded, `up --build`
# succeeded, `alembic upgrade` succeeded. Every step told the truth about itself,
# and no step asked the only question that mattered — *is the code now running the
# code I just pulled?* This script asks it, and exits non-zero when the answer is
# no. It never prints a warning and continues: a deploy that cannot be proven is a
# failed deploy, because a warning in a green build log is a warning nobody reads.
#
# What it checks, per service, in the order a failure is cheapest to understand:
#
#   1. MOUNTS — no volume is mounted at /app or under it on the running container.
#      This is the structural cause of the incident: docker-compose.yml (the dev
#      file) mounts an anonymous volume at /app/.next; docker seeds such a volume
#      from the image exactly once, on first start, and then reuses it forever, so
#      it covers the fresh .next baked into every later image. The prod override
#      now drops those mounts — this check is what notices if they ever come back,
#      or if a container predating the fix is still attached to the old volume.
#
#   2. REVISION — the image carries label org.opencontainers.image.revision equal
#      to `git rev-parse HEAD` on the host. The label is set by build.labels in
#      deploy/docker-compose.prod.yml, so no Dockerfile changed. This catches the
#      "forgot to rebuild" and "built somewhere else / from another branch" cases.
#
#   3. CONTENT — the artefact inside the running container is byte-identical to the
#      artefact inside its own image, compared by running a throwaway container off
#      that image with no volumes attached. This is the check that would have caught
#      the incident on day one: the image's .next/BUILD_ID was current, the
#      container's was a month old, and every other signal said the deploy was fine.
#
# Why revision label + content, and not a git SHA baked into the app
# ------------------------------------------------------------------
# Baking `git rev-parse HEAD` into the image as a build-arg is the obvious move and
# it is not enough on its own: an ENV/build-arg lives in the image config, which the
# volume cannot shadow. The container would happily report the correct new SHA while
# serving the old .next out of the volume underneath — the check would pass on
# exactly the failure it was written for. Anything that proves freshness has to be
# read from *inside the shadowable path*. Hence the split: the label answers "was
# this image built from this commit", the content diff answers "is the container
# actually running that image", and only the two together answer the real question.
# The label route also needs no Dockerfile edit, so backend, worker and frontend are
# covered by the same mechanism.
#
# Usage (normally via `make verify`, which `make up` runs for you):
#   COMPOSE="docker compose --profile web -f docker-compose.yml -f ../deploy/docker-compose.prod.yml" \
#   GIT_SHA=$(git rev-parse HEAD) bash deploy/verify-deploy.sh
set -uo pipefail

COMPOSE=${COMPOSE:?COMPOSE must hold the full compose command (see make verify)}
GIT_SHA=${GIT_SHA:-}

REVISION_LABEL=org.opencontainers.image.revision
failed=0

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
green(){ printf '\033[32m%s\033[0m\n' "$*"; }

fail() {
	red "FAIL  $*"
	failed=1
}

if [ -z "$GIT_SHA" ]; then
	red "verify-deploy: GIT_SHA is empty — nothing to compare against."
	red "               Run through 'make verify' from habit-tracker/, or export it yourself."
	exit 1
fi

# A dirty tree does not fail the run: the images were built from that same tree and
# the content check still compares container against image. But the revision label
# then names a commit whose code is not exactly what shipped, so say so out loud.
if [ -n "$(git -C "$(dirname "$0")/.." status --porcelain 2>/dev/null)" ]; then
	echo "note: working tree is dirty — the images contain uncommitted changes,"
	echo "      so label $REVISION_LABEL=$GIT_SHA describes the commit, not the build."
fi

echo "verify-deploy: expecting every service to run the build of $GIT_SHA"

# Fingerprint of the deployed artefact, per service. The command runs twice with
# identical text — once inside the running container, once inside a throwaway
# container started from that container's own image with no volumes attached.
# Any difference means something is mounted over the artefact, or the container
# outlived the image it is supposed to be running.
fingerprint_cmd() {
	case "$1" in
		frontend)
			# Next.js regenerates .next/BUILD_ID on every build, and it lives inside the
			# exact directory the anonymous volume used to cover. This is the value that
			# was fresh in the image and stale in the container during the incident.
			echo 'cat /app/.next/BUILD_ID'
			;;
		*)
			# Backend and worker share one image and have no equivalent single marker,
			# so hash the source that was copied in. Catches a bind mount of the host
			# checkout over /app just as well as a stale container.
			echo "find /app -type f -name '*.py' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1"
			;;
	esac
}

check_service() {
	svc=$1
	echo
	echo "── $svc"

	cid=$($COMPOSE ps -q "$svc" 2>/dev/null | awk 'NR==1')
	if [ -z "$cid" ]; then
		fail "$svc: no running container. 'up' either did not start it or it crashed —"
		red  "      check '$COMPOSE logs $svc'."
		return
	fi

	# 1. mounts ---------------------------------------------------------------
	shadows=$(docker inspect -f '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}' "$cid" \
		| grep -E '^/app(/|$)' || true)
	if [ -n "$shadows" ]; then
		fail "$svc: a volume is mounted over the application directory:"
		printf '%s\n' "$shadows" | sed 's/^/        /'
		red  "      These are development mounts from docker-compose.yml. In production they"
		red  "      hide the image's code — an anonymous volume at /app/.next is seeded once"
		red  "      and never again, so the container keeps serving the build it first saw."
		red  "      Fix: deploy/docker-compose.prod.yml must drop them (it does now), and the"
		red  "      already-created volume has to be destroyed once: '$COMPOSE down -v'."
		return
	fi
	green "  ok    nothing mounted over /app"

	# 2. revision label -------------------------------------------------------
	img=$(docker inspect -f '{{.Image}}' "$cid")
	label=$(docker image inspect -f "{{index .Config.Labels \"$REVISION_LABEL\"}}" "$img" 2>/dev/null)
	if [ "$label" != "$GIT_SHA" ]; then
		fail "$svc: image was not built from the deployed commit."
		red  "      $REVISION_LABEL = ${label:-<absent>}"
		red  "      git rev-parse HEAD       = $GIT_SHA"
		if [ -z "$label" ] || [ "$label" = "unset" ]; then
			red  "      An absent or 'unset' label means the image was built without GIT_SHA in the"
			red  "      environment — i.e. by a bare 'docker compose build', not by 'make up'."
		else
			red  "      The container is running an older build. Rebuild: 'make up'."
		fi
		return
	fi
	green "  ok    image built from $GIT_SHA"

	# 3. container content vs image content -----------------------------------
	cmd=$(fingerprint_cmd "$svc")
	in_container=$($COMPOSE exec -T "$svc" sh -c "$cmd" 2>/dev/null | tr -d '\r\n')
	in_image=$(docker run --rm --entrypoint sh "$img" -c "$cmd" 2>/dev/null | tr -d '\r\n')

	if [ -z "$in_image" ]; then
		fail "$svc: could not fingerprint the image ($cmd produced nothing)."
		return
	fi
	if [ -z "$in_container" ]; then
		fail "$svc: could not fingerprint the running container ($cmd produced nothing)."
		return
	fi
	if [ "$in_container" != "$in_image" ]; then
		fail "$svc: the container is NOT serving the contents of its own image."
		red  "      in image     = $in_image"
		red  "      in container = $in_container"
		red  "      This is the failure that made three deploys report success while the"
		red  "      interface stayed a month old. Something covers the built artefact at"
		red  "      runtime, or the container predates the image. Fix: '$COMPOSE down -v'"
		red  "      to destroy the stale volumes, then 'make up'."
		return
	fi
	green "  ok    container content matches image ($in_image)"

	# 4. migrations ------------------------------------------------------------
	# Только бэкенд: ревизии живут в его образе, и именно их отсутствие
	# остановило выкат 31.08 — `.dockerignore` исключал `alembic/versions/*.py`,
	# а прод до того монтировал исходники поверх образа и читал ревизии с хоста.
	# Проверяется образ, а не контейнер: контейнер уже сверен с образом выше.
	if [ "$svc" = "backend" ]; then
		revisions=$(docker run --rm --entrypoint sh "$img" -c \
			'ls alembic/versions/*.py 2>/dev/null | wc -l' | tr -d '\r\n ')
		if [ -z "$revisions" ] || [ "$revisions" -lt 2 ]; then
			fail "$svc: в образе нет миграций (найдено файлов: ${revisions:-0})."
			red  "      alembic внутри контейнера не найдёт ревизию, на которой стоит"
			red  "      база, и 'alembic upgrade head' остановит выкат. Проверьте"
			red  "      services/backend/.dockerignore: строка alembic/versions/*.py"
			red  "      выбрасывает ревизии из образа."
			return
		fi
		green "  ok    миграции в образе ($revisions ревизий)"
	fi
}

# The frontend sits behind the `web` profile; verify it only when the caller's
# COMPOSE enables that profile, otherwise there is legitimately no container.
services="backend worker"
case "$COMPOSE" in
	*"--profile web"*) services="$services frontend" ;;
esac

for s in $services; do
	check_service "$s"
done

echo
if [ "$failed" -ne 0 ]; then
	red "verify-deploy: FAILED — what is running is not the build of $GIT_SHA."
	red "               Treat this deploy as not done. Do not announce it."
	exit 1
fi
green "verify-deploy: OK — $(echo "$services" | tr ' ' ',' | sed 's/,/, /g') are running the build of $GIT_SHA."
