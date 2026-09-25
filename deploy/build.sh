#!/usr/bin/env bash
# Build the image and push it to Artifact Registry; prints the image reference last.
#   deploy/build.sh [tag]           docker (CI)
#   BUILDER=cloudbuild deploy/build.sh [tag]   Cloud Build (a machine without Docker)
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

TAG="${1:-$(git rev-parse --short=12 HEAD)$(git diff --quiet HEAD -- src data pyproject.toml Dockerfile || echo -dirty)}"
IMAGE="$IMAGE_BASE:$TAG"

if [ "${BUILDER:-docker}" = cloudbuild ]; then
  gcloud builds submit . --config deploy/cloudbuild.yaml --substitutions "_IMAGE=$IMAGE" \
    --region "$REGION" --service-account "projects/$PROJECT/serviceAccounts/$DEPLOY_SA" "${GCLOUD_FLAGS[@]}" >&2
else
  docker build -t "$IMAGE" . >&2
  docker push "$IMAGE" >&2
fi
echo "$IMAGE"
