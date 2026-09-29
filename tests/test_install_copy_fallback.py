import os
from pathlib import Path
import subprocess
import sys


def test_clone_failure_discards_only_partial_staging_target(tmp_path):
    script = (Path(__file__).parents[1] / "scripts/install-local.sh").read_text()
    function = script.split("copy_path() {", 1)[1].split("\n}\n", 1)[0]
    source, destination = tmp_path / "source tree", tmp_path / "staged tree"
    source.mkdir()
    (source / "keep.txt").write_text("original")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    copier = binaries / "cp"
    copier.write_text(
        '#!/bin/sh\nif [ "$1" = "-cR" ]; then mkdir -p "$3"; touch "$3/partial"; exit 1; fi\nexec /bin/cp "$@"\n'
    )
    copier.chmod(0o755)
    result = subprocess.run(
        [
            "bash",
            "-c",
            "set -eu\ncopy_platform=Darwin\ncopy_path() {"
            + function
            + '\n}\ncopy_path "$1" "$2"',
            "copy-test",
            str(source),
            str(destination),
        ],
        env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in destination.iterdir()) == ["keep.txt"]
    (destination / "keep.txt").write_text("changed")
    assert (source / "keep.txt").read_text() == "original"


def run_apps_copy(source, destination):
    script = (Path(__file__).parents[1] / "scripts/install-local.sh").read_text()
    functions = "\n".join(
        name + "() {" + script.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}"
        for name in ("copy_path", "copy_apps")
    )
    return subprocess.run(
        ["bash", "-c", 'set -eu\ncopy_platform=other\n' + functions + '\ncopy_apps "$1" "$2"',
         "apps-copy-test", str(source), str(destination)],
        env={**os.environ, "LOOPX_PYTHON": sys.executable},
        capture_output=True,
        text=True,
    )


def test_apps_snapshot_excludes_developer_trees_without_changing_files(tmp_path):
    source, destination = tmp_path / "source apps", tmp_path / "release apps"
    project = source / "project"
    project.mkdir(parents=True)
    for name in ("node_modules", ".next", "dist", "build", "coverage"):
        tree = project / "nested" / name
        tree.mkdir(parents=True)
        (tree / "not-shipped.js").write_text("development output")
    (project / "nested" / "keep.ts").write_text("source")
    executable = project / "run.sh"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o751)
    (project / "source-link").symlink_to("nested/keep.ts")
    (project / "dangling-link").symlink_to("missing.ts")
    (project / "node_modules").symlink_to("missing-dependency")

    result = run_apps_copy(source, destination)
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in (destination / "project" / "nested").iterdir()) == ["keep.ts"]
    delivered = destination / "project"
    assert sorted(p.name for p in delivered.iterdir()) == [
        "dangling-link", "nested", "run.sh", "source-link"
    ]
    assert (delivered / "run.sh").read_bytes() == executable.read_bytes()
    assert (delivered / "run.sh").stat().st_mode & 0o777 == 0o751
    assert (delivered / "source-link").readlink() == Path("nested/keep.ts")
    assert (delivered / "dangling-link").readlink() == Path("missing.ts")
    (delivered / "nested" / "keep.ts").write_text("changed release")
    assert (project / "nested" / "keep.ts").read_text() == "source"
    assert (project / "nested" / "node_modules" / "not-shipped.js").is_file()


def test_apps_snapshot_keeps_ordinary_files_with_excluded_directory_names(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "release"
    source.mkdir()
    names = ("node_modules", ".next", "dist", "build", "coverage")
    for name in names:
        (source / name).write_text("ordinary source file")
    result = run_apps_copy(source, destination)
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in destination.iterdir()) == sorted(names)
    assert all((destination / name).read_text() == "ordinary source file" for name in names)


def test_apps_snapshot_preserves_root_symlink_and_absent_source(tmp_path):
    source, destination = tmp_path / "source-link", tmp_path / "release-link"
    real_source = tmp_path / "real-source"
    real_source.mkdir()
    source.symlink_to("real-source", target_is_directory=True)
    result = run_apps_copy(source, destination)
    assert result.returncode == 0, result.stderr
    assert destination.is_symlink()
    assert destination.readlink() == Path("real-source")
    absent_destination = tmp_path / "absent-release"
    result = run_apps_copy(tmp_path / "absent-source", absent_destination)
    assert result.returncode == 0, result.stderr
    assert not absent_destination.exists()
