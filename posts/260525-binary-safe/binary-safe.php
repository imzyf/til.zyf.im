<?php

// Demo: PHP binary safety —— 配合 260525-binary-safe.md
// 跑法: php binary-safe.php
// 验证环境: PHP 8.5 (macOS) —— 不同 PHP 版本下 strto* 行为有差异，见 #5 注释

declare(strict_types=1);

function section(string $title): void
{
    echo "\n=== {$title} ===\n";
}

// 1. crypt() 遇 \0 截断 —— 同 salt + \0 后缀不同 → 同 hash 碰撞
section('1. crypt() \\0 truncation collision');

$salt = '$2y$10$' . str_repeat('a', 22);
$h1 = crypt("secret\0extra1", $salt);
$h2 = crypt("secret\0extra2", $salt);
$h3 = crypt("secret\0completely-different-suffix", $salt);

echo "h1: {$h1}\n";
echo "h2: {$h2}\n";
echo "h3: {$h3}\n";
echo 'h1 === h2 ? ' . var_export($h1 === $h2, true) . "\n";
echo 'h1 === h3 ? ' . var_export($h1 === $h3, true) . "\n";
echo "→ \\0 后面的内容全被 libc crypt 丢弃, 只有 'secret' 进了哈希\n";

// 2. random_bytes(32) 含 \0 的实际概率 —— 理论值 1 - (255/256)^32 ≈ 11.76%
section('2. random_bytes(32) NUL hit rate (theoretical ≈ 11.76%)');

$samples = 10_000;
$contains_null = 0;
for ($i = 0; $i < $samples; $i++) {
    if (str_contains(random_bytes(32), "\0")) {
        $contains_null++;
    }
}
$rate = $contains_null / $samples * 100;
printf("在 %d 次采样里 %d 次含 \\0 (≈ %.2f%%)\n", $samples, $contains_null, $rate);

// 3. 修法: 把二进制 key 先编码再喂 password_hash
section('3. Fix: base64_encode binary key before password_hash');

$key = random_bytes(32);
echo 'raw key (hex): ' . bin2hex($key) . "\n";
echo "（如果含 00 字节, 直接 password_hash 会丢一截熵）\n";
echo 'safe hash:     ' . password_hash(base64_encode($key), PASSWORD_BCRYPT) . "\n";

// 4. hash_hmac() 是 binary safe —— key 里有 \0 也读得到后面字节
section('4. hash_hmac is binary safe');

$key_with_null = "abc\0def";
$key_truncated = 'abc';
$msg = 'message';

echo "key 'abc\\0def' (len=" . strlen($key_with_null) . "):\n";
echo '  hmac: ' . hash_hmac('sha256', $msg, $key_with_null) . "\n";
echo "key 'abc'      (len=" . strlen($key_truncated) . "):\n";
echo '  hmac: ' . hash_hmac('sha256', $msg, $key_truncated) . "\n";
echo "→ 两个 hmac 不同, 证明 hash_hmac 读到了 \\0 后面的字节\n";

// 5. locale 影响行为 —— strcoll 按 LC_COLLATE 排序, 同样字节给相反结果
//
// 注: PHP 8.2 起 strtolower / strtoupper / ucfirst / ucwords 不再吃 locale,
//     永远只处理 ASCII (https://wiki.php.net/rfc/strtolower-ascii)。
//     当下仍 locale-aware 的是 strcoll。
section('5. strcoll order depends on locale');

setlocale(LC_COLLATE, 'C');
$c_cmp = strcoll("\xE4", 'z');
echo "locale=C:                strcoll(0xE4, 'z') = {$c_cmp} → "
    . ($c_cmp > 0 ? "ä > z (按字节 0xE4 > 0x7A)" : "ä < z") . "\n";

// macOS / Linux 上 de_DE.UTF-8 locale 名可能略有差异, 多试几个
$de_set = setlocale(LC_COLLATE, 'de_DE.UTF-8', 'de_DE.utf8', 'de_DE');
if ($de_set !== false) {
    $de_cmp = strcoll("\xC3\xA4", 'z');  // UTF-8 ä
    echo "locale={$de_set}:    strcoll('ä', 'z') = {$de_cmp} → "
        . ($de_cmp < 0 ? 'ä < z (德语 ä 紧挨 a, 在 z 前)' : 'ä > z') . "\n";
} else {
    echo "locale=de_DE.UTF-8: 系统未装该 locale, 跳过\n";
    echo "  (Linux 上 'sudo locale-gen de_DE.UTF-8' 安装; macOS 自带)\n";
}
setlocale(LC_COLLATE, 'C');

// 6. 用 mb_* + 显式编码绕开 locale —— 任何环境下行为一致
section('6. mb_strtolower with explicit encoding bypasses locale entirely');

$utf8_a_umlaut = "\xC3\x84";  // UTF-8 编码的 Ä (大写)
echo 'input bytes:           ' . bin2hex($utf8_a_umlaut) . " (UTF-8 Ä)\n";
echo 'mb_strtolower(UTF-8):  ' . bin2hex(mb_strtolower($utf8_a_umlaut, 'UTF-8'))
    . " (UTF-8 ä, 任何 locale 下都一样)\n";
echo 'strtolower (8.2+ ASCII only): ' . bin2hex(strtolower($utf8_a_umlaut))
    . " (字节原样, 不识别 UTF-8)\n";
