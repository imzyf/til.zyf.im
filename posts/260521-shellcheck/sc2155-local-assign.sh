#!/usr/bin/env bash
# SC2155: local/declare/export 同步赋值会掩盖右侧 $(cmd) 的退出码
# local 自身退出码永远是 0——即使开了 set -e 也救不了
#
# 运行：bash sc2155-local-assign.sh
# 检查：shellcheck sc2155-local-assign.sh   # 报 SC2155

failing_cmd() { return 42; }

bad() {
  local x=$(failing_cmd)                                       # ← SC2155 在这一行
  echo "  bad:  \$? = $?  ← local 退出码 = 0，failing_cmd 的 42 被吞了"
}

good() {
  local x
  x=$(failing_cmd)
  echo "  good: \$? = $?  ← failing_cmd 的真实退出码"
}

echo "=== 直接看退出码差异 ==="
bad
good

echo
echo "=== 在 set -e 下：bad 跑过头，good 被拦下 ==="

echo "--- bad ---"
bash -e <<'EOF'
failing_cmd() { return 42; }
bad() {
  local x=$(failing_cmd)
  echo "  set -e 没拦——继续往下跑"
}
bad
echo "  甚至跑到脚本末尾"
EOF
echo "  子进程退出码 = $?"

echo "--- good ---"
bash -e <<'EOF'
failing_cmd() { return 42; }
good() {
  local x
  x=$(failing_cmd)
  echo "  不会打印"
}
good
EOF
echo "  子进程退出码 = $?  ← set -e 拦下了"
