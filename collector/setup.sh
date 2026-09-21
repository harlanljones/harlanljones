#!/usr/bin/env bash
# Provisions (or updates) the nightly profile collector on GCP, entirely
# inside the personal `harlanljones` gcloud configuration. Idempotent: re-run
# after code changes to rebuild and redeploy.
#
#   collector/setup.sh                 provision/update everything
#   collector/setup.sh --run-now       ...then execute the job once
#   BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX collector/setup.sh   (first run)
#
# Resources (all free-tier sized): Artifact Registry repo, Cloud Storage state
# bucket (mirror tarball), 2 Secret Manager secrets (GitHub PATs), Cloud Run
# Job (2 vCPU / 4 GiB, ~10 min nightly), Cloud Scheduler job, $1 budget alert.
set -euo pipefail

CONFIG="harlanljones"
PROJECT_ID="${PROJECT_ID:-harlanljones-profile}"
REGION="${REGION:-us-central1}"          # Cloud Run + Cloud Storage free tier region
JOB="profile-collector"
REPO="collector"
BUCKET="${PROJECT_ID}-collector-state"
SRC_BUCKET="${PROJECT_ID}-build-source"  # Cloud Build source staging (the default bucket is multi-region, not free tier)
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${JOB}:latest"
JOB_SA="collector-job@${PROJECT_ID}.iam.gserviceaccount.com"
SCHED_SA="collector-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA="collector-build@${PROJECT_ID}.iam.gserviceaccount.com"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

g() {
	if command -v gcloud >/dev/null 2>&1; then
		CLOUDSDK_ACTIVE_CONFIG_NAME="$CONFIG" gcloud "$@"
	else
		CLOUDSDK_ACTIVE_CONFIG_NAME="$CONFIG" mise exec gcloud@585.0.0 -- gcloud "$@"
	fi
}
step() { printf '\n==> %s\n' "$*"; }

# ---- Guard: personal account only, never the work (primeiq.ai) identity.
account="$(g config get-value account 2>/dev/null || true)"
if [[ -z "$account" ]]; then
	echo "No account in gcloud configuration '$CONFIG'. Log in first:" >&2
	echo "  CLOUDSDK_ACTIVE_CONFIG_NAME=$CONFIG gcloud auth login" >&2
	exit 1
fi
if [[ "${account,,}" == *@primeiq.ai ]]; then
	echo "Refusing to run as work account $account." >&2
	exit 1
fi
echo "gcloud configuration: $CONFIG  account: $account  project: $PROJECT_ID  region: $REGION"

step "Project"
if ! g projects describe "$PROJECT_ID" >/dev/null 2>&1; then
	g projects create "$PROJECT_ID" --name="harlanljones profile"
fi
g config set project "$PROJECT_ID" >/dev/null

step "Billing"
if [[ "$(g billing projects describe "$PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null)" != "True" ]]; then
	if [[ -z "${BILLING_ACCOUNT:-}" ]]; then
		echo "Project has no billing account. Pick one of these and re-run with BILLING_ACCOUNT=<id>:" >&2
		g billing accounts list >&2
		exit 1
	fi
	g billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
fi
BILLING_ACCOUNT="$(g billing projects describe "$PROJECT_ID" --format='value(billingAccountName)' | sed 's#billingAccounts/##')"

step "APIs"
g services enable run.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com \
	artifactregistry.googleapis.com cloudbuild.googleapis.com storage.googleapis.com \
	iam.googleapis.com billingbudgets.googleapis.com

step "Service accounts"
for sa in collector-job collector-scheduler collector-build; do
	if ! g iam service-accounts describe "${sa}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1; then
		g iam service-accounts create "$sa" --display-name="profile ${sa#collector-}"
	fi
done
for role in roles/artifactregistry.writer roles/logging.logWriter; do
	g projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$BUILD_SA" \
		--role="$role" --condition=None >/dev/null
done

step "Artifact Registry"
if ! g artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1; then
	g artifacts repositories create "$REPO" --repository-format=docker --location="$REGION"
fi
# Keep only the newest image so storage stays inside the 0.5 GB free tier.
g artifacts repositories set-cleanup-policies "$REPO" --location="$REGION" --policy=- >/dev/null <<'JSON'
[{"name": "keep-latest", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 1}},
 {"name": "delete-rest", "action": {"type": "Delete"}, "condition": {"tagState": "ANY"}}]
