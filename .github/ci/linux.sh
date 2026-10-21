#!/usr/bin/env bash
set -eo pipefail

ci_root="${GITHUB_WORKSPACE:-$(pwd)}"
source_dir="$ci_root/rviz-under-test"
validation_dir="$ci_root/validation"
artifacts_dir="$validation_dir/artifacts"
mkdir -p "$artifacts_dir"

source_ros() {
  source "/opt/ros/$ROS_DISTRO/setup.bash"
  if [[ -f "$validation_dir/install/local_setup.bash" ]]; then
    source "$validation_dir/install/local_setup.bash"
  fi
  export ROS_LOG_DIR="$artifacts_dir/ros-logs"
  export XDG_RUNTIME_DIR="$validation_dir/xdg-runtime"
  mkdir -p "$XDG_RUNTIME_DIR"
  chmod 700 "$XDG_RUNTIME_DIR"
}

build_packages() {
  local label="$1"
  shift
  source_ros
  cd "$validation_dir"
  colcon --log-base "$artifacts_dir/build-$label" build \
    --base-paths "$source_dir" --build-base build --install-base install \
    --packages-select "$@" --packages-ignore rviz_ogre_vendor \
    --executor sequential --event-handlers console_cohesion+ \
    --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON \
      -DEnableDisplayTests=True 2>&1 | tee "$artifacts_dir/build-$label.log"
}

run_ctest() {
  local package="$1"
  shift
  ctest --test-dir "$validation_dir/build/$package" \
    --no-tests=error --output-on-failure --timeout 120 \
    --output-junit "$results_dir/$package.junit.xml" "$@" \
    2>&1 | tee "$results_dir/$package.log"
  if [[ -d "$validation_dir/build/$package/test_results" ]]; then
    cp -a "$validation_dir/build/$package/test_results" "$results_dir/$package-results"
  fi
}

case "$1" in
  dependencies)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
      build-essential cmake git pkg-config python3-colcon-common-extensions \
      python3-rosdep python3-vcstool xvfb xauth x11-utils \
      matchbox-window-manager libgl1-mesa-dri libglx-mesa0 \
      "ros-$ROS_DISTRO-rviz-ogre-vendor"
    if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
      rosdep init
    fi
    rosdep update --rosdistro "$ROS_DISTRO"
    rosdep install --from-paths "$source_dir" --ignore-src \
      --rosdistro "$ROS_DISTRO" -y
    {
      git -C "$source_dir" rev-parse HEAD
      uname -a
      cat /etc/os-release
      gcc --version
      cmake --version
      pkg-config --modversion Qt6Core
    } > "$artifacts_dir/environment.txt"
    ;;
  build-common)
    build_packages common rviz_rendering rviz_common
    ;;
  build-plugins)
    build_packages plugins rviz_rendering_tests rviz_visual_testing_framework rviz_default_plugins
    ;;
  test)
    phase="$2"
    wm="$3"
    source_ros
    results_dir="$artifacts_dir/$phase-$wm"
    mkdir -p "$results_dir"
    if [[ "$wm" == matchbox ]]; then
      matchbox-window-manager > "$results_dir/matchbox.log" 2>&1 &
      wm_pid=$!
      trap 'kill "$wm_pid" 2>/dev/null || true' EXIT
      for attempt in {1..100}; do
        if xprop -root _NET_SUPPORTING_WM_CHECK | grep -q 'window id'; then
          break
        fi
        kill -0 "$wm_pid"
        sleep 0.05
      done
      xprop -root _NET_SUPPORTING_WM_CHECK | grep -q 'window id'
    fi
    case "$phase" in
      mouse)
        python3 - <<'PY'
from ament_index_python.resources import get_resources
plugins = get_resources('rviz_common__pluginlib__plugin')
assert 'rviz_default_plugins' not in plugins, plugins
print('Verified downstream RViz plugins are absent:', plugins)
PY
        run_ctest rviz_common -R '^viewport_mouse_event_test_'
        ;;
      matrix)
        run_ctest rviz_rendering -R '^render_window_scaling_test_'
        run_ctest rviz_default_plugins -R '^viewport_coordinate_conversion_test_'
        ;;
      gmock)
        export QT_SCALE_FACTOR=1
        for package in rviz_rendering rviz_common rviz_default_plugins; do
          run_ctest "$package" -L gmock
        done
        ;;
      *)
        printf 'Unknown test phase: %s\n' "$phase" >&2
        exit 2
        ;;
    esac
    ;;
  *)
    printf 'Unknown CI command: %s\n' "$1" >&2
    exit 2
    ;;
esac
