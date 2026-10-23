#!/usr/bin/env bash
# Tailwind CSS 재생성: 고정 버전 standalone CLI를 .cache/에 받아 해시 검증 후 빌드
set -euo pipefail

VERSION="v3.4.17"
cd "$(dirname "$0")/.."

case "$(uname -s)-$(uname -m)" in
    Linux-x86_64)
        ASSET="linux-x64"
        SHA256="7d24f7fa191d2193b78cd5f5a42a6093e14409521908529f42d80b11fde1f1d4"
        ;;
    Linux-aarch64 | Linux-arm64)
        ASSET="linux-arm64"
        SHA256="69b1378b8133192d7d2feb12a116fa12d035594f58db3eff215879e4ad8cf39b"
        ;;
    Darwin-arm64)
        ASSET="macos-arm64"
        SHA256="a1d0c7985759accca0bf12e51ac1dcbf0f6cf2fffb62e6e0f62d091c477a10a3"
        ;;
    Darwin-x86_64)
        ASSET="macos-x64"
        SHA256="6cbdad74be776c087ffa5e9a057512c54898f9fe8828d3362212dfe32fc933a3"
        ;;
    *)
        echo "지원하지 않는 플랫폼: $(uname -s)-$(uname -m)" >&2
        exit 1
        ;;
esac

BIN=".cache/tailwindcss-${VERSION}-${ASSET}"
if [ ! -x "$BIN" ]; then
    mkdir -p .cache
    curl -fsSL -o "$BIN.tmp" \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/${VERSION}/tailwindcss-${ASSET}"
    echo "${SHA256}  $BIN.tmp" | sha256sum -c - >/dev/null || {
        echo "sha256 불일치: $BIN.tmp" >&2
        rm -f "$BIN.tmp"
        exit 1
    }
    chmod +x "$BIN.tmp"
    mv "$BIN.tmp" "$BIN"
fi

"$BIN" -c tailwind.config.js -i app/static/css/input.css \
    -o app/static/css/tailwind.css --minify
