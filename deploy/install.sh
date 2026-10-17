#!/usr/bin/env sh
# Chronicle one-command install.
#
#   ./deploy/install.sh                            Chronicle + Hermes plugin in this environment
#   ./deploy/install.sh --sandbox NAME             ...and add the Chronicle egress preset (host only)
#   ./deploy/install.sh --sandbox NAME --lockdown  ...and REPLACE the sandbox policy with the
#                                                  strict allow-list (Token Factory + Tavily only)
#
# Run it inside the NemoClaw sandbox (nemoclaw NAME connect) to install the
# plugin, and on the host with --sandbox to apply the network policy. Install
# before --lockdown: the lockdown policy blocks PyPI.
set -eu

REPO_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
HERMES_HOME=${HERMES_HOME:-$HOME/.hermes}
CHRONICLE_HOME=$HOME/.chronicle
SANDBOX=""
LOCKDOWN=0
SKIP_UI=0

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  echo "Options: --sandbox NAME  --lockdown  --no-ui  -h|--help"
}

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --sandbox) [ $# -ge 2 ] || die "--sandbox needs a name"; SANDBOX=$2; shift 2 ;;
    --lockdown) LOCKDOWN=1; shift ;;
    --no-ui) SKIP_UI=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done
[ "$LOCKDOWN" = 0 ] || [ -n "$SANDBOX" ] || die "--lockdown needs --sandbox NAME"

# --- 1. Find the Python that runs Hermes --------------------------------------
hermes_python() {
  if [ -n "${HERMES_PYTHON:-}" ]; then echo "$HERMES_PYTHON"; return; fi
  if [ -x /opt/hermes/.venv/bin/python ]; then echo /opt/hermes/.venv/bin/python; return; fi
  if have hermes; then
    shebang=$(head -n 1 "$(command -v hermes)" 2>/dev/null || true)
    case "$shebang" in
      '#!'*python*) py=${shebang#\#!}; py=${py%% *}; [ -x "$py" ] && { echo "$py"; return; } ;;
    esac
  fi
  return 0
}

install_into() {
  if have uv; then
    uv pip install --quiet --python "$1" "$REPO_DIR"
  else
    "$1" -m pip install --quiet "$REPO_DIR"
  fi
}

PY=$(hermes_python)
if [ -n "$PY" ]; then
  say "Installing Chronicle into the Hermes environment ($PY)"
  install_into "$PY"
else
  warn "Hermes not found; installing Chronicle for development only (set HERMES_PYTHON to override)"
  if have uv; then
    (cd "$REPO_DIR" && uv sync --quiet --extra dev)
    PY=$REPO_DIR/.venv/bin/python
  else
    have python3 || die "python3 (>= 3.10) is required"
    [ -d "$REPO_DIR/.venv" ] || python3 -m venv "$REPO_DIR/.venv"
    PY=$REPO_DIR/.venv/bin/python
    "$PY" -m pip install --quiet -e "$REPO_DIR[dev]"
  fi
fi
"$PY" -c 'import chronicle.integrations.hermes_provider' || die "Chronicle failed to import in $PY"
say "Checking name detection (loads spaCy, takes ~15s)"
"$PY" -c 'import sys; from chronicle.guard.pii_detector import ner_available; sys.exit(0 if ner_available() else 1)' 2>/dev/null \
  || die "Name detection failed to load, so names would reach the model unmasked. The spaCy model
       downloads from github.com: inside a NemoClaw sandbox, add the 'github' preset while installing."

# --- 2. Local state (egress log, LLM cache) stays private to this user ---------
mkdir -p "$CHRONICLE_HOME"
chmod 700 "$CHRONICLE_HOME"
if [ ! -f "$REPO_DIR/.env" ]; then
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
  chmod 600 "$REPO_DIR/.env"
  say "Created .env from .env.example (add NEBIUS_API_KEY when you have it)"
fi

# --- 3. Hermes plugin ----------------------------------------------------------
PLUGIN_DIR=$HERMES_HOME/plugins/chronicle
say "Installing Hermes plugin to $PLUGIN_DIR"
mkdir -p "$HERMES_HOME/plugins"
rm -rf "$PLUGIN_DIR"
cp -R "$REPO_DIR/deploy/hermes-plugin/chronicle" "$PLUGIN_DIR"

# --- 4. UI dependencies --------------------------------------------------------
if [ "$SKIP_UI" = 0 ] && have npm; then
  say "Installing UI dependencies"
  (cd "$REPO_DIR/ui" && npm install --silent --no-audit --no-fund)
elif [ "$SKIP_UI" = 0 ]; then
  warn "npm not found; skipping UI (install Node 18+ to run the Memory Time Machine)"
fi

# --- 5. Sandbox network policy (host side) -------------------------------------
if [ -n "$SANDBOX" ]; then
  if [ "$LOCKDOWN" = 1 ]; then
    have openshell || die "openshell CLI not found; run --lockdown on the host"
    say "Replacing the live policy of '$SANDBOX' with deploy/openshell-policy.yaml"
    openshell policy set --policy "$REPO_DIR/deploy/openshell-policy.yaml" --wait "$SANDBOX"
  else
    have nemoclaw || die "nemoclaw CLI not found; run --sandbox on the host"
    say "Adding the Chronicle egress preset to '$SANDBOX'"
    nemoclaw "$SANDBOX" policy add --from-file "$REPO_DIR/deploy/presets/chronicle.yaml" --yes
  fi
fi

say "Done. Next:"
echo "  hermes memory setup                  # pick 'chronicle'"
echo "  cd ui && npm run dev                 # Memory Time Machine on http://localhost:5173"
[ -z "$SANDBOX" ] || echo "  openshell logs $SANDBOX --source sandbox   # see any blocked requests"
