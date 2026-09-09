# Creates infra/.venv on first use (installing requirements.txt into it), then
# activates it in your current shell. Only infra/ needs this - deploy.py and the
# Lambda code depend on boto3, but the Python demo app (python/app.py) is stdlib-only
# and never needs a virtual environment.
#
# Must be SOURCED, not executed, so the activation applies to your shell:
#   source activate.sh
#   (or: . activate.sh)

sourced=0
if [ -n "$ZSH_VERSION" ]; then
  case $ZSH_EVAL_CONTEXT in *:file) sourced=1 ;; esac
elif [ -n "$BASH_VERSION" ]; then
  [ "${BASH_SOURCE[0]}" != "$0" ] && sourced=1
fi

if [ "$sourced" -ne 1 ]; then
  echo "This script must be sourced, not executed, so it can activate the" >&2
  echo "virtual environment in your current shell. Run:" >&2
  echo "  source activate.sh" >&2
  exit 1
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

if [ ! -d "$DIR/.venv" ]; then
  echo "Creating virtual environment in infra/.venv..."
  python3 -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install --quiet -r "$DIR/requirements.txt"
fi

source "$DIR/.venv/bin/activate"
echo "Virtual environment active (infra/.venv). Now run:"
echo "  python3 deploy.py --gen-model-id <your-bedrock-model-id>"
