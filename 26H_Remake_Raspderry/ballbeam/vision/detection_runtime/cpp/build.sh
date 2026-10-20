#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "${source_dir}/.." && pwd)"
# Keep Linux artifacts separate from a Windows build directory that may have
# been copied to the Raspberry Pi together with the workspace.
build_dir="${source_dir}/build-linux"
archive_args=()
if [[ -f "${source_dir}/ncnn.tar.gz" ]]; then
  archive_args+=("-DNCNN_SOURCE_ARCHIVE=${source_dir}/ncnn.tar.gz")
fi

cmake -S "${source_dir}" -B "${build_dir}" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DPython_EXECUTABLE="$(command -v python3 || command -v python)" \
  "${archive_args[@]}"
cmake --build "${build_dir}" --config Release

module="$(find "${build_dir}" -name '_ncnn_cpp*.so' -type f | head -n 1)"
if [[ -z "${module}" ]]; then
  echo "CMake completed but _ncnn_cpp*.so was not produced" >&2
  exit 1
fi
cp "${module}" "${project_dir}/$(basename "${module}")"
echo "Installed $(basename "${module}") to ${project_dir}"
