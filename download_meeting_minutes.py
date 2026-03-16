#!/usr/bin/env python3
"""
Cybozu Garoon ファイル管理 - チーフ会議議事録ダウンローダー

対象URL: https://kondakaikei.cybozu.com/o/ag.cgi?page=FileIndex&gid=&fCID=561442
「チーフ会議議事録」または「ﾁｰﾌ会議議事録」を含むファイルをすべてダウンロードします。
"""

import os
import re
import sys
import time
import getpass
import argparse
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlencode, parse_qs, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("必要なライブラリをインストールしてください:")
    print("  pip install requests beautifulsoup4")
    sys.exit(1)

BASE_URL = "https://kondakaikei.cybozu.com"
FILE_INDEX_URL = f"{BASE_URL}/o/ag.cgi?page=FileIndex&gid=&fCID=561442"
LOGIN_URL = f"{BASE_URL}/o/ac.cgi"

# 検索キーワード（全角・半角カタカナ両方対応）
KEYWORDS = ["チーフ会議議事録", "ﾁｰﾌ会議議事録"]

OUTPUT_DIR = Path("downloaded_minutes")


def normalize_text(text: str) -> str:
    """全角・半角カタカナを統一して比較するために正規化"""
    return unicodedata.normalize("NFKC", text)


def contains_keyword(text: str) -> bool:
    """テキストがキーワードを含むか確認（正規化後に比較）"""
    normalized = normalize_text(text)
    for kw in KEYWORDS:
        if normalize_text(kw) in normalized:
            return True
    return False


def login(session: requests.Session, username: str, password: str) -> bool:
    """Cybozu Garoon にログイン"""
    print(f"ログイン中: {username}")
    payload = {
        "_ID": username,
        "Password": password,
        "submit": "ログイン",
    }
    try:
        resp = session.post(LOGIN_URL, data=payload, allow_redirects=True, timeout=30)
        resp.raise_for_status()
        # ログイン失敗の確認（ログインページに戻っていないか）
        if "Password" in resp.text and "ログイン" in resp.text and resp.url == LOGIN_URL:
            print("ログイン失敗: ユーザー名またはパスワードが間違っています。")
            return False
        print("ログイン成功")
        return True
    except requests.RequestException as e:
        print(f"ログインエラー: {e}")
        return False


def get_all_files(session: requests.Session) -> list[dict]:
    """ファイル一覧ページから全ファイル情報を取得（ページネーション対応）"""
    files = []
    url = FILE_INDEX_URL
    page_num = 1

    while url:
        print(f"ファイル一覧取得中 (ページ {page_num}): {url}")
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"ページ取得エラー: {e}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        page_files = parse_file_list(soup, resp.url)
        files.extend(page_files)
        print(f"  → {len(page_files)} 件取得")

        # 次のページへのリンクを探す
        url = find_next_page_url(soup, resp.url)
        page_num += 1

    return files


