#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${PROJECT_ROOT}/configs/scripts.yaml"

usage() {
  cat <<'EOF'
Usage: scripts/build_env.sh [--config PATH]

Create the development environment using the shared YAML configuration.
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
    *)
      echo "Error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -f "${CONFIG_FILE}" ]] || { echo "Error: config file not found: ${CONFIG_FILE}" >&2; exit 1; }

# Read the deliberately flat YAML file without requiring dependencies before setup.
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

is_true() {
  [[ "$1" == "true" || "$1" == "yes" || "$1" == "1" ]]
}

absolute_from_root() {
  if [[ "$1" = /* ]]; then
    printf '%s' "$1"
  else
    printf '%s/%s' "${PROJECT_ROOT}" "$1"
  fi
}

MANAGER="$(required_value environment_manager)"
PYTHON_VERSION="$(required_value python_version)"
VIRTUALENV_DIR="$(absolute_from_root "$(required_value virtualenv_dir)")"
CONDA_ENVIRONMENT="$(required_value conda_environment)"
INSTALL_EXTRAS="$(yaml_value install_extras)"
INSTALL_MLX="$(required_value install_mlx)"
INSTALL_BILI_DL="$(required_value install_bili_dl)"
BILI_DL_REPOSITORY="$(required_value bili_dl_repository)"
BILI_DL_DIR="$(absolute_from_root "$(required_value bili_dl_dir)")"
INITIALIZE_APP="$(required_value initialize_app)"
DATA_DIR="$(absolute_from_root "$(required_value data_dir)")"

extras="${INSTALL_EXTRAS}"
if is_true "${INSTALL_MLX}"; then
  extras="${extras:+${extras},}mlx"
fi

uv_args=()
pip_target="."
if [[ -n "${extras}" ]]; then
  IFS=',' read -r -a extra_names <<< "${extras}"
  for extra in "${extra_names[@]}"; do
    extra="${extra//[[:space:]]/}"
    [[ -n "${extra}" ]] && uv_args+=(--extra "${extra}")
  done
  pip_target=".[${extras}]"
fi

cd "${PROJECT_ROOT}"

case "${MANAGER}" in
  uv)
    command -v uv >/dev/null 2>&1 || { echo "Error: uv is not installed." >&2; exit 1; }
    echo "Creating uv environment at ${VIRTUALENV_DIR} (Python ${PYTHON_VERSION})..."
    UV_PROJECT_ENVIRONMENT="${VIRTUALENV_DIR}" uv sync --python "${PYTHON_VERSION}" "${uv_args[@]}"
    RUNNER=(uv run)
    ;;
  conda)
    command -v conda >/dev/null 2>&1 || { echo "Error: conda is not installed." >&2; exit 1; }
    if conda env list | awk '{print $1}' | grep -Fxq "${CONDA_ENVIRONMENT}"; then
      echo "Updating Conda environment '${CONDA_ENVIRONMENT}'..."
    else
      echo "Creating Conda environment '${CONDA_ENVIRONMENT}' (Python ${PYTHON_VERSION})..."
      conda create --yes --name "${CONDA_ENVIRONMENT}" "python=${PYTHON_VERSION}"
    fi
    conda run --name "${CONDA_ENVIRONMENT}" python -m pip install --editable "${pip_target}"
    RUNNER=(conda run --name "${CONDA_ENVIRONMENT}")
    ;;
  venv)
    command -v "python${PYTHON_VERSION}" >/dev/null 2>&1 || {
      echo "Error: python${PYTHON_VERSION} is not installed or not on PATH." >&2
      exit 1
    }
    echo "Creating virtual environment at ${VIRTUALENV_DIR}..."
    "python${PYTHON_VERSION}" -m venv "${VIRTUALENV_DIR}"
    "${VIRTUALENV_DIR}/bin/python" -m pip install --upgrade pip
    "${VIRTUALENV_DIR}/bin/python" -m pip install --editable "${pip_target}"
    RUNNER=("${VIRTUALENV_DIR}/bin")
    ;;
  *)
    echo "Error: environment_manager must be uv, conda, or venv (got '${MANAGER}')." >&2
    exit 1
    ;;
esac

if is_true "${INSTALL_BILI_DL}"; then
  command -v git >/dev/null 2>&1 || { echo "Error: git is required to install bili-dl." >&2; exit 1; }
  if [[ -d "${BILI_DL_DIR}/.git" ]]; then
    echo "bili-dl already exists at ${BILI_DL_DIR}; leaving it unchanged."
  elif [[ -e "${BILI_DL_DIR}" ]]; then
    echo "Error: bili_dl_dir exists but is not a Git checkout: ${BILI_DL_DIR}" >&2
    exit 1
  else
    mkdir -p "$(dirname "${BILI_DL_DIR}")"
    git clone "${BILI_DL_REPOSITORY}" "${BILI_DL_DIR}"
  fi
fi

if is_true "${INITIALIZE_APP}"; then
  echo "Initializing application data at ${DATA_DIR}..."
  case "${MANAGER}" in
    uv) V2K_DATA_DIR="${DATA_DIR}" UV_PROJECT_ENVIRONMENT="${VIRTUALENV_DIR}" "${RUNNER[@]}" v2k init ;;
    conda) V2K_DATA_DIR="${DATA_DIR}" "${RUNNER[@]}" v2k init ;;
    venv) V2K_DATA_DIR="${DATA_DIR}" "${VIRTUALENV_DIR}/bin/v2k" init ;;
  esac
fi

echo "Environment is ready. Start the GUI with: scripts/serve.sh --config ${CONFIG_FILE}"
