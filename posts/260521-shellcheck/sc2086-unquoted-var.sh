#!/usr/bin/env bash
# SC2086: unquoted $VAR 触发 word splitting / pathname expansion
# 用 ls 演示（rm 演示会有副作用风险）
#
# 运行：bash sc2086-unquoted-var.sh

dir=$(mktemp -d)
touch "$dir/a b"   # 一个文件名带空格

FILE="$dir/a b"

echo "=== 错误：ls \$FILE（无引号 → 拆成两个 arg）==="
ls $FILE 2>&1 | sed 's/^/  /' || true

echo
echo "=== 正确：ls \"\$FILE\" ==="
ls "$FILE" | sed 's/^/  /'

# glob 风险演示
touch "$dir/keep.log" "$dir/keep.txt"
PATTERN="$dir/*"
echo
echo "=== 错误：echo \$PATTERN（被 glob 展开）==="
echo $PATTERN | sed 's/^/  /'

echo
echo "=== 正确：echo \"\$PATTERN\"（保持字面）==="
echo "$PATTERN" | sed 's/^/  /'

rm -rf "$dir"
