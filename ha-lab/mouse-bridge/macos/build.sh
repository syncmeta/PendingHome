#!/bin/bash
# 编译 mouse-source。用系统自带的 Swift，不需要装任何东西。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
swiftc -O -o mouse-source mouse-source.swift
echo "✅ 编译完成：$(pwd)/mouse-source"
echo "   先跑 ./mouse-source --list 看看你的两个鼠标是哪两个标识（这一步不弹权限框）"
