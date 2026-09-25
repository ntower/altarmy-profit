# Names shared by deploy/*.sh. Sourced, not run. Every gcloud call passes the project explicitly, so the
# caller's gcloud defaults (project, quota project) never matter.
PROJECT=alt-army-prod
PROJECT_NUMBER=516573536063
REGION=us-central1
GCLOUD_FLAGS=(--project "$PROJECT" --billing-project "$PROJECT" --quiet)

REPO=altarmy                                   # Artifact Registry (docker)
IMAGE_BASE="$REGION-docker.pkg.dev/$PROJECT/$REPO/altarmy"

SQL_INSTANCE=altarmy-pg                        # Cloud SQL Postgres 16, db-f1-micro
SQL_CONNECTION="$PROJECT:$REGION:$SQL_INSTANCE"

RUN_SA="altarmy-run@$PROJECT.iam.gserviceaccount.com"             # the service and jobs run as this
SCHEDULER_SA="altarmy-scheduler@$PROJECT.iam.gserviceaccount.com" # Cloud Scheduler starts jobs as this
DEPLOY_SA="altarmy-deploy@$PROJECT.iam.gserviceaccount.com"       # CI (Workload Identity Federation)

WIF_POOL=github
WIF_PROVIDER=github-actions
GITHUB_REPO=ntower/altarmy-profit

# Per environment: prod | staging. Sets SERVICE, DB_NAME, DB_USER, SECRET, JOB_PREFIX, MAX_INSTANCES.
env_config() {
  case "$1" in
    prod)
      SERVICE=altarmy DB_NAME=altarmy DB_USER=altarmy SECRET=database-url JOB_PREFIX=altarmy MAX_INSTANCES=2
      ;;
    staging)
      SERVICE=altarmy-staging DB_NAME=altarmy_staging DB_USER=altarmy_staging SECRET=database-url-staging
      JOB_PREFIX=altarmy-staging MAX_INSTANCES=1
      ;;
    *)
      echo "environment must be prod or staging, not '$1'" >&2
      return 1
      ;;
  esac
}

# The Firebase web config (public) from hosted.env, as Cloud Run env vars.
firebase_env() {
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  grep -E '^FIREBASE_(PROJECT_ID|API_KEY|AUTH_DOMAIN)=' "$root/hosted.env" | tr -d '\r' | paste -sd, -
}
