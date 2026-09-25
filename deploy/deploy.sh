#!/usr/bin/env bash
# Deploy an image to an environment, in order:
#   1. define the Cloud Run jobs with the new image (migrate and merge; prod also ingest-tbc, ingest-forever,
#      prune). Only prod's are scheduled (setup.sh scheduler); staging's merge runs by hand
#   2. run the migrate job and wait: migrations run once per deploy, before any new instance starts
#   3. deploy the Cloud Run service (its instances never migrate)
#   4. build the front end and deploy it to Firebase Hosting (prod: the live site; staging: the
#      `staging` preview channel, whose /api rewrites to the staging service)
#
#   deploy/deploy.sh prod|staging IMAGE
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
ENV_NAME="${1:?prod or staging}"
IMAGE="${2:?image, e.g. from deploy/build.sh}"
env_config "$ENV_NAME"

COMMON=(--image "$IMAGE" --region "$REGION" --service-account "$RUN_SA"
  --set-cloudsql-instances "$SQL_CONNECTION" --set-secrets "DATABASE_URL=$SECRET:latest")

job() { # job NAME ARGS...: the CLI with ARGS, as a Cloud Run job
  local name="$1"
  shift
  local args
  args="$(IFS=,; echo "$*")"
  gcloud run jobs deploy "$name" "${COMMON[@]}" --command altarmy-profit --args="$args" \
    --memory 2Gi --cpu 1 --max-retries 1 --task-timeout 30m --set-env-vars DB_POOL_SIZE=1,DB_MAX_OVERFLOW=0 \
    "${GCLOUD_FLAGS[@]}"
}

echo "== jobs ($ENV_NAME)"
job "$JOB_PREFIX-migrate" migrate
job "$JOB_PREFIX-merge" merge
if [ "$ENV_NAME" = prod ]; then
  job "$JOB_PREFIX-ingest-tbc" --game-version tbc ingest --only-if-new --cache /tmp/cache
  job "$JOB_PREFIX-ingest-forever" --game-version forever ingest --only-if-new --cache /tmp/cache
  job "$JOB_PREFIX-prune" prune
fi

echo "== migrate"
gcloud run jobs execute "$JOB_PREFIX-migrate" --region "$REGION" --wait "${GCLOUD_FLAGS[@]}"

echo "== service $SERVICE"
gcloud run deploy "$SERVICE" "${COMMON[@]}" \
  --allow-unauthenticated --min-instances 0 --max-instances "$MAX_INSTANCES" --concurrency 40 \
  --cpu 1 --memory 1Gi --cpu-boost --timeout 300 \
  --set-env-vars "ALTARMY_MODE=hosted,$(firebase_env),DB_POOL_SIZE=3,DB_MAX_OVERFLOW=2" \
  "${GCLOUD_FLAGS[@]}"

echo "== front end"
(cd frontend && npm run build)
FIREBASE=(npx --yes firebase-tools@14 --project "$PROJECT" --non-interactive)
if [ "$ENV_NAME" = prod ]; then
  "${FIREBASE[@]}" deploy --only hosting
else
  "${FIREBASE[@]}" --config firebase.staging.json hosting:channel:deploy staging --expires 30d
fi