def parse_file_list(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """HTMLからファイル情報を解析"""
    files = []

    # Cybozu Garoon のファイル一覧テーブルを解析
    # ファイル行を探す（複数のセレクタを試みる）
    rows = (
        soup.select("tr.filerow")
        or soup.select("table.vr_FileList tr")
        or soup.select("tr[id^='file']")
        or soup.select(".fileListItem")
    )

    if not rows:
        # テーブル全体からすべての行を検索
        all_rows = soup.select("table tr")
        for row in all_rows:
            file_info = extract_file_from_row(row, base_url)
            if file_info:
                files.append(file_info)
    else:
        for row in rows:
            file_info = extract_file_from_row(row, base_url)
            if file_info:
                files.append(file_info)

    # 添付ファイルへの直接リンクを探す（別パターン）
    if not files:
        files = extract_files_by_links(soup, base_url)

    return files


def extract_file_from_row(row, base_url: str) -> dict | None:
    """テーブル行からファイル情報を抽出"""
    # ダウンロードリンクを探す
    download_link = (
        row.find("a", href=re.compile(r"page=FileGet|page=FilesGet|FileDownload"))
        or row.find("a", href=re.compile(r"fID=|fileId="))
        or row.find("a", class_=re.compile(r"download|file"))
    )

    if not download_link:
        return None

    href = download_link.get("href", "")
    if not href:
        return None

    # ファイル名を取得（リンクテキスト、title属性、またはalt属性から）
    file_name = (
        row.find("td", class_=re.compile(r"fileName|name|title"))
        or row.find("span", class_=re.compile(r"fileName|name"))
    )
    if file_name:
        name = file_name.get_text(strip=True)
    else:
        # 行内のテキストを結合
        name = row.get_text(separator=" ", strip=True)

    download_url = urljoin(base_url, href)

    return {
        "name": name,
        "url": download_url,
        "row_text": row.get_text(separator=" ", strip=True),
    }


def extract_files_by_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """リンクからファイル情報を直接抽出"""
    files = []
    seen_urls = set()

    # ダウンロード関連のリンクをすべて探す
    links = soup.find_all(
        "a",
        href=re.compile(r"(page=FileGet|page=FilesGet|fID=|FileDownload)", re.I),
    )

    for link in links:
        href = link.get("href", "")
        if not href or href in seen_urls:
            continue
        seen_urls.add(href)

        download_url = urljoin(base_url, href)
        # リンクの周辺テキストを取得
        parent = link.find_parent("tr") or link.find_parent("div") or link.parent
        row_text = parent.get_text(separator=" ", strip=True) if parent else link.get_text(strip=True)
        name = link.get_text(strip=True) or link.get("title", "") or href

        files.append({
            "name": name,
            "url": download_url,
            "row_text": row_text,
        })

    return files


def find_next_page_url(soup: BeautifulSoup, current_url: str) -> str | None:
    """ページネーションの「次へ」リンクを取得"""
    next_link = (
        soup.find("a", string=re.compile(r"次[のへ]|next|›|»", re.I))
        or soup.find("a", title=re.compile(r"次[のへ]|next", re.I))
        or soup.find("a", class_=re.compile(r"next|pagination-next", re.I))
    )
    if next_link:
        href = next_link.get("href", "")
        if href:
            return urljoin(current_url, href)
    return None


def download_file(session: requests.Session, file_info: dict, output_dir: Path) -> bool:
    """ファイルをダウンロードして保存"""
    url = file_info["url"]
    suggested_name = file_info.get("name", "unknown")

    try:
        resp = session.get(url, stream=True, timeout=60)
        resp.raise_for_status()

        # Content-Disposition からファイル名を取得
        content_disposition = resp.headers.get("Content-Disposition", "")
        filename = extract_filename_from_header(content_disposition) or sanitize_filename(suggested_name)

        if not filename or filename in (".", ".."):
            # URLからファイル名を推測
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            fid = params.get("fID", params.get("fileId", ["unknown"]))[0]
            filename = f"file_{fid}"

        filepath = output_dir / filename
        # 同名ファイルが存在する場合は番号を付ける
        if filepath.exists():
            stem = filepath.stem
            suffix = filepath.suffix
            counter = 1
            while filepath.exists():
                filepath = output_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        size_kb = filepath.stat().st_size / 1024
        print(f"  ✓ 保存: {filepath.name} ({size_kb:.1f} KB)")
        return True

    except requests.RequestException as e:
        print(f"  ✗ ダウンロード失敗 [{url}]: {e}")
        return False


def extract_filename_from_header(content_disposition: str) -> str:
    """Content-Disposition ヘッダーからファイル名を抽出"""
    if not content_disposition:
        return ""

    # RFC 5987 形式 (filename*=UTF-8''...)
    match = re.search(r"filename\*=(?:UTF-8'')?(.+?)(?:;|$)", content_disposition, re.I)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1).strip().strip('"'))

    # 通常形式 (filename="...")
    match = re.search(r'filename=["\']?([^"\';\n]+)["\']?', content_disposition, re.I)
    if match:
        name = match.group(1).strip()
        # エンコードされた日本語ファイル名のデコード
        try:
            return name.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return name

    return ""


