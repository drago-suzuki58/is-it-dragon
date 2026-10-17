# is-it-dragon 開発方針

## 構成と責務

- `src/is_it_dragon/core/`: 純粋関数だけを置く（I/O、乱数、時刻を使わない）。Chrome 拡張へ移植するときは、ここを TypeScript に書き直す。
- `src/is_it_dragon/adapters/`: 環境に依存する実装（Pillow、httpx、キャッシュ、描画）。core の `Normalizer`、`Transport`、`Cache` の形に合わせる。
- `src/is_it_dragon/judge.py`: core とアダプタを組み立てるだけにする。
- `src/is_it_dragon/apps/`: 入出力だけを書く。判定の手順を apps の中に重複して書かない。
- `profiles/*.json`: 判定対象とプロンプト。Bot、`lab`、将来の Chrome 拡張で同じファイルを共有する。
  - API に送るのは `questions` と `locate` だけ。表示名など API に送らない情報は `display` に置く。
  - `questions` の中に API が受け付けないキーを足さない。

## 判定の仕様

- モデルは `jev-1.14.0` に固定する（`core/request.py` の `MODEL`）。Box 質問は Jev 1.14 が必要。
- 画像は1枚1リクエストで送る。画像の参照キーは画像の SHA-256 から作り、同じ入力から同じリクエストができるようにする（キャッシュのキーにもなる）。
- 位置（Box）は判定と同じリクエストで聞く。料金は画像の入力トークンが大半なので、別リクエストにすると料金がほぼ倍になる。Box は対象がなくても必ず返るので、結果が yes のときだけ採用する。
- Box を同じリクエストに入れると、他の質問の答えがわずかに変わることがある。Bot と `lab` は同じ条件（`locate=True`、同じ `state.source`）で判定し、`lab` の結果が Bot の結果と一致するようにする。
- 結果は `p >= thresholds.yes` で yes、`p <= thresholds.no` で no、それ以外は unsure。
- 判定に使うのは `main` の Noul の p だけ。choice（種類）や Box は判定に使わない。
- choice の質問は対象がいる前提で答えるので、その確率分布や確信度は「対象がいる確率」ではない。結果が no のときは表示せず、unsure のときは前提（「ドラゴンだとしたら」）を見出しに書く。
- unsure は、表示だけ p が 0.5 以上なら「たぶんいます」、未満なら「たぶんいません」と言い分ける。
- キャッシュはリクエスト本文のハッシュをキーにして応答を保存する。プロンプトを変えると自動でキャッシュを外れる。

## 画像の制約（Jev）

- PNG / JPEG の静止画、各辺 280〜1568px、1枚 16MiB、リクエスト全体 32MiB。範囲外は自動で縮小されず、リクエストごと拒否される。
- EXIF の回転は API 側で適用されないので、画素を回転してから送る。
- 正規化は、短辺 280px 未満の画像だけを 280px まで拡大する。それ以上には拡大しない（大きく拡大すると判定が悪化した）。
- 画像入力は TypeSafe が「Dreamer-ready」とする段階の機能で、同じ絵でも解像度や質問の組み合わせで p が大きく動く。プロンプトや閾値を変えるときは、`lab` で複数の画像を比べてから決める。

## Discord Bot

- インタラクションだけを扱い、Gateway Intents は使わない（Message Content Intent も不要）。
- 3秒以内に defer し、結果は followup で返す。
- 添付の CDN URL は署名付きで失効するので、受け取ったその場でダウンロードする。
- URL から画像を取るときは `adapters/fetch_image.py` を使う（http(s) のみ、サイズ上限、Content-Type の確認、内部アドレスの拒否）。
- スポイラーの添付は、Embed にぼかしなしで出てしまうので、サムネイルも枠の画像も出さない。
- ユーザーに見せるメッセージは日本語にする。

## 検証

- 変更後は `uv run pytest` と `uv run ruff check .`、`uv run ruff format --check .` を通す。
- 単体テストは API を呼ばない。API を使う確認は `uv run --env-file .env lab try ...` で行う。
- テスト用の画像や検証の出力は `.dev/` に置き、リポジトリに含めない。
