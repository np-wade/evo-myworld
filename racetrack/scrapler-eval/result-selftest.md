# Scrapler Eval — all-registered

| provenance | value |
| --- | --- |
| bracket | all-registered |
| candidates | 9 |
| tasks | 4 |
| git_sha | `26c9a16f82bc7e5eb3044905989f4cae7cb29296` |
| git_dirty | yes |
| host | WadeYoga |
| python | 3.14.4 |
| platform | Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.43 |
| utc | 2026-07-25T21:51:24.626992+00:00 |
| ts | 1785016284.626992 |

<!-- 2026-07-25T21:51:24.626992+00:00 sha=26c9a16(dirty) host=WadeYoga py=3.14.4 Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.43 -->


# Race result: all-registered

## Overall leaderboard

| # | candidate | class | normalized | leaderboard | elo | gate% | n |
|---|---|---|---|---|---|---|---|
| 1 | raw-fetch-baseline 🏆 | 1 | 98.55 | 0.8435 | 1058.3 | 100.0 | 3 |
| 2 | adaptive-selfheal | 4 | 70.00 | 0.7150 | 1045.8 | 100.0 | 1 |
| 3 | css-json | 4 | 70.00 | 0.7150 | 1043.8 | 100.0 | 1 |
| 4 | json-blob-extractor | 4 | 70.00 | 0.7150 | 1041.9 | 100.0 | 1 |
| 5 | curl-impersonate | 1 | 67.56 | 0.7040 | 971.5 | 33.3 | 3 |
| 6 | scrapling-static | 1 | 67.56 | 0.7040 | 970.2 | 33.3 | 3 |
| 7 | trafilatura-article | 4 | 0.00 | 0.4000 | 957.8 | 100.0 | 1 |
| 8 | regex-article-extractor | 4 | 0.00 | 0.4000 | 956.2 | 0.0 | 1 |
| 9 | llm-extract | 4 | 0.00 | -0.1500 | 954.4 | 0.0 | 1 |


## Weight class 1

| # | candidate | class | normalized | leaderboard | elo | gate% | n |
|---|---|---|---|---|---|---|---|
| 1 | raw-fetch-baseline 🏆 | 1 | 98.55 | 0.8435 | 1058.3 | 100.0 | 3 |
| 2 | curl-impersonate | 1 | 67.56 | 0.7040 | 971.5 | 33.3 | 3 |
| 3 | scrapling-static | 1 | 67.56 | 0.7040 | 970.2 | 33.3 | 3 |


## Weight class 4

| # | candidate | class | normalized | leaderboard | elo | gate% | n |
|---|---|---|---|---|---|---|---|
| 1 | adaptive-selfheal 🏆 | 4 | 70.00 | 0.7150 | 1045.8 | 100.0 | 1 |
| 2 | css-json | 4 | 70.00 | 0.7150 | 1043.8 | 100.0 | 1 |
| 3 | json-blob-extractor | 4 | 70.00 | 0.7150 | 1041.9 | 100.0 | 1 |
| 4 | trafilatura-article | 4 | 0.00 | 0.4000 | 957.8 | 100.0 | 1 |
| 5 | regex-article-extractor | 4 | 0.00 | 0.4000 | 956.2 | 0.0 | 1 |
| 6 | llm-extract | 4 | 0.00 | -0.1500 | 954.4 | 0.0 | 1 |


## Why candidates lost

### Why candidates lost

| signature | count | candidates hit | example task |
| --- | ---: | --- | --- |
| error:retrieved_content: retrieved 58 chars < min 100 | 2 | curl-impersonate, scrapling-static | t1-product |
| error:retrieved_content: retrieved 63 chars < min 100 | 2 | curl-impersonate, scrapling-static | t2-lazyfeed |
| error:retrieved_content: retrieved 45 chars < min 100 | 1 | regex-article-extractor | x-product-fields |
| error:unavailable: missing deps | 1 | llm-extract | x-product-fields |
| low_quality:completeness | 1 | trafilatura-article | x-product-fields |