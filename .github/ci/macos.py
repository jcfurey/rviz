"""Run the exact PR commit natively on macOS, using RoboStack dependencies."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

WORKSPACE = Path(os.environ["GITHUB_WORKSPACE"])
ROOT = WORKSPACE / "validation"
SOURCE = WORKSPACE / "rviz-under-test"
PREFIX = Path(os.environ["CONDA_PREFIX"])
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
PACKAGES = ("rviz_rendering", "rviz_common", "rviz_default_plugins")


def environment():
    env = dict(os.environ)
    overlay_names = ("rviz_default_plugins", "rviz_visual_testing_framework",
                     "rviz_rendering_tests", "rviz_common", "rviz_rendering")
    overlays = [ROOT / "install" / name for name in overlay_names
                if (ROOT / "install" / name).exists()]
    prefixes = os.pathsep.join(str(path) for path in (*overlays, PREFIX))
    env.update({"AMENT_PREFIX_PATH": prefixes, "CMAKE_PREFIX_PATH": prefixes,
                "QT_QPA_PLATFORM": "cocoa", "QT_SCALE_FACTOR": "1",
                "MACOSX_DEPLOYMENT_TARGET": "14.0", "CMAKE_BUILD_PARALLEL_LEVEL": "2",
                "ROS_LOG_DIR": str(ARTIFACTS / "ros-logs")})
    libraries = [ROOT / "build" / name for name in PACKAGES]
    libraries += [ROOT / "install" / name / "lib" for name in PACKAGES]
    libraries += [PREFIX / "lib"]
    env["DYLD_LIBRARY_PATH"] = os.pathsep.join(str(path) for path in libraries)
    return env


def run(command, env, label):
    print("Running:", " ".join(str(value) for value in command), flush=True)
    with (ARTIFACTS / (label + ".log")).open("w") as output:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in process.stdout:
            output.write(line)
            print(line, end="", flush=True)
        status = process.wait()
    if status:
        raise subprocess.CalledProcessError(status, command)


def build(packages, label, env):
    revision = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    assert revision == os.environ["RVIZ_TEST_REF"], revision
    (ARTIFACTS / "source-revision.txt").write_text(revision + "\n")
    rpaths = [ROOT / "install" / name / "lib" for name in PACKAGES] + [PREFIX / "lib"]
    sdk = subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip()
    run(["colcon", "--log-base", str(ARTIFACTS / ("colcon-" + label)), "build",
         "--base-paths", str(SOURCE), "--build-base", str(ROOT / "build"),
         "--install-base", str(ROOT / "install"), "--packages-select", *packages,
         "--packages-ignore", "rviz_ogre_vendor", "--executor", "sequential",
         "--cmake-args", "-G", "Ninja", "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
         "-DCMAKE_C_COMPILER_LAUNCHER=ccache", "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
         "-DBUILD_TESTING=ON", "-DEnableDisplayTests=True", "-DCMAKE_OSX_ARCHITECTURES=arm64",
         "-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0", "-DCMAKE_OSX_SYSROOT=" + sdk,
         "-DCMAKE_INSTALL_RPATH=" + ";".join(str(path) for path in rpaths)], env, label)


def isolate_plugins(env):
    isolated = ROOT / "isolated-underlay"
    share = isolated / "share"
    share.mkdir(parents=True, exist_ok=True)
    for path in PREFIX.iterdir():
        if path.name != "share" and not (isolated / path.name).exists():
            (isolated / path.name).symlink_to(path)
    for path in (PREFIX / "share").iterdir():
        if path.name not in {"ament_index", "rviz_default_plugins"} and not (share / path.name).exists():
            (share / path.name).symlink_to(path)
    index = share / "ament_index"
    if not index.exists():
        shutil.copytree(PREFIX / "share/ament_index", index)
    registrations = index / "resource_index/rviz_common__pluginlib__plugin"
    if registrations.exists():
        shutil.rmtree(registrations)
    registrations.mkdir(parents=True)
    package = index / "resource_index/packages/rviz_default_plugins"
    if package.exists():
        package.unlink()
    env["AMENT_PREFIX_PATH"] = os.pathsep.join(str(path) for path in (
        ROOT / "install/rviz_common", ROOT / "install/rviz_rendering", isolated))
    run([sys.executable, "-c", "from ament_index_python.resources import get_resources; "
         "p = get_resources('rviz_common__pluginlib__plugin'); "
         "assert 'rviz_default_plugins' not in p, p; print('Isolated plugin registrations:', p)"],
        env, "isolated-plugins")


def test(package, label, arguments, env):
    run(["ctest", "--test-dir", str(ROOT / "build" / package), "--no-tests=error",
         "--output-on-failure", "--timeout", "120", "--output-junit",
         str(ARTIFACTS / (label + ".junit.xml")), *arguments], env, label)
    results = ROOT / "build" / package / "test_results"
    if results.exists():
        shutil.copytree(results, ARTIFACTS / (label + "-results"), dirs_exist_ok=True)


def diagnostics(env):
    isolate_plugins(env)
    commands = ARTIFACTS / "lldb-commands.txt"
    commands.write_text(
        "settings set target.disable-aslr false\n"
        "settings set target.env-vars DYLD_LIBRARY_PATH=" + env["DYLD_LIBRARY_PATH"] + "\n"
        "run\nthread backtrace all\nimage list\nquit\n")
    command = ["/usr/bin/lldb", "--batch", "--source", str(commands), "--",
               str(ROOT / "build/rviz_common/viewport_mouse_event_test"),
               "--gtest_filter=ViewportMouseEventTest.mouse_coordinates_include_fractional_scaling"]
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                text=True, errors="replace", timeout=60)
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired as error:
        output = "LLDB timed out after 60 seconds.\n"
        for part in (error.stdout, error.stderr):
            if part:
                output += part.decode(errors="replace") if isinstance(part, bytes) else part
    (ARTIFACTS / "lldb-mouse.log").write_text(output)
    print(output, flush=True)
    reports = ARTIFACTS / "native-crash-reports"
    reports.mkdir(exist_ok=True)
    for report in (Path.home() / "Library/Logs/DiagnosticReports").glob("*"):
        if report.is_file() and report.name.startswith(("viewport_mouse", "render_window_scal")):
            shutil.copy2(report, reports / report.name)


phase = sys.argv[1]
env = environment()
if phase == "environment":
    run(["uname", "-a"], env, "platform")
    run(["sw_vers"], env, "macos-version")
    run(["system_profiler", "SPDisplaysDataType"], env, "displays")
    run(["/usr/bin/swift", "-e", "import AppKit; "
         "for (i, s) in NSScreen.screens.enumerated() { "
         "print(\"screen_\\(i) native_backing_scale=\\(s.backingScaleFactor) frame=\\(s.frame)\") }"],
        env, "native-backing-scale")
    run(["pkg-config", "--modversion", "Qt6Core"], env, "qt-version")
    run([env.get("CXX", "clang++"), "--version"], env, "compiler")
elif phase == "build-common":
    build(["rviz_rendering", "rviz_common"], "build-common", env)
elif phase == "build-plugins":
    build(["rviz_rendering_tests", "rviz_visual_testing_framework", "rviz_default_plugins"], "build-plugins", env)
elif phase == "mouse":
    isolate_plugins(env)
    test("rviz_common", "isolated-mouse", ["-R", "^viewport_mouse_event_test_"], env)
elif phase == "diagnostics":
    diagnostics(env)
elif phase == "matrix":
    # The CMake registrations use Cocoa's native backing scale for viewport/menu
    # tests; mouse/focus cases also run at forced scales 1, 1.25, 1.5, and 2.
    test("rviz_rendering", "viewport", ["-R", "^render_window_scaling_test_"], env)
    test("rviz_default_plugins", "coordinates", ["-R", "^viewport_coordinate_conversion_test_"], env)
elif phase == "gmock":
    for package in PACKAGES:
        test(package, "gmock-" + package, ["-L", "gmock"], env)
else:
    raise ValueError("Unknown phase: " + phase)
