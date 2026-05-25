#!/usr/bin/env bash
# SC2046: unquoted $(cmd) 的输出也会被 word splitting
# 路径含空格时 cd $(pwd) 会炸
#
# 运行：bash sc2046-unquoted-subst.sh

dir="/tmp/sc2046-demo $$"   # 路径自带空格
mkdir -p "$dir"
cd "$dir"

echo "=== 当前目录（含空格）：$(pwd) ==="
echo

echo "=== 错误：cd \$(pwd)（被拆成多个 arg）==="
cd $(pwd) 2>&1 | sed 's/^/  /' || echo "  cd 失败：'$(pwd)' 被拆开"

echo
echo "=== 正确：cd \"\$(pwd)\" ==="
cd "$(pwd)" && echo "  cd 成功，当前在：$(pwd)"

cd /
rm -rf "$dir"
