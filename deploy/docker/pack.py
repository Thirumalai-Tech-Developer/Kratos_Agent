"""Build one self-contained Ubuntu installer without exporting local secrets."""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_FILES = (
    "Dockerfile",
    ".dockerignore",
    "compose.yaml",
    "deploy/docker/.env.example",
    "deploy/docker/entrypoint.sh",
    "deploy/docker/healthcheck.py",
    "deploy/docker/install.sh",
    "deploy/docker/README.md",
    "deploy/docker/pack.py",
)


def checked_member(member: tarfile.TarInfo) -> None:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe archive path: {member.name}")
    if member.issym() or member.islnk():
        raise ValueError(f"Review this tracked link before packaging: {member.name}")
    forbidden = {".env", "studio-secrets.json", "Cookies", "Login Data"}
    if path.name in forbidden or ".kratos" in path.parts:
        raise ValueError(f"Private state must not be packaged: {member.name}")


def package(output: Path) -> None:
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    with tempfile.TemporaryDirectory(prefix="kratos-docker-package-") as temp:
        original = Path(temp) / "tracked.tar"
        archive = Path(temp) / "source.tar.gz"
        subprocess.run(
            ["git", "archive", "--format=tar", f"--output={original}", revision],
            cwd=ROOT, check=True,
        )
        with original.open("rb") as source, archive.open("wb") as target:
            with gzip.GzipFile(fileobj=target, mode="wb", mtime=0) as zipped:
                with tarfile.open(fileobj=source, mode="r|") as src_tar:
                    with tarfile.open(fileobj=zipped, mode="w|") as dst_tar:
                        for member in src_tar:
                            checked_member(member)
                            if member.name in DEPLOYMENT_FILES:
                                continue
                            data = src_tar.extractfile(member) if member.isfile() else None
                            dst_tar.addfile(member, data)
                            if data is not None:
                                data.close()
                        for relative in DEPLOYMENT_FILES:
                            data = (ROOT / relative).read_bytes()
                            # Text scripts must survive SCP without CRLF issues.
                            data = data.replace(b"\r\n", b"\n")
                            member = tarfile.TarInfo(relative)
                            member.size = len(data)
                            member.mode = 0o755 if relative.endswith(".sh") else 0o644
                            member.mtime = 0
                            dst_tar.addfile(member, io.BytesIO(data))
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        header = (ROOT / "deploy/docker/install.sh").read_text(encoding="utf-8")
        header = re.sub(r"^SOURCE_REVISION=.*$", f"SOURCE_REVISION={revision}", header, flags=re.M)
        header = re.sub(r"^SOURCE_SHA256=.*$", f"SOURCE_SHA256={digest}", header, flags=re.M)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as packaged:
            packaged.write(header.replace("\r\n", "\n").encode("utf-8"))
            packaged.write(b"\n: <<'__KRATOS_SOURCE_PAYLOAD_END__'\n__KRATOS_SOURCE_PAYLOAD_BEGIN__\n")
            with archive.open("rb") as source:
                base64.encode(source, packaged)
            packaged.write(b"__KRATOS_SOURCE_PAYLOAD_END__\n")
        print(f"Installer: {output}")
        print(f"Source revision: {revision}")
        print(f"Source archive SHA256: {digest}")
        print(f"Size: {output.stat().st_size / 1024 / 1024:.1f} MiB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    package(args.output.resolve())
