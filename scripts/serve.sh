#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${PROJECT_ROOT}/configs/scripts.yaml"
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
Usage: scripts/serve.sh [--config PATH] [-- V2K_SERVE_ARGS...]

Start the Video2Knowledge GUI using the environment and runtime settings from
the shared YAML configuration. Arguments after -- override/add v2k serve flags.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      [[ $# -ge 2 ]] || { echo "Error: --config requires a path." >&2; exit 2; }
      CONFIG_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      EXTRA_ARGS=("$@")
      break
      ;;
    *)
      echo "Error: unknown argument: $1 (put v2k arguments after --)" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -f "${CONFIG_FILE}" ]] || { echo "Error: config file not found: ${CONFIG_FILE}" >&2; exit 1; }

yaml_value() {
  local key="$1"
  awk -v wanted="${key}" '
    /^[[:space:]]*(#|$)/ { next }
    {
      separator = index($0, ":")
      if (!separator) next
      name = substr($0, 1, separator - 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
      if (name != wanted) next
      value = substr($0, separator + 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      if ((substr(value, 1, 1) == "\"" && substr(value, length(value), 1) == "\"") ||
          (substr(value, 1, 1) == "\047" && substr(value, length(value), 1) == "\047")) {
        value = substr(value, 2, length(value) - 2)
      }
      print value
      exit
    }
  ' "${CONFIG_FILE}"
}

required_value() {
  local key="$1" value
  value="$(yaml_value "${key}")"
  [[ -n "${value}" ]] || { echo "Error: missing '${key}' in ${CONFIG_FILE}" >&2; exit 1; }
  printf '%s' "${value}"
}

absolute_from_root() {
  if [[ "$1" = /* ]]; then
    printf '%s' "$1"
  else
    printf '%s/%s' "${PROJECT_ROOT}" "$1"
  fi
}

MANAGER="$(required_value environment_manager)"
VIRTUALENV_DIR="$(absolute_from_root "$(required_value virtualenv_dir)")"
CONDA_ENVIRONMENT="$(required_value conda_environment)"
DATA_DIR="$(absolute_from_root "$(required_value data_dir)")"
GUI_HOST="$(required_value gui_host)"
GUI_PORT="$(required_value gui_port)"
GUI_RELOAD="$(required_value gui_reload)"

[[ "${GUI_PORT}" =~ ^[0-9]+$ ]] && (( GUI_PORT >= 1 && GUI_PORT <= 65535 )) || {
  echo "Error: gui_port must be between 1 and 65535." >&2
  exit 1
}

serve_args=(serve --host "${GUI_HOST}" --port "${GUI_PORT}")
if [[ "${GUI_RELOAD}" == "true" || "${GUI_RELOAD}" == "yes" || "${GUI_RELOAD}" == "1" ]]; then
  serve_args+=(--reload)
fi
serve_args+=("${EXTRA_ARGS[@]}")

cd "${PROJECT_ROOT}"
echo "Starting Video2Knowledge GUI at http://${GUI_HOST}:${GUI_PORT}"

case "${MANAGER}" in
  uv)
    command -v uv >/dev/null 2>&1 || { echo "Error: uv is not installed; run scripts/build_env.sh first." >&2; exit 1; }
    [[ -x "${VIRTUALENV_DIR}/bin/python" ]] || { echo "Error: environment not found at ${VIRTUALENV_DIR}; run scripts/build_env.sh first." >&2; exit 1; }
    V2K_DATA_DIR="${DATA_DIR}" UV_PROJECT_ENVIRONMENT="${VIRTUALENV_DIR}" exec uv run v2k "${serve_args[@]}"
    ;;
  conda)
    command -v conda >/dev/null 2>&1 || { echo "Error: conda is not installed; run scripts/build_env.sh first." >&2; exit 1; }
    V2K_DATA_DIR="${DATA_DIR}" exec conda run --no-capture-output --name "${CONDA_ENVIRONMENT}" v2k "${serve_args[@]}"
    ;;
  venv)
    [[ -x "${VIRTUALENV_DIR}/bin/v2k" ]] || { echo "Error: environment not found at ${VIRTUALENV_DIR}; run scripts/build_env.sh first." >&2; exit 1; }
    V2K_DATA_DIR="${DATA_DIR}" exec "${VIRTUALENV_DIR}/bin/v2k" "${serve_args[@]}"
    ;;
  *)
    echo "Error: environment_manager must be uv, conda, or venv (got '${MANAGER}')." >&2
    exit 1
    ;;
esac
