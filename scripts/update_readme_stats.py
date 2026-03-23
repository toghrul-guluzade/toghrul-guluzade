# scripts/update_readme_stats.py
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

USERNAME = os.environ["GH_USERNAME"]
TOKEN = os.environ["GH_TOKEN"]
README = Path("README.md")

API = "https://api.github.com"


def gh_get(path: str):
    req = Request(
        API + path,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USERNAME,
        },
    )
    with urlopen(req) as r:
        return json.loads(r.read().decode())


def paged_get(path: str):
    page = 1
    all_items = []
    while True:
        sep = "&" if "?" in path else "?"
        items = gh_get(f"{path}{sep}per_page=100&page={page}")
        if not items:
            break
        all_items.extend(items)
        page += 1
    return all_items


def list_owned_repos():
    return paged_get(f"/users/{USERNAME}/repos?type=owner&sort=updated")


def list_contributed_repos():
    # Practical approximation:
    # search recent public events for PushEvent/PRs and collect repo names.
    # This is not perfect all-time coverage.
    events = paged_get(f"/users/{USERNAME}/events/public")
    repos = set()
    for e in events:
        repo = e.get("repo", {}).get("name")
        if repo:
            repos.add(repo)
    return sorted(repos)


def repo_languages(full_name: str):
    return gh_get(f"/repos/{full_name}/languages")


def clone_and_cloc(repo_full_name: str, temp_root: Path) -> int:
    repo_dir = temp_root / repo_full_name.replace("/", "__")
    url = f"https://github.com/{repo_full_name}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", url, str(repo_dir)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not repo_dir.exists():
        return 0

    result = subprocess.run(
        ["cloc", str(repo_dir), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return 0

    total = data.get("SUM", {}).get("code", 0)
    return int(total)


def main():
    owned = list_owned_repos()

    total_repos = len(owned)
    total_stars = sum(repo.get("stargazers_count", 0) for repo in owned)

    lang_bytes = {}
    owned_names = [r["full_name"] for r in owned]

    for full_name in owned_names:
        langs = repo_languages(full_name)
        for lang, count in langs.items():
            lang_bytes[lang] = lang_bytes.get(lang, 0) + count

    # Include contributed repos from public recent activity only.
    contributed = [r for r in list_contributed_repos() if r not in owned_names]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        total_loc = 0

        for full_name in owned_names:
            total_loc += clone_and_cloc(full_name, root)

        for full_name in contributed[:20]:
            total_loc += clone_and_cloc(full_name, root)
            langs = repo_languages(full_name)
            for lang, count in langs.items():
                lang_bytes[lang] = lang_bytes.get(lang, 0) + count

    top_langs = ", ".join(
        lang for lang, _ in sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)[:4]
    )

    text = README.read_text(encoding="utf-8")
    text = text.replace("__REPOS__", str(total_repos))
    text = text.replace("__STARS__", str(total_stars))
    text = text.replace("__LOC__", f"{total_loc:,}")
    text = text.replace("__LANGS__", top_langs or "N/A")
    README.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()