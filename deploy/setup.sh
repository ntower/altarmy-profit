#!/usr/bin/env bash
# One-time Google Cloud setup for the hosted app, one section at a time (each creates billable or
# visible resources, so run them deliberately):
#
#   deploy/setup.sh apis         enable the APIs
#   deploy/setup.sh registry     Artifact Registry repo, keeping the last 5 images
#   deploy/setup.sh accounts     service accounts and their roles
#   deploy/setup.sh sql          Cloud SQL instance (Postgres 16, db-f1-micro, 10 GB SSD)
#   deploy/setup.sh database ENV   a database, its user (random password) and the DATABASE_URL secret
#   deploy/setup.sh wif          Workload Identity Federation for GitHub Actions
#   deploy/setup.sh scheduler    Cloud Scheduler jobs (after a prod deploy made the jobs; existing ones are kept)
#
# Then: BUILDER=cloudbuild deploy/build.sh, deploy/deploy.sh prod|staging IMAGE (README, "Deploy").
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
G=("${GCLOUD_FLAGS[@]}")

apis() {
  gcloud services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com \
    artifactregistry.googleapis.com cloudscheduler.googleapis.com cloudbuild.googleapis.com \
    iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com "${G[@]}"
}

registry() {
  gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION" \
    --description "altarmy-profit images" "${G[@]}"
  gcloud artifacts repositories set-cleanup-policies "$REPO" --location "$REGION" \
    --policy deploy/ar-cleanup.json --no-dry-run "${G[@]}"
}

project_role() { # project_role MEMBER ROLE
  gcloud projects add-iam-policy-binding "$PROJECT" --member "$1" --role "$2" --condition None \
    "${G[@]}" >/dev/null
  echo "  $2 -> $1"
}

accounts() {
  gcloud iam service-accounts create altarmy-run --display-name "altarmy-profit service and jobs" "${G[@]}"
  gcloud iam service-accounts create altarmy-scheduler --display-name "altarmy-profit scheduler" "${G[@]}"
  gcloud iam service-accounts create altarmy-deploy --display-name "altarmy-profit CI deploys" "${G[@]}"

  # runtime: Cloud SQL, its secrets (granted per secret in `database`), deleting Firebase Auth users
  project_role "serviceAccount:$RUN_SA" roles/cloudsql.client
  project_role "serviceAccount:$RUN_SA" roles/firebaseauth.admin
  # scheduler: start Cloud Run jobs
  project_role "serviceAccount:$SCHEDULER_SA" roles/run.invoker
  # CI: deploy services and jobs as altarmy-run, push images, deploy Hosting; Cloud Build as itself
  for role in roles/run.admin roles/artifactregistry.writer roles/firebasehosting.admin \
    roles/serviceusage.serviceUsageConsumer roles/logging.logWriter roles/storage.objectViewer; do
    project_role "serviceAccount:$DEPLOY_SA" "$role"
  done
  gcloud iam service-accounts add-iam-policy-binding "$RUN_SA" --member "serviceAccount:$DEPLOY_SA" \
    --role roles/iam.serviceAccountUser "${G[@]}" >/dev/null
}

sql() {
  gcloud sql instances create "$SQL_INSTANCE" --database-version POSTGRES_16 --edition ENTERPRISE \
    --tier db-f1-micro --region "$REGION" --storage-type SSD --storage-size 10 --storage-auto-increase \
    --availability-type zonal --backup-start-time 08:00 --retained-backups-count 7 \
    --assign-ip "${G[@]}"
}

database() { # database prod|staging: its database, user and DATABASE_URL secret (password never printed)
  env_config "${1:?prod or staging}"
  gcloud sql databases create "$DB_NAME" --instance "$SQL_INSTANCE" "${G[@]}"
  local password
  password="$(openssl rand -hex 24)"
  gcloud sql users create "$DB_USER" --instance "$SQL_INSTANCE" --password "$password" "${G[@]}"
  printf 'postgresql+psycopg://%s:%s@/%s?host=/cloudsql/%s' "$DB_USER" "$password" "$DB_NAME" \
    "$SQL_CONNECTION" | gcloud secrets create "$SECRET" --data-file - --replication-policy automatic "${G[@]}"
  gcloud secrets add-iam-policy-binding "$SECRET" --member "serviceAccount:$RUN_SA" \
    --role roles/secretmanager.secretAccessor "${G[@]}" >/dev/null
}

wif() {
  gcloud iam workload-identity-pools create "$WIF_POOL" --location global \
    --display-name "GitHub Actions" "${G[@]}"
  gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" --location global \
    --workload-identity-pool "$WIF_POOL" --issuer-uri https://token.actions.githubusercontent.com \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition "assertion.repository == '$GITHUB_REPO'" "${G[@]}"
  gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --role roles/iam.workloadIdentityUser \
    --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$WIF_POOL/attribute.repository/$GITHUB_REPO" \
    "${G[@]}" >/dev/null
  echo "GitHub repo variables:"
  echo "  GCP_WIF_PROVIDER=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$WIF_POOL/providers/$WIF_PROVIDER"
  echo "  GCP_DEPLOY_SA=$DEPLOY_SA"
}

schedule() { # schedule NAME CRON: run the prod job NAME on CRON (UTC); skipped if it exists
  if gcloud scheduler jobs describe "$1" --location "$REGION" "${G[@]}" >/dev/null 2>&1; then
    echo "schedule $1 exists"
    return
  fi
  gcloud scheduler jobs create http "$1" --location "$REGION" --schedule "$2" --time-zone Etc/UTC \
    --uri "https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$1:run" \
    --http-method POST --oauth-service-account-email "$SCHEDULER_SA" \
    --oauth-token-scope https://www.googleapis.com/auth/cloud-platform "${G[@]}"
}

scheduler() {
  schedule altarmy-ingest-tbc "0 9 * * *"
  schedule altarmy-ingest-forever "15 9 * * *"
  schedule altarmy-prune "0 10 * * *"
  schedule altarmy-merge "30 * * * *" # hourly: daily medians and 7-day price statistics
}

case "${1:-}" in
  apis | registry | accounts | sql | wif | scheduler) "$1" ;;
  database) database "${2:-}" ;;
  *)
    sed -n '2,15p' "$0"
    exit 1
    ;;
esac
