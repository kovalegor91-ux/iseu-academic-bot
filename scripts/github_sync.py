import os
import sys
import base64
import json
from pathlib import Path
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_PATTERNS = [
    ".env",
    "__pycache__",
    ".pyc",
    "output/Test_",
    "output/images/img_",
    "output/test_images",
    "sessions/session_",
    ".git"
]

def should_include(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    for exc in EXCLUDE_PATTERNS:
        if exc in norm:
            return False
    return True

def push_project_to_github(github_token: str, repo_name: str = "iseu-academic-bot", is_private: bool = False):
    headers = {
        "Authorization": f"Bearer {github_token.strip()}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    # 1. Get authenticated user
    print("Проверяю токен GitHub...")
    user_resp = requests.get("https://api.github.com/user", headers=headers)
    if user_resp.status_code != 200:
        raise ValueError(f"Не удалось авторизоваться в GitHub. HTTP {user_resp.status_code}: {user_resp.text}")

    user_info = user_resp.json()
    username = user_info.get("login")
    print(f"Авторизован как: {username}")

    # 2. Check or create repo
    print(f"Проверяю наличие репозитория '{repo_name}'...")
    repo_url = f"https://api.github.com/repos/{username}/{repo_name}"
    check_repo = requests.get(repo_url, headers=headers)

    if check_repo.status_code == 404:
        print(f"Создаю новый репозиторий '{repo_name}' на GitHub...")
        create_payload = {
            "name": repo_name,
            "description": "Telegram-бот для генерации рефератов и презентаций по стандартам МГЭИ им. А.Д. Сахарова БГУ",
            "private": is_private,
            "auto_init": False
        }
        create_resp = requests.post("https://api.github.com/user/repos", headers=headers, json=create_payload)
        if create_resp.status_code not in (200, 201):
            raise ValueError(f"Не удалось создать репозиторий: {create_resp.text}")
        print(f"Репозиторий '{repo_name}' успешно создан!")
    elif check_repo.status_code == 200:
        print(f"Репозиторий '{repo_name}' уже существует, загружаю файлы в него...")
    else:
        raise ValueError(f"Ошибка проверки репозитория: {check_repo.text}")

    # 3. Collect files
    files_to_upload = []
    for file_path in PROJECT_ROOT.rglob("*"):
        if file_path.is_file():
            rel_str = str(file_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            if should_include(rel_str):
                files_to_upload.append((file_path, rel_str))

    print(f"Подготовлено {len(files_to_upload)} файлов для загрузки на GitHub.")

    # 4. Upload blobs
    tree_items = []
    for fpath, rel_path in files_to_upload:
        try:
            with open(fpath, "rb") as f:
                content = f.read()
            b64_content = base64.b64encode(content).decode("utf-8")
            blob_resp = requests.post(
                f"https://api.github.com/repos/{username}/{repo_name}/git/blobs",
                headers=headers,
                json={"content": b64_content, "encoding": "base64"}
            )
            if blob_resp.status_code not in (200, 201):
                print(f"Ошибка загрузки blob для {rel_path}: {blob_resp.text}")
                continue
            sha = blob_resp.json().get("sha")
            tree_items.append({
                "path": rel_path,
                "mode": "100644",
                "type": "blob",
                "sha": sha
            })
            print(f"  + {rel_path}")
        except Exception as e:
            print(f"Ошибка при обработке {rel_path}: {e}")

    # 5. Create Tree
    print("Создаю дерево файлов...")
    tree_resp = requests.post(
        f"https://api.github.com/repos/{username}/{repo_name}/git/trees",
        headers=headers,
        json={"tree": tree_items}
    )
    if tree_resp.status_code not in (200, 201):
        raise ValueError(f"Ошибка создания дерева: {tree_resp.text}")
    tree_sha = tree_resp.json().get("sha")

    # 6. Check existing branch ref for parent commit
    parent_commits = []
    ref_url = f"https://api.github.com/repos/{username}/{repo_name}/git/refs/heads/main"
    ref_resp = requests.get(ref_url, headers=headers)
    if ref_resp.status_code == 200:
        parent_commits.append(ref_resp.json().get("object", {}).get("sha"))

    # 7. Create Commit
    print("Создаю коммит...")
    commit_payload = {
        "message": "Deploy ISEU Academic Bot with WebApp and Render.com support",
        "tree": tree_sha,
        "parents": parent_commits
    }
    commit_resp = requests.post(
        f"https://api.github.com/repos/{username}/{repo_name}/git/commits",
        headers=headers,
        json=commit_payload
    )
    if commit_resp.status_code not in (200, 201):
        raise ValueError(f"Ошибка создания коммита: {commit_resp.text}")
    commit_sha = commit_resp.json().get("sha")

    # 8. Update or Create Ref 'refs/heads/main'
    print("Обновляю ветку 'main'...")
    if parent_commits:
        update_ref = requests.patch(
            ref_url,
            headers=headers,
            json={"sha": commit_sha, "force": True}
        )
    else:
        update_ref = requests.post(
            f"https://api.github.com/repos/{username}/{repo_name}/git/refs",
            headers=headers,
            json={"ref": "refs/heads/main", "sha": commit_sha}
        )

    if update_ref.status_code not in (200, 201):
        raise ValueError(f"Ошибка обновления ветки: {update_ref.text}")

    github_repo_html = f"https://github.com/{username}/{repo_name}"
    print(f"\n🎉 ВСЕ ФАЙЛЫ УСПЕШНО ЗАГРУЖЕНЫ В GITHUB: {github_repo_html}")
    return github_repo_html

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python github_sync.py <GITHUB_TOKEN> [repo_name]")
        sys.exit(1)
    tok = sys.argv[1]
    rname = sys.argv[2] if len(sys.argv) > 2 else "iseu-academic-bot"
    push_project_to_github(tok, rname)
