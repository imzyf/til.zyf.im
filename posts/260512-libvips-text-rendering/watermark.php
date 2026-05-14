<?php
// 给一张图加右下角文字水印
// 用法: php watermark.php <input> <output.png>

require __DIR__ . '/vendor/autoload.php';

use Jcupitt\Vips\Image;

if ($argc < 3) {
    fwrite(STDERR, "Usage: php watermark.php <input> <output.png>\n");
    exit(1);
}

[, $in, $out] = $argv;

$bg = Image::newFromFile($in);

$txt = Image::text('© imzyf 2026', [
    'font'  => 'Sans Bold 28',
    'width' => $bg->width - 80,    // word-wrap 边界
    'align' => 'high',             // 右对齐
    'rgba'  => true,
]);

$bg->composite($txt, 'over', [
    'x' => 40,
    'y' => $bg->height - $txt->height - 40,
])->writeToFile($out);

echo "wrote {$out}\n";
