import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen


REPO = "garooduh/castorsteel"
API = f"https://api.github.com/repos/{REPO}"
STATE = Path("/var/lib/castorsteel")
NGINX = "http://127.0.0.1"
SITE_HOST = "castorsteel.ru"
PUBLIC_FILES = {"favicon.ico", "robots.txt", "sitemap.xml"}
PUBLIC_EXTENSIONS = {".html", ".css", ".js"}
PAGES = (
    "/",
    "/nastennaya-sistema/",
    "/potolochnaya-sistema/",
    "/raspornaya-sistema/",
)


def github_json(path):
    request = Request(API + path, headers={"Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def approved_commit():
    sha = github_json("/branches/main")["commit"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("GitHub returned an invalid commit SHA")
    try:
        runs = github_json(
            "/actions/workflows/site.yml/runs"
            f"?branch=main&event=push&head_sha={sha}&per_page=1"
        )["workflow_runs"]
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    if runs and runs[0]["head_sha"] == sha and runs[0]["conclusion"] == "success":
        return sha
    return None


def unpack_release(sha, release):
    source = f"https://codeload.github.com/{REPO}/tar.gz/{sha}"
    with urlopen(source, timeout=30) as response, tarfile.open(fileobj=response, mode="r|gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            relative = path.parts[1:]
            if path.is_absolute() or not relative or any(part.startswith(".") for part in relative):
                continue
            if not member.isfile():
                continue
            is_site_file = len(relative) == 1 and relative[0] in PUBLIC_FILES
            if relative[0] != "assets" and path.suffix not in PUBLIC_EXTENSIONS and not is_site_file:
                continue
            target = release.joinpath(*relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as contents, target.open("xb") as output:
                shutil.copyfileobj(contents, output)

    for page in PAGES:
        relative_index = release / page.strip("/") / "index.html"
        if not relative_index.is_file():
            raise ValueError(f"Release is missing {page}")


def switch_current(target, current, scratch):
    pending_link = scratch / "current"
    pending_link.symlink_to(target)
    pending_link.replace(current)


def check_nginx(release):
    for path in PAGES:
        request = Request(NGINX + path, headers={"Host": SITE_HOST})
        expected = (release / path.strip("/") / "index.html").read_bytes()
        with urlopen(request, timeout=5) as response:
            if response.read(len(expected) + 1) != expected:
                raise ValueError(f"Nginx is serving unexpected content at {path}")


def main():
    current = STATE / "current"
    previous = current.readlink()
    sha = approved_commit()
    if sha is None:
        print("The current main commit has no successful push run for site.yml")
        return

    releases = STATE / "releases"
    releases.mkdir(exist_ok=True)
    release = releases / sha
    if previous == release:
        return

    with TemporaryDirectory(prefix="deploy-", dir=STATE) as directory:
        scratch = Path(directory)
        if not release.exists():
            staged = scratch / "site"
            staged.mkdir()
            unpack_release(sha, staged)
            staged.rename(release)

        if github_json("/branches/main")["commit"]["sha"] != sha:
            print("main changed while preparing the release")
            return

        switch_current(release, current, scratch)
        try:
            check_nginx(release)
        except Exception:
            switch_current(previous, current, scratch)
            raise

    print(f"Published CastorSteel commit {sha}")


if __name__ == "__main__":
    os.umask(0o022)
    main()
