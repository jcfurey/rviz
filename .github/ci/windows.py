"""Build and test the exact PR commit against the official Windows nightly."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path("C:/w")
SOURCE = ROOT / "src/rviz"
ARTIFACTS = ROOT / "artifacts"
ROS = Path(os.environ["ROS_PREFIX"])
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def environment():
    vswhere = Path("C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe")
    studio = subprocess.check_output([
        str(vswhere), "-latest", "-products", "*", "-requires",
        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath",
    ], text=True).strip()
    if not studio:
        raise RuntimeError("Visual Studio C++ tools were not found")
    lines = ["@echo off", f'call "{studio}\\VC\\Auxiliary\\Build\\vcvars64.bat" >nul',
             "if errorlevel 1 exit /b 1", f'call "{ROS}\\local_setup.bat" >nul',
             "if errorlevel 1 exit /b 1"]
    overlay = ROOT / "i/local_setup.bat"
    if overlay.exists():
        lines += [f'call "{overlay}" >nul', "if errorlevel 1 exit /b 1"]
    lines += ["set"]
    batch = ROOT / "environment.cmd"
    batch.write_text("\n".join(lines) + "\n")
    output = subprocess.check_output(["cmd.exe", "/d", "/c", str(batch)], text=True)
    env = {name.upper(): value for name, value in os.environ.items()}
    for line in output.splitlines():
        name, separator, value = line.partition("=")
        if separator and name:
            env[name.upper()] = value
    env.update({"CMAKE_BUILD_PARALLEL_LEVEL": "2", "ROS_LOG_DIR": str(ARTIFACTS / "ros-logs"),
                "QT_SCALE_FACTOR": "1", "QT_OPENGL": "desktop", "GALLIUM_DRIVER": "llvmpipe"})
    return env


def run(command, env, log):
    print("Running:", subprocess.list2cmdline([str(value) for value in command]), flush=True)
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in process.stdout:
            output.write(line)
            print(line, end="", flush=True)
        code = process.wait()
    if code:
        raise subprocess.CalledProcessError(code, command)


def build(packages, label, env):
    if not SOURCE.exists():
        original = Path(os.environ["GITHUB_WORKSPACE"]) / "rviz-under-test"
        revision = subprocess.check_output(["git", "-C", str(original), "rev-parse", "HEAD"], text=True).strip()
        assert revision == os.environ["RVIZ_TEST_REF"], revision
        (ARTIFACTS / "source-revision.txt").write_text(revision + "\n")
        shutil.copytree(original, SOURCE, ignore=shutil.ignore_patterns(".git"))
    colcon = shutil.which("colcon", path=env["PATH"])
    if not colcon:
        raise RuntimeError("colcon was not found in the Pixi environment")
    run([colcon, "--log-base", str(ARTIFACTS / ("build-" + label)),
         "build", "--base-paths", str(SOURCE), "--build-base", str(ROOT / "b"),
         "--install-base", str(ROOT / "i"), "--packages-select", *packages,
         "--packages-ignore", "rviz_ogre_vendor", "--executor", "sequential",
         "--event-handlers", "console_cohesion+",
         "--cmake-args", "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
         "-DCMAKE_C_COMPILER_LAUNCHER=sccache", "-DCMAKE_CXX_COMPILER_LAUNCHER=sccache",
         "-DBUILD_TESTING=ON", "-DEnableDisplayTests=True"], env, ARTIFACTS / ("build-" + label + ".log"))


def junction(destination, target):
    if not destination.exists():
        subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(destination), str(target)],
                       check=True, stdout=subprocess.DEVNULL)


def isolate_plugins(env):
    isolated = ROOT / "isolated-underlay"
    share = isolated / "share"
    share.mkdir(parents=True, exist_ok=True)
    for directory in ROS.iterdir():
        if directory.is_dir() and directory.name not in {"share", ".pixi"}:
            junction(isolated / directory.name, directory)
    for directory in (ROS / "share").iterdir():
        if directory.is_dir() and directory.name not in {"ament_index", "rviz_default_plugins"}:
            junction(share / directory.name, directory)
    index = share / "ament_index"
    if not index.exists():
        shutil.copytree(ROS / "share/ament_index", index)
    registrations = index / "resource_index/rviz_common__pluginlib__plugin"
    if registrations.exists():
        shutil.rmtree(registrations)
    registrations.mkdir(parents=True)
    package = index / "resource_index/packages/rviz_default_plugins"
    if package.exists():
        package.unlink()
    env["AMENT_PREFIX_PATH"] = os.pathsep.join(str(path) for path in (
        ROOT / "i/rviz_common", ROOT / "i/rviz_rendering", isolated))
    run([sys.executable, "-c", "from ament_index_python.resources import get_resources; "
         "p = get_resources('rviz_common__pluginlib__plugin'); "
         "assert 'rviz_default_plugins' not in p, p; print('Isolated plugin registrations:', p)"],
        env, ARTIFACTS / "isolated-plugins.log")


def software_opengl(env):
    candidates = [path for path in Path("C:/mesa").rglob("opengl32.dll") if "x64" in path.parts]
    if len(candidates) != 1:
        raise RuntimeError("Expected one x64 Mesa OpenGL DLL: " + str(candidates))
    mesa = candidates[0].parent
    env["QT_OPENGL_DLL"] = str(candidates[0])
    # Windows resolves imported OpenGL DLLs beside the test executables first.
    for package in ("rviz_rendering", "rviz_common", "rviz_default_plugins"):
        output = ROOT / "b" / package
        if output.exists():
            for library in mesa.glob("*.dll"):
                shutil.copy2(library, output / library.name)


def test(package, label, arguments, env):
    run(["ctest", "--test-dir", str(ROOT / "b" / package), "--no-tests=error",
         "--output-on-failure", "--timeout", "120", "--output-junit",
         str(ARTIFACTS / (label + ".junit.xml")), *arguments], env,
        ARTIFACTS / (label + ".log"))
    results = ROOT / "b" / package / "test_results"
    if results.exists():
        shutil.copytree(results, ARTIFACTS / (label + "-results"), dirs_exist_ok=True)


phase = sys.argv[1]
env = environment()
if phase == "build-common":
    build(["rviz_rendering", "rviz_common"], "common", env)
elif phase == "build-plugins":
    build(["rviz_rendering_tests", "rviz_visual_testing_framework", "rviz_default_plugins"], "plugins", env)
else:
    software_opengl(env)
    if phase == "mouse":
        isolate_plugins(env)
        test("rviz_common", "isolated-mouse", ["-R", "^viewport_mouse_event_test_"], env)
    elif phase == "matrix":
        test("rviz_rendering", "viewport", ["-R", "^render_window_scaling_test_"], env)
        test("rviz_default_plugins", "coordinates", ["-R", "^viewport_coordinate_conversion_test_"], env)
    elif phase == "gmock":
        for package in ("rviz_rendering", "rviz_common", "rviz_default_plugins"):
            test(package, "gmock-" + package, ["-L", "gmock"], env)
    else:
        raise ValueError("Unknown phase: " + phase)
