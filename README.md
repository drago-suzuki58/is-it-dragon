# is-it-dragon

画像にドラゴンが含まれているかを [TypeSafe](https://docs.typesafe.ai/) の Jev 1.14 で判定します。判定する対象とプロンプトは `profiles/*.json` に置きます。

現在使えるのは、プロンプトと画像を試すための CLI（`lab`）です。Discord Bot はまだありません。

## 導入

```sh
uv sync
echo 'TYPESAFE_API_KEY=...' > .env
```

## lab

```sh
# 判定して、生の応答とトークン数・推定コストを表示する
uv run --env-file .env lab try photo.jpg https://example.com/dragon.png

# 2つのプロファイルで同じ画像を比べる
uv run --env-file .env lab try photo.jpg -p dragon -p my-variant.json

# 位置（Box）も聞き、yes のとき枠を描いた画像を out/ に保存する
uv run --env-file .env lab try photo.jpg --box out/

# 送信するリクエスト本文を表示する（API は呼ばない）
uv run lab request photo.jpg

# 正規化後の画像を書き出す
uv run lab normalize anim.gif -o normalized.jpg
```

- `-p` にはプロファイル名（`profiles/` の中のファイル名）か、`.json` ファイルのパスを渡します。
- 応答は `.cache/lab/` にキャッシュされ、同じ画像とプロンプトで再実行しても API は呼ばれません。プロファイルの `questions` を変えると、その分は API を呼び直します。`--no-cache` を付けると、キャッシュを使わずに API を呼びます。
- 画像は PNG / JPEG の静止画に変換し、各辺を 280〜1568px に収めてから送ります。アニメーション画像は先頭フレームだけを使います。

## 制限

- Jev の画像入力は TypeSafe が「Dreamer-ready」としている段階の機能で、本番品質の扱いではありません。精度や API の形式が変わることがあります。
