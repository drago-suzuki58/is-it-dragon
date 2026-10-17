# is-it-dragon

画像にドラゴンが含まれているかを [TypeSafe](https://docs.typesafe.ai/) の Jev 1.14 で判定します。判定する対象とプロンプトは `profiles/*.json` に置きます。

Discord Bot と、プロンプトと画像を試すための CLI（`lab`）があります。

## 導入

```sh
uv sync
```

`.env` に API キーと Bot のトークンを書きます。`lab` だけを使うなら `DISCORD_TOKEN` は不要です。

```sh
TYPESAFE_API_KEY=...
DISCORD_TOKEN=...
```

## Discord Bot

```sh
uv run --env-file .env is-it-dragon
```

- `/dragon url:<画像のURL>` または `/dragon image:<画像ファイル>`: URL の画像か、添付した画像を判定します。
- メッセージを右クリック（長押し）→「アプリ」→「ドラゴン判定」: そのメッセージの添付画像と、埋め込みの画像を判定します。転送されたメッセージでは、転送元の画像を判定します。1回に判定するのは先頭の4枚までです。
- 結果は Embed で返します。ドラゴンがいる確率が 80% 以上なら「ドラゴンがいます」、20% 以下なら「ドラゴンはいません」、その間は 50% を境に「たぶんドラゴンがいます」「たぶんドラゴンはいません」と表示します。あわせて、確率、モデル名、トークン数を表示します。
- 確率が 20% を超えるときは種類の確率分布と確信度を、80% 以上のときは位置（Box）の座標と確信度も表示します。種類は「ドラゴンだとしたらどの種類か」を答えたもので、ドラゴンがいるかどうかの判定には使っていません。
- メッセージから判定したときは、結果のタイトルが元のメッセージへのリンクになります。
- 「います」のときは、位置の枠を描いた画像を結果に添付し、Embed に表示します。この画像はチャンネルのメディア欄に載ります。
- スポイラー付きで添付された画像は、Embed にサムネイルも枠の画像も出しません。
- サーバーにもユーザーにもインストールできます。ユーザーにインストールした場合は、Bot がいないサーバーや DM でも使えます。
- コマンドは起動時に登録します。Discord Developer Portal の Installation で、Guild Install と User Install の両方を有効にしてください。
- URL で渡された画像は、http(s) の画像だけを取得します。内部ネットワーク宛ての URL は拒否します。

## lab

```sh
# 判定して、生の応答とトークン数・推定コストを表示する（ディレクトリを渡すと、その直下の画像をすべて判定する）
uv run --env-file .env lab try photo.jpg https://example.com/dragon.png images/

# 2つのプロファイルで同じ画像を比べる
uv run --env-file .env lab try photo.jpg -p dragon -p my-variant.json

# yes のとき、位置（Box）の枠を描いた画像を out/ に保存する
uv run --env-file .env lab try photo.jpg --box out/

# 送信するリクエスト本文を表示する（API は呼ばない）
uv run lab request photo.jpg

# 正規化後の画像を書き出す
uv run lab normalize anim.gif -o normalized.jpg
```

- `-p` にはプロファイル名（`profiles/` の中のファイル名）か、`.json` ファイルのパスを渡します。
- Bot と同じく、位置（Box）も同じリクエストで聞きます。
- 入力は並列に判定し、入力の順に表示します。同時に判定する数は `-j` で変えられます（既定: 4）。失敗した入力はエラーを表示して続け、1件でも失敗すると終了コード 1 で終わります。
- 応答は `.cache/lab/` にキャッシュされ、同じ画像とプロンプトで再実行しても API は呼ばれません。プロファイルの `questions` を変えると、その分は API を呼び直します。`--no-cache` を付けると、キャッシュを使わずに API を呼びます。
- 画像は PNG / JPEG の静止画に変換し、各辺を 280〜1568px に収めてから送ります。アニメーション画像は先頭フレームだけを使います。

## 制限

- Jev の画像入力は TypeSafe が「Dreamer-ready」としている段階の機能で、本番品質の扱いではありません。精度や API の形式が変わることがあります。
