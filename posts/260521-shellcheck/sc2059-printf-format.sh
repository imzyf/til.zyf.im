#!/usr/bin/env bash
# SC2059: printf 第一个参数若含 %，会被当 format directive 而非字面字符
# 当字符串来自用户输入时是 format string injection 漏洞的根源
#
# 运行：bash sc2059-printf-format.sh

msg='100% complete: see /tmp/foo.log'

echo "=== 错误：printf \"\$msg\\n\"（% 被解析为 format spec）==="
printf "$msg\n" 2>&1 | sed 's/^/  /'

echo
echo "=== 攻击场景：msg 含 %s 期望参数但没传 ==="
attack='user=%s pid=%d'
printf "$attack\n" 2>&1 | sed 's/^/  /'

echo
echo "=== 正确：printf \"%s\\n\" \"\$msg\" ==="
printf "%s\n" "$msg" | sed 's/^/  /'
printf "%s\n" "$attack" | sed 's/^/  /'
