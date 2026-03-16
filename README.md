# チーフ会議議事録ダウンローダー

Cybozu Garoon のファイル管理ページから「チーフ会議議事録」を含むファイルをすべてダウンロードします。

**対象URL:** `https://kondakaikei.cybozu.com/o/ag.cgi?page=FileIndex&gid=&fCID=561442`

## セットアップ

```bash
pip install requests beautifulsoup4
```

## 使い方

### 方法1: Cookie を使う（推奨）

すでにブラウザでログイン済みの場合、Cookie を使うと簡単です。

1. ブラウザで対象ページを開く
2. 開発者ツール（F12）→ Application → Cookies → `kondakaikei.cybozu.com`
3. `CBSESSID` などのセッション Cookie の値をコピー

```bash
python download_meeting_minutes.py --cookie "CBSESSID=xxxxxxxx; CBTOKEN=yyyyyyyy"
```

### 方法2: ユーザー名・パスワードでログイン

```bash
python download_meeting_minutes.py -u <ユーザー名> -p <パスワード>
```

パスワードを引数に渡したくない場合は省略するとプロンプトが表示されます:

```bash
python download_meeting_minutes.py -u <ユーザー名>
```

## オプション

| オプション | 説明 |
|-----------|------|
| `-u`, `--username` | ログインユーザー名 |
| `-p`, `--password` | ログインパスワード |
| `--cookie` | セッションCookie文字列 |
| `-o`, `--output` | 保存先ディレクトリ（デフォルト: `downloaded_minutes`） |
| `--dry-run` | ダウンロードせずに対象ファイルの一覧のみ表示 |
| `--all` | キーワードフィルタなしで全ファイルをダウンロード |

## 使用例

```bash
# まず対象ファイルを確認（ダウンロードなし）
python download_meeting_minutes.py --cookie "CBSESSID=xxxx" --dry-run

# ダウンロード実行
python download_meeting_minutes.py --cookie "CBSESSID=xxxx"

# 保存先を指定
python download_meeting_minutes.py --cookie "CBSESSID=xxxx" -o ./議事録
```

## 検索キーワード

- `チーフ会議議事録`（全角）
- `ﾁｰﾌ会議議事録`（半角カタカナ）

全角・半角カタカナは正規化して統一比較されるため、混在していても正しく検出されます。

## ダウンロードされるファイルの保存先

デフォルトでは `downloaded_minutes/` ディレクトリに保存されます。
同名ファイルが存在する場合は `filename_1.pdf` のように連番が付きます。
