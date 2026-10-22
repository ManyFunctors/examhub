# Crawling from India

Many Indian government hosts drop traffic from GitHub's datacenter ranges (about
half of the feeds that fail on the runner answer from an Indian address). The
fix that keeps everything on GitHub Actions is a self-hosted runner on a free VM
in India. `crawl`, `watch` and `probe-feeds` run on whatever the repository
variable `CRAWL_RUNNER` names, and on `ubuntu-24.04` when it is unset.

## One-time setup

1. Create an always-free VM in an Indian region (Oracle Cloud Always Free,
   Mumbai or Hyderabad; Ampere A1 with 2 OCPU / 12 GB is plenty; Ubuntu 24.04).
2. Repo Settings > Actions > Runners > New self-hosted runner: copy the
   registration token.
3. On the VM: `curl -fsSLO https://raw.githubusercontent.com/ManyFunctors/examhub/main/scripts/setup-india-runner.sh && bash setup-india-runner.sh <token>`
4. `gh variable set CRAWL_RUNNER --body examhub-india --repo ManyFunctors/examhub`

Run `probe-feeds` with a few feeds that failed before (for example
`in-kvs/notices,mz-mpsc/posts,in-coal-india/careers`) to confirm.

## If the runner is offline

Jobs wait for a runner that never comes, so the harvest stops. Unset the
variable (`gh variable delete CRAWL_RUNNER`) and the workflows fall back to
GitHub's runners at once.

## Not moved

`recheck`, `recheck-hourly`, `record`, `site` and `pr` stay on GitHub's runners:
they build the site and open pull requests, and need no Indian address.

## Safety

The three workflows that use this runner only start on a schedule or by hand, never from a pull request, so a fork cannot run code on the VM.

## Without a runner in India: the Internet Archive fallback

A feed whose host never answers the runner (timeout, refused or reset
connection, TLS failure) or answers 403/429/5xx is read from the Internet
Archive's latest capture instead (`web.archive.org/web/2id_/<url>`, the page as
served). With the repository secrets `IA_ACCESS_KEY` and `IA_SECRET_KEY` (a free
archive.org account, keys at archive.org/account/s3.php) the pipeline first
asks Save Page Now 2 for a fresh capture of any feed whose latest capture is a
day old or more, at most `EXAMHUB_WAYBACK_SAVES` (20) per run, and waits for it.
Without the keys it reads the latest capture as it is. (Anonymous Save Page Now
no longer works: "You need to be logged in".) archive.today has no API and
answers automated requests with a captcha, so it is not used. `EXAMHUB_WAYBACK=0` turns it off.

Such a feed is marked `via = "wayback"` in `feed-health.jsonl` with the capture
time and age. Its notices are added but never marked gone, because an archived
copy is old. Detail pages are not followed. A host the Archive has never
captured (or that blocks it too) stays empty.
