<?php
/**
 * set_ck.php —— 供机器人自动更新点歌 Cookie 用。
 *
 * 部署：放到 C:\wwwroot\lala.fan\API\set_ck.php（与 qq.php、p_skey.txt 同目录）。
 * 安全：必须带正确的 token 才能写入；请把下面的 $TOKEN 改成一长串随机字符，
 *       并在机器人里用「设置点歌CK密钥 <同样的token>」配置成一致的值。
 *
 * 机器人会 POST：token=<密钥>&ck=<完整Cookie串>，成功后覆盖 p_skey.txt。
 */
error_reporting(0);

// ★★★ 改成你自己的长随机密钥（和机器人端保持一致）★★★
$TOKEN = 'CHANGE_ME_到一长串随机字符串';

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');

$token = $_POST['token'] ?? $_GET['token'] ?? '';
if (!is_string($token) || !hash_equals($TOKEN, $token)) {
    http_response_code(403);
    echo json_encode(['code' => -1, 'msg' => 'token 无效'], JSON_UNESCAPED_UNICODE);
    exit;
}

$ck = $_POST['ck'] ?? '';
if (!is_string($ck) || strpos($ck, 'qm_keyst=') === false) {
    echo json_encode(['code' => -2, 'msg' => 'CK 无效：缺少 qm_keyst'], JSON_UNESCAPED_UNICODE);
    exit;
}

$file = __DIR__ . '/p_skey.txt';
// 写入前先备份一份，便于回滚
if (file_exists($file)) {
    @copy($file, $file . '.bak');
}
$ok = @file_put_contents($file, trim($ck));

echo json_encode(
    $ok !== false
        ? ['code' => 0, 'msg' => 'p_skey.txt 已更新', 'bytes' => $ok]
        : ['code' => -3, 'msg' => '写入失败（检查目录写权限）'],
    JSON_UNESCAPED_UNICODE
);
