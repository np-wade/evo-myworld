# Scrapler Eval — all-registered

| provenance | value |
| --- | --- |
| bracket | all-registered |
| candidates | 3 |
| tasks | 4 |
| git_sha | `bae27cfb4fa8597cda198d2d0d8a043ec97d200a` |
| git_dirty | yes |
| host | WadeYoga |
| python | 3.14.4 |
| platform | Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.43 |
| utc | 2026-07-25T21:41:36.557955+00:00 |
| ts | 1785015696.557955 |

<!-- 2026-07-25T21:41:36.557955+00:00 sha=bae27cf(dirty) host=WadeYoga py=3.14.4 Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.43 -->


# Race result: all-registered

## Overall leaderboard

| # | candidate | class | normalized | leaderboard | elo | gate% | n |
|---|---|---|---|---|---|---|---|
| 1 | raw-fetch-baseline 🏆 | 1 | 98.55 | 0.8435 | 1000.0 | 100.0 | 3 |
| 2 | json-blob-extractor | 4 | 70.00 | 0.7150 | 1016.0 | 100.0 | 1 |
| 3 | regex-article-extractor | 4 | 0.00 | 0.4000 | 984.0 | 0.0 | 1 |


## Weight class 1

| # | candidate | class | normalized | leaderboard | elo | gate% | n |
|---|---|---|---|---|---|---|---|
| 1 | raw-fetch-baseline 🏆 | 1 | 98.55 | 0.8435 | 1000.0 | 100.0 | 3 |


## Weight class 4

| # | candidate | class | normalized | leaderboard | elo | gate% | n |
|---|---|---|---|---|---|---|---|
| 1 | json-blob-extractor 🏆 | 4 | 70.00 | 0.7150 | 1016.0 | 100.0 | 1 |
| 2 | regex-article-extractor | 4 | 0.00 | 0.4000 | 984.0 | 0.0 | 1 |


## Why candidates lost

### Why candidates lost

| signature | count | candidates hit | example task |
| --- | ---: | --- | --- |
| error:retrieved_content: retrieved 45 chars < min 100 | 1 | regex-article-extractor | x-product-fields |