JSON

step "State bucket"
if ! g storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
	g storage buckets create "gs://$BUCKET" --location="$REGION" \
		--uniform-bucket-level-access --public-access-prevention
fi
g storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$JOB_SA" \
	--role=roles/storage.objectUser >/dev/null

step "Build source bucket"
if ! g storage buckets describe "gs://$SRC_BUCKET" >/dev/null 2>&1; then
	g storage buckets create "gs://$SRC_BUCKET" --location="$REGION" \
		--uniform-bucket-level-access --public-access-prevention
fi
# Source tarballs are only needed for the build that uploaded them.
# (A real file, not <(...): gcloud under `mise exec` can't read the parent's fds.)
lifecycle="$(mktemp)"
echo '{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 1}}]}' >"$lifecycle"
g storage buckets update "gs://$SRC_BUCKET" --lifecycle-file="$lifecycle" >/dev/null
rm -f "$lifecycle"
g storage buckets add-iam-policy-binding "gs://$SRC_BUCKET" --member="serviceAccount:$BUILD_SA" \
	--role=roles/storage.objectViewer >/dev/null

step "Secrets (fine-grained GitHub PATs)"
# gh-read-token:  all my repositories, Contents: Read, Metadata: Read
# gh-write-token: only harlanljones/harlanljones, Contents: Read and write
for secret in gh-read-token gh-write-token; do
	if ! g secrets describe "$secret" >/dev/null 2>&1; then
		read -rsp "Paste value for $secret: " value
		echo
		printf '%s' "$value" | g secrets create "$secret" --replication-policy=automatic --data-file=-
		unset value
	fi
	g secrets add-iam-policy-binding "$secret" --member="serviceAccount:$JOB_SA" \
		--role=roles/secretmanager.secretAccessor >/dev/null
done

step "Build image"
(cd "$ROOT" && g builds submit --config=collector/cloudbuild.yaml --substitutions="_IMAGE=$IMAGE" \
	--gcs-source-staging-dir="gs://$SRC_BUCKET/source" --service-account="projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" --region="$REGION" .)

step "Cloud Run Job"
g run jobs deploy "$JOB" --image="$IMAGE" --region="$REGION" --service-account="$JOB_SA" \
	--cpu=2 --memory=4Gi --task-timeout=3600 --max-retries=1 \
	--set-secrets="GH_READ_TOKEN=gh-read-token:latest,GH_WRITE_TOKEN=gh-write-token:latest" \
	--add-volume="name=state,type=cloud-storage,bucket=$BUCKET" \
	--add-volume-mount="volume=state,mount-path=/mnt/state"
g run jobs add-iam-policy-binding "$JOB" --region="$REGION" --member="serviceAccount:$SCHED_SA" \
	--role=roles/run.invoker >/dev/null

step "Nightly schedule (03:15 Pacific)"
sched_args=(--location="$REGION" --schedule="15 3 * * *" --time-zone="America/Los_Angeles"
	--uri="https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs/$JOB:run"
	--http-method=POST --oauth-service-account-email="$SCHED_SA")
if g scheduler jobs describe "$JOB-nightly" --location="$REGION" >/dev/null 2>&1; then
	g scheduler jobs update http "$JOB-nightly" "${sched_args[@]}"
else
	g scheduler jobs create http "$JOB-nightly" "${sched_args[@]}"
fi

step "Budget alert (\$1)"
if ! g billing budgets list --billing-account="$BILLING_ACCOUNT" --format='value(displayName)' 2>/dev/null \
	| grep -qx "$JOB budget"; then
	g billing budgets create --billing-account="$BILLING_ACCOUNT" --display-name="$JOB budget" \
		--budget-amount=1USD --threshold-rule=percent=0.5 --threshold-rule=percent=1.0 \
		--filter-projects="projects/$PROJECT_ID" ||
		echo "Budget creation failed (needs Billing Account Costs Manager); set one in the console." >&2
fi

if [[ "${1:-}" == "--run-now" ]]; then
	step "Executing job"
	g run jobs execute "$JOB" --region="$REGION" --wait
fi
echo
echo "Done. Logs: gcloud run jobs executions list --job=$JOB --region=$REGION"
