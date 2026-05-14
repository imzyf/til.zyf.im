<?php
// 多行 + CJK + emoji 排版，展示 Pango 渲染能力
// 输出 multiline.png（透明底 RGBA）
// 系统需有 Noto Sans CJK SC + emoji 字体

require __DIR__ . '/vendor/autoload.php';

use Jcupitt\Vips\Image;

$body = <<<TEXT
你好，世界 🌏
libvips 用 Pango 做 layout：
自动换行、CJK shaping、emoji、双向文本一把抓。
TEXT;

$txt = Image::text($body, [
    'font'    => 'Noto Sans CJK SC 28',
    'width'   => 800,            // 800px 内 word-wrap
    'align'   => 'centre',
    'spacing' => 50,
    'rgba'    => true,
]);

$txt->writeToFile(__DIR__ . '/multiline.png');

echo "wrote multiline.png ({$txt->width}x{$txt->height})\n";
