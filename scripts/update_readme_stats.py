import json
import os
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
    # Authenticated endpoint: includes your private repos too
    repos = paged_get("/user/repos?affiliation=owner&sort=updated")
    return repos


def list_contributed_repos():
    # Practical approximation from recent public activity
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

    # Authenticated clone URL so private repos you own can be cloned
    url = f"https://x-access-token:{TOKEN}@github.com/{repo_full_name}.git"

    clone_result = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(repo_dir)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if clone_result.returncode != 0 or not repo_dir.exists():
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

    return int(data.get("SUM", {}).get("code", 0))


def format_top_languages(lang_bytes: dict, top_n: int = 4) -> str:
    if not lang_bytes:
        return "N/A"

    sorted_langs = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)
    top_langs = [lang for lang, _ in sorted_langs[:top_n]]
    return ", ".join(top_langs)


def replace_marker_line(text: str, label: str, value: str) -> str:
    lines = text.splitlines()
    new_lines = []

    prefix = f"{label}"
    for line in lines:
        if prefix in line:
            left, sep, right = line.partition(prefix)
            if sep:
                rebuilt = left + prefix + value
                if line.endswith("│"):
                    width = len(line) - 1
                    rebuilt = rebuilt[:width].ljust(width) + "│"
                line = rebuilt
        new_lines.append(line)

    return "\n".join(new_lines) + "\n"


def main():
    owned = list_owned_repos()

    total_repos = len(owned)
    total_stars = sum(repo.get("stargazers_count", 0) for repo in owned)

    lang_bytes = {}
    owned_names = [repo["full_name"] for repo in owned]

    for full_name in owned_names:
        try:
            langs = repo_languages(full_name)
            for lang, count in langs.items():
                lang_bytes[lang] = lang_bytes.get(lang, 0) + count
        except Exception:
            continue

    # Recent public contributed repos not already owned by you
    contributed = [r for r in list_contributed_repos() if r not in owned_names]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        total_loc = 0

        # Count LOC for your owned repos
        for full_name in owned_names:
            total_loc += clone_and_cloc(full_name, root)

        # Count a limited number of recent public contributed repos
        for full_name in contributed[:10]:
            total_loc += clone_and_cloc(full_name, root)
            try:
                langs = repo_languages(full_name)
                for lang, count in langs.items():
                    lang_bytes[lang] = lang_bytes.get(lang, 0) + count
            except Exception:
                continue

    top_langs = format_top_languages(lang_bytes, top_n=4)

    text = README.read_text(encoding="utf-8")

    # Simple exact marker replacement
    text = text.replace("__REPOS__", str(total_repos))
    text = text.replace("__STARS__", str(total_stars))
    text = text.replace("__LOC__", f"{total_loc:,}")
    text = text.replace("__LANGS__", top_langs)

    README.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
