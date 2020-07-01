<?php
/**
 * @author mybsdc <mybsdc@gmail.com>
 * @date 2020/3/6
 * @time 15:56
 */

if (!function_exists('system_log')) {
    /**
     * 写日志
     *
     * @param $content
     * @param array $response
     * @param string $fileName
     * @description 受支持的着色标签
     * 'reset', 'bold', 'dark', 'italic', 'underline', 'blink', 'reverse', 'concealed', 'default', 'black', 'red',
     * 'green', 'yellow', 'blue', 'magenta', 'cyan', 'light_gray', 'dark_gray', 'light_red', 'light_green',
     * 'light_yellow', 'light_blue', 'light_magenta', 'light_cyan', 'white', 'bg_default', 'bg_black', 'bg_red',
     * 'bg_green', 'bg_yellow', 'bg_blue', 'bg_magenta', 'bg_cyan', 'bg_light_gray', 'bg_dark_gray', 'bg_light_red',
     * 'bg_light_green','bg_light_yellow', 'bg_light_blue', 'bg_light_magenta', 'bg_light_cyan', 'bg_white'
     */
    function system_log($content, array $response = [], $fileName = '')
    {
        try {
            $path = sprintf('%s/logs/%s/', __DIR__, date('Y-m'));
            $file = $path . ($fileName ?: date('d')) . '.log';

            if (!is_dir($path)) {
                mkdir($path, 0777, true);
                chmod($path, 0777);
            }

            $handle = fopen($file, 'a'); // 追加而非覆盖

            if (!filesize($file)) {
                chmod($file, 0666);
            }

            $msg = sprintf(
                "[%s] %s %s\n",
                date('Y-m-d H:i:s'),
                is_string($content) ? $content : json_encode($content),
                $response ? json_encode($response, JSON_UNESCAPED_UNICODE) : '');

            echo $msg;

            fwrite($handle, $msg);
            fclose($handle);

            flush();
        } catch (\Exception $e) {
            // DO NOTHING
        }
    }
}

require __DIR__ . '/vendor/autoload.php';

use Curl\Curl;
use Curl\MultiCurl;

class Downloader
{
    protected static $instance;

    /**
     * @throws Exception
     */
    public function handle()
    {
        $client = new Curl();

        global $argv;

        if (!isset($argv[1])) {
            system_log('缺少必要的页面地址参数');
            exit(0);
        }

        $pageUrl = $argv[1]; // https://bp.pep.com.cn/jc/ptgzkcbzsyjks/gzkbsxjsys/
        $client->get($pageUrl);
        $page = $client->rawResponse;

        if (!preg_match('/<title>(?P<title>.*?)<\/title>/i', $page, $m)) {
            throw new \Exception('标题匹配失败');
        }
        $title = $m['title'];

        if (!preg_match_all('/title="(?P<subject>.*?)">.+?<\/a><\/h6>(?:.|\s)+?"\.\/(?P<path>.*?\.pdf)"/i', $page, $items, PREG_SET_ORDER)) {
            throw new \Exception('未匹配到课本信息');
        }

        $multiClient = new MultiCurl();
        $multiClient->setTimeout(0);
        $multiClient->success(function ($c) {
            system_log(sprintf('下载成功：%s', $c->url));
        });
        $multiClient->error(function ($c) {
            system_log(sprintf('出错：%s 原因：%s', $c->url, $c->errorMessage));
        });

        system_log(sprintf('共发现%d个课本', count($items)));

        $dir = sprintf('data/%s/', $title);
        system_log(sprintf('正在新建文件夹：%s', $dir));
        if (!is_dir($dir)) {
            mkdir($dir, 0777, true);
            chmod($dir, 0777);
        }
        system_log('文件夹准备好了');

        system_log('开始创建任务...');
        foreach ($items as $item) {
            $subject = $item['subject'];
            $path = $item['path'];
            $file = sprintf('%s%s.pdf', $dir, $subject);
            if (file_exists($file) && filesize($file)) {
                continue;
            }

            $multiClient->addDownload(sprintf('%s%s', $pageUrl, $path), $file);
            system_log(sprintf('已添加任务：《%s》', $subject));
        }
        $multiClient->start();

        system_log('恭喜，所有任务执行完成');
    }

    public static function getInstance()
    {
        if (!self::$instance instanceof self) {
            self::$instance = new self();
        }

        return self::$instance;
    }
}

try {
    Downloader::getInstance()->handle();
} catch (\Exception $e) {
    echo $e->getMessage();
}