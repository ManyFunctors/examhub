#!/usr/bin/env bash
# Turn a fresh Ubuntu 24.04 VM (x86_64 or arm64) in India into a GitHub Actions
# runner for the crawl, watch and probe-feeds workflows. See docs/self-hosted-runner.md.
#
#   ./setup-india-runner.sh <registration-token>
#
# The token comes from Settings > Actions > Runners > New self-hosted runner
# (it is valid for one hour and is used once here, then dropped).
set -euo pipefail

REPO="ManyFunctors/examhub"
LABEL="examhub-india"
TOKEN="${1:?usage: $0 <registration-token>}"
case "$(uname -m)" in
  x86_64) RARCH=x64; GARCH=linux64 ;;
  aarch64) RARCH=arm64; GARCH=linux-aarch64 ;;
  *) echo "unsupported CPU $(uname -m)"; exit 1 ;;
esac

sudo apt-get update -qq
sudo apt-get install -y -qq git curl jq ca-certificates xz-utils \
  tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-mar tesseract-ocr-ben \
  tesseract-ocr-guj tesseract-ocr-kan tesseract-ocr-mal tesseract-ocr-ori tesseract-ocr-pan \
  tesseract-ocr-tam tesseract-ocr-tel tesseract-ocr-asm tesseract-ocr-urd

# Firefox from Mozilla's apt repo (Ubuntu's own package is a snap, which headless
# selenium cannot drive).
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://packages.mozilla.org/apt/repo-signing-key.gpg | sudo tee /etc/apt/keyrings/packages.mozilla.org.asc >/dev/null
echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" | sudo tee /etc/apt/sources.list.d/mozilla.list >/dev/null
printf 'Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' | sudo tee /etc/apt/preferences.d/mozilla >/dev/null
sudo apt-get update -qq
sudo apt-get install -y -qq firefox

# geckodriver, where settings.py looks for it ($GECKOWEBDRIVER).
GECKO_VERSION="$(curl -fsSL https://api.github.com/repos/mozilla/geckodriver/releases/latest | jq -r .tag_name)"
sudo install -d /opt/geckodriver
curl -fsSL "https://github.com/mozilla/geckodriver/releases/download/${GECKO_VERSION}/geckodriver-${GECKO_VERSION}-${GARCH}.tar.gz" \
  | sudo tar -xz -C /opt/geckodriver

# The Actions runner itself.
mkdir -p "$HOME/actions-runner" && cd "$HOME/actions-runner"
RUNNER_VERSION="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name | sed 's/^v//')"
curl -fsSL "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RARCH}-${RUNNER_VERSION}.tar.gz" | tar -xz
printf 'GECKOWEBDRIVER=/opt/geckodriver\nMOZ_HEADLESS=1\n' >> .env
./config.sh --unattended --url "https://github.com/${REPO}" --token "$TOKEN" \
  --name "india-$(hostname)" --labels "$LABEL" --replace
sudo ./svc.sh install
sudo ./svc.sh start

echo
echo "Runner registered. In the repo, set the Actions variable CRAWL_RUNNER to: $LABEL"
echo "  gh variable set CRAWL_RUNNER --body $LABEL --repo $REPO"
