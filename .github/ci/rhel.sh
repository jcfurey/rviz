#!/usr/bin/env bash
set -eo pipefail

ci_root="${GITHUB_WORKSPACE:-$(pwd)}"
source_dir="$ci_root/rviz-under-test"
artifacts_dir="$ci_root/validation/artifacts"
mkdir -p "$artifacts_dir"

if [[ "${1:-}" != dependencies ]]; then
  exec bash "$(dirname "$0")/linux.sh" "$@"
fi

# Match ci_linux-rhel: AlmaLinux 10, EPEL/CRB, Qt 6, and xwfb-run.
# Use the official Rolling nightly; the five RViz packages are built from source.
# shellcheck disable=SC2016 # Replace the literal DNF variable in repo files.
sed -i 's/\$releasever/10/g' /etc/yum.repos.d/*.repo
dnf install -y epel-release 'dnf-command(config-manager)' curl-minimal
dnf config-manager --set-enabled crb
rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-*

repo_package="$artifacts_dir/ros2-release-1.3.0-1.el.noarch.rpm"
curl --fail --location --retry 3 \
  https://github.com/ros-infrastructure/ros-apt-source/releases/download/1.3.0/ros2-release-1.3.0-1.el.noarch.rpm \
  --output "$repo_package"
printf '%s  %s\n' \
  8b21cf0b65cdc29d6079ca231456e976eafeb46f7d9ed6e19684d7c4fc6d49d8 \
  "$repo_package" | sha256sum --check
dnf install -y "$repo_package"
dnf install -y \
  bzip2 cmake gcc-c++ git glibc-langpack-en make patch pkgconf-pkg-config tar \
  python3-colcon-common-extensions python3-rosdep python3-vcstool \
  xwayland-run xorg-x11-xauth \
  mesa-dri-drivers mesa-libGL mesa-libGLU

# RHEL 10 dropped pydocstyle; Rolling xacro has no release RPM here.
# Provision their Python distributions explicitly, as upstream does for pydocstyle.
python3 -m pip install 'pydocstyle==6.3.0' 'xacro==2.1.1'

ros_prefix="/opt/ros/$ROS_DISTRO"
ros_bundle="$ci_root/validation/ros2-rolling-nightly-linux-rhel-amd64.tar.bz2"
if [[ ! -f "$ros_bundle" ]]; then
  curl --fail --location --retry 3 \
    https://github.com/ros2/ros2/releases/download/release-rolling-nightlies/ros2-rolling-nightly-linux-rhel-amd64.tar.bz2 \
    --output "$ros_bundle"
fi
printf '%s  %s\n' \
  b57ae57908ee72adddd8c47cdf7dd50a0072103e10e139a105e78a841fafa20f \
  "$ros_bundle" | sha256sum --check
mkdir -p "$ros_prefix"
if [[ ! -f "$ros_prefix/setup.bash" ]]; then
  tar -xjf "$ros_bundle" --strip-components=1 -C "$ros_prefix"
fi

# The nightly includes downstream RViz. Keep its plugin registration out of
# discovery until our source-built default plugins register themselves.
plugin_registration="$ros_prefix/share/ament_index/resource_index/rviz_common__pluginlib__plugin/rviz_default_plugins"
if [[ -f "$plugin_registration" ]]; then
  cp "$plugin_registration" "$artifacts_dir/underlay-rviz-default-plugins.txt"
  rm "$plugin_registration"
fi

# shellcheck source=/dev/null
source "$ros_prefix/setup.bash"

if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
  rosdep init
fi
rosdep update --rosdistro "$ROS_DISTRO"
for dependency_path in "$ros_prefix/share" "$source_dir"; do
  rosdep install --from-paths "$dependency_path" --ignore-src \
    --rosdistro "$ROS_DISTRO" --os=rhel:10 -y \
    --skip-keys 'cyclonedds fastcdr fastdds iceoryx_binding_c rti-connext-dds-7.7.0 urdfdom_headers xacro pydocstyle'
done

{
  git -C "$source_dir" rev-parse HEAD
  uname -a
  cat /etc/os-release
  gcc --version
  cmake --version
  pkg-config --modversion Qt6Core
  rpm -q xwayland-run qt6-qtbase mesa-libGL
  python3 -m pip show pydocstyle xacro
  printf 'ROS nightly SHA256: %s\n' \
    b57ae57908ee72adddd8c47cdf7dd50a0072103e10e139a105e78a841fafa20f
} > "$artifacts_dir/environment.txt"