def sanitize_filename(name: str) -> str:
    """ファイル名として使用できない文字を除去"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip(". ")
    return name[:200] if name else "unknown"


def main():
    parser = argparse.ArgumentParser(
        description="Cybozu Garoon からチーフ会議議事録をダウンロード"
    )
    parser.add_argument("-u", "--username", help="ログインユーザー名")
    parser.add_argument("-p", "--password", help="ログインパスワード")
    parser.add_argument(
        "--cookie",
        help="セッションCookie (例: 'CBSESSID=xxxx; CBTOKEN=yyyy')\n"
             "ブラウザの開発者ツール → Application → Cookies から取得",
    )
    parser.add_argument(
        "-o", "--output", default=str(OUTPUT_DIR), help="出力ディレクトリ (デフォルト: downloaded_minutes)"
    )
    parser.add_argument(
        "--all", action="store_true", help="キーワードフィルタなしで全ファイルをダウンロード"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="ダウンロードせずに対象ファイルの一覧のみ表示"
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
    })

    # 認証方法の選択
    if args.cookie:
        # Cookie を直接設定
        print("Cookie でセッションを設定中...")
        for cookie_str in args.cookie.split(";"):
            cookie_str = cookie_str.strip()
            if "=" in cookie_str:
                name, value = cookie_str.split("=", 1)
                session.cookies.set(name.strip(), value.strip(), domain="kondakaikei.cybozu.com")
        print("Cookie 設定完了")
    else:
        # ユーザー名/パスワードでログイン
        username = args.username or input("ユーザー名: ")
        password = args.password or getpass.getpass("パスワード: ")
        if not login(session, username, password):
            sys.exit(1)

    # ファイル一覧取得
    print(f"\nファイル一覧を取得中: {FILE_INDEX_URL}")
    all_files = get_all_files(session)
    print(f"\n合計 {len(all_files)} 件のファイルを検出")

    if not all_files:
        print("\n警告: ファイルが見つかりませんでした。")
        print("考えられる原因:")
        print("  1. 認証に失敗している（Cookie が期限切れ、またはパスワードが間違い）")
        print("  2. ページの HTML 構造が想定と異なる")
        print("  3. アクセス権限がない")
        sys.exit(1)

    # キーワードでフィルタリング
    if args.all:
        target_files = all_files
        print("全ファイルをダウンロード対象とします")
    else:
        target_files = [
            f for f in all_files
            if contains_keyword(f["name"]) or contains_keyword(f["row_text"])
        ]
        print(f"\nキーワード「チーフ会議議事録」に該当: {len(target_files)} 件")

    if not target_files:
        print("\n対象ファイルが見つかりませんでした。")
        print("--all オプションで全ファイルを確認できます。")
        sys.exit(0)

    print("\n--- 対象ファイル一覧 ---")
    for i, f in enumerate(target_files, 1):
        print(f"  {i:3d}. {f['name']}")
        print(f"       URL: {f['url']}")

    if args.dry_run:
        print("\n[dry-run] ダウンロードはスキップしました。")
        sys.exit(0)

    # ダウンロード
    print(f"\nダウンロード開始 → {output_dir}/")
    success_count = 0
    fail_count = 0
    for i, file_info in enumerate(target_files, 1):
        print(f"\n[{i}/{len(target_files)}] {file_info['name']}")
        if download_file(session, file_info, output_dir):
            success_count += 1
        else:
            fail_count += 1
        time.sleep(0.5)  # サーバー負荷軽減

    print(f"\n完了: 成功 {success_count} 件, 失敗 {fail_count} 件")
    print(f"保存先: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
