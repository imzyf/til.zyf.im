#!/usr/bin/env bash
# SC2068: $@ 不加引号 → 含空格的参数被再次 word splitting 拆开
#
# 运行：bash sc2068-unquoted-at.sh

demo_bad() {
  echo "  \$# = $#（接收到的原始参数个数）"
  local i=1
  for arg in $@; do        # 错：$@ 没引号，再次 word splitting
    echo "    [$i] '$arg'"
    i=$((i+1))
  done
}

demo_good() {
  echo "  \$# = $#（接收到的原始参数个数）"
  local i=1
  for arg in "$@"; do      # 对：保持原始边界
    echo "    [$i] '$arg'"
    i=$((i+1))
  done
}

echo "=== 调用方传 3 个参数：\"a b\"  c  d ==="
echo
echo "--- 错误：for arg in \$@ ---"
demo_bad "a b" c d

echo
echo "--- 正确：for arg in \"\$@\" ---"
demo_good "a b" c d
