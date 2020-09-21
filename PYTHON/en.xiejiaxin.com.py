#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@author mybsdc <mybsdc@gmail.com>
@date 2020/7/1
@time 17:14
"""

import os
import errno
import time
import re
import traceback
from urllib import parse
from functools import reduce
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, ALL_COMPLETED
import requests
from requests.adapters import HTTPAdapter
from pyquery import PyQuery as pq
from lxml import etree
import colorful as cf
import argparse


def catch_exception(origin_func):
    def wrapper(self, *args, **kwargs):
        """
        用于异常捕获的装饰器
        :param origin_func:
        :return:
        """
        try:
            return origin_func(self, *args, **kwargs)
        except AssertionError as ae:
            print('参数错误：{}'.format(str(ae)))
        except Exception as e:
            print('出错：{} 位置：{}'.format(str(e), traceback.format_exc()))
        finally:
            pass

    return wrapper


class Downloader(object):
    headers = {
        'Accept-Language': 'zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7,und;q=0.6',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/'
                      '83.0.4103.116 Safari/537.36'
    }
    courseware_regex = re.compile(r'<a class=\"\" href=\"/tougao/HTML/(?P<num>\d+?)\.html.*?title=\"(?P<title>.*?)\"',
                                  re.I)
    item_regex = re.compile(r"window\.location\.href='.*?HTML/(?P<code>\d+)\.html';", re.I)
    items_regex = re.compile(r'title=\"\" href=\"/waiyanban/HTML/(?P<code>\d+)\.html\" target=_blank>(?P<title>.*?)<',
                             re.I)

    def __init__(self):
        # 解析命令行传参
        self.args = self.get_all_args()

        # 最大线程数
        self.max_workers = self.args.max_workers

        # 代理池
        self.proxy_pool = []
        self.proxy_num = 0
        self.enable_proxy = False

        self.curl = requests.Session()
        self.curl.headers = Downloader.headers
        self.max_retries = 3
        self.curl.mount('http://', HTTPAdapter(max_retries=self.max_retries))
        self.curl.mount('https://', HTTPAdapter(max_retries=self.max_retries))

    def __set_proxy_pool(self) -> None:
        if not self.enable_proxy:
            return

        r = self.curl.get(
            'https://proxyapi.horocn.com/api/v2/proxies?order_id=7D3G1678402087038498&num=10&format=json&line_separator=win&can_repeat=no&user_token=6de15444142f7b906a0ef6ef45b41233').json()

        if r.get('code') != 0:
            raise Exception(r.get('msg'))

        self.proxy_pool = list(map(lambda item: f"{item.get('host')}:{item.get('port')}", r.get('data')))

    def __get_proxy(self):
        if not self.enable_proxy:
            return {}

        try:
            proxy = self.proxy_pool[self.proxy_num]
            self.proxy_num += 1
        except IndexError as ie:
            self.proxy_num = 0
            proxy = self.proxy_pool[self.proxy_num]

        return {
            'https': proxy,
            'http': proxy
        }

    def download(self, subject, title, url):
        """
        下载课件
        :param title:
        :param url:
        :return:
        """
        filename = 'data/{}/{}.zip'.format(subject, title)
        if os.path.exists(filename) and os.path.getsize(filename):
            return True

        print('{c.italic_yellow}开始下载 《{title}》{c.no_italic}{c.close_fg_color}'.format(c=cf, title=title))
        with requests.get(url, headers=Downloader.headers, stream=True, proxies=self.__get_proxy()) as r:
            r.encoding = 'GBK'

            if 'ERROR' in r.text:
                print('出现未知错误')

                return False

            if '本站对特定时间段的下载数量进行了限制' in r.text:
                print('下载数量受限制')

                return False

            dirname = os.path.dirname(filename)
            os.makedirs(dirname, exist_ok=True)

            try:
                with open(filename, 'wb') as f:
                    # 分块写入磁盘，支持大文件
                    for chunk in r.iter_content(chunk_size=1024):
                        chunk and f.write(chunk)
            except Exception as e:
                Downloader.silent_remove(filename)
                print(cf.blue(f'下载《{title}》时出现未知错误，已下载部分已被删除'))

                raise

            # 检查文件的完整性
            # requests v3 也许会支持在文件不完整时抛出异常，但是 v2 不会
            # 参考：https://blog.petrzemek.net/2018/04/22/on-incomplete-http-reads-and-the-requests-library-in-python/
            content_len = int(r.headers.get('Content-Length'))
            actual_len = r.raw.tell()
            if content_len != actual_len:
                Downloader.silent_remove(filename)
                print(cf.blue(f'下载《{title}》时发现服务器返回的数据不完整，已删除不完整的文件'))

                raise IOError(f'读取不完整，已读取 {actual_len} 个字节，预期还差 {content_len - actual_len} 个字节，但是连接被关闭了')

            if os.path.getsize(filename) < 5120:
                Downloader.silent_remove(filename)
                print('文件过小，已删除')

        return title

    @staticmethod
    def silent_remove(filename):
        """
        静默删除
        相较于先检查文件是否存在的写法，这种写法更 pythonic，虽然看起来比较丑陋，但是在多线程中这种删除方式比事先检查文件是否存在更优，因为可能
        遇到当前线程去检查此文件刚刚还存在，但是去删的时候却被其它线程抢了先的情况
        参考：https://stackoverflow.com/a/10840586/8507338
        :param filename:
        :return:
        """
        try:
            os.remove(filename)
        except OSError as ose:
            if ose.errno != errno.ENOENT:
                raise

    def __get_courseware_items(self, html: str) -> list:
        """
        提取所有课件名称与地址
        :param html:
        :return:
        """
        match = Downloader.courseware_regex.findall(html)
        if match is None:
            raise Exception('匹配课件标题与地址出错')

        courseware_items = list(
            map(lambda item: {'url': f'http://en.xiejiaxin.com/tougao/HTML/{item[0]}.html', 'title': unescape(item[1])},
                match))

        return courseware_items

    @staticmethod
    def time_diff(start_time, end_time):
        """
        计算时间间隔
        :param start_time: 开始时间戳
        :param end_time: 结束时间戳
        :return:
        """
        diff_time = end_time - start_time

        if diff_time < 0:
            raise ValueError('结束时间必须大于等于开始时间')

        if diff_time < 1:
            return '{:.2f}秒'.format(diff_time)
        else:
            diff_time = int(diff_time)

        if diff_time < 60:
            return '{:02d}秒'.format(diff_time)
        elif 60 <= diff_time < 3600:
            m, s = divmod(diff_time, 60)

            return '{:02d}分钟{:02d}秒'.format(m, s)
        elif 3600 <= diff_time < 24 * 3600:
            m, s = divmod(diff_time, 60)
            h, m = divmod(m, 60)

            return '{:02d}小时{:02d}分钟{:02d}秒'.format(h, m, s)
        elif 24 * 3600 <= diff_time:
            m, s = divmod(diff_time, 60)
            h, m = divmod(m, 60)
            d, h = divmod(h, 24)

            return '{:02d}天{:02d}小时{:02d}分钟{:02d}秒'.format(d, h, m, s)

    @staticmethod
    def get_all_args():
        """
        获取所有命令行参数
        :return:
        """
        parser = argparse.ArgumentParser()
        parser.add_argument('-url', '--page_url', help='课本页面地址',
                            default='', type=str)
        parser.add_argument('-mw', '--max_workers', help='最大线程数', default=5, type=int)

        return parser.parse_args()

    def __get_all_coursewares(self, class_id=1044):
        all_coursewares = []
        page_num = 1

        while True:
            print('开始获取第 {c.bold_red_on_black}{page_num}{c.reset} 页内容'.format(page_num=page_num, c=cf))
            r = self.curl.get(
                'http://en.xiejiaxin.com/tougao/ShowClass.asp?ClassID={}&page={}'.format(class_id, page_num))
            r.encoding = 'GBK'
            all_coursewares += self.__get_courseware_items(r.text)

            if '| 下一页 | 尾页' in r.text:
                print('{c.green}已取得所有课件地址{c.reset}'.format(c=cf))
                break

            page_num += 1
            time.sleep(2)

        print('共发现 {c.bold_red_on_black}{count}{c.reset} 份课件'.format(count=len(all_coursewares), c=cf))

        return all_coursewares

    @staticmethod
    def __get_real_coursewares(all_coursewares: list, keyword: str = '三起'):
        real_coursewares = list(
            filter(lambda item: keyword in item.get('title') and '六年级' not in item.get('title'), all_coursewares))
        print('外研版（三年级起点）相关课件共 {c.green}{count}{c.reset} 份'.format(count=len(real_coursewares), c=cf))

        return real_coursewares

    @staticmethod
    def pipeline(*steps):
        return reduce(lambda x, y: y(x()) if callable(x) else y(x), list(steps))

    def __parse_download_page(self, title: str, url: str):
        """
        解析下载页面内容
        :param title:
        :param url:
        :return:
        """
        with requests.get(url, headers=Downloader.headers, allow_redirects=True) as r:
            r.encoding = 'GBK'

            # 单份资料
            match = Downloader.item_regex.search(r.text)
            if match:
                return [
                    {
                        'title': title,
                        'code': match.group('code')
                    }
                ]

            # 付费资源
            if '不提供自助下载' in r.text:
                print('{c.green}{title}{c.reset} 是付费资源，无法获取'.format(title=title, c=cf))

                return None

            # 多份资料
            items = Downloader.items_regex.findall(unescape(r.text))
            if items:
                return list(map(lambda item: {'title': item[1], 'code': item[0]}, items))

            return None

    def __get_download_urls(self, real_coursewares: list):
        all_items = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            all_tasks = {
                executor.submit(self.__parse_download_page, item.get('title'), item.get('url')): item.get('title') for
                item in real_coursewares}

            for future in as_completed(all_tasks):
                title = all_tasks[future]

                try:
                    result = future.result()
                    if result is None:
                        continue

                    all_items[title] = future.result()
                    print('{c.green}{title}{c.reset} 的下载页面内容 {c.green}解析成功{c.reset}'.format(title=title, c=cf))
                except Exception as e:
                    print('在处理 {title} 的时候抛出了一个异常，内容为 {c.red}{e}{c.reset}'.format(title=title, e=str(e), c=cf))

        return all_items

    @catch_exception
    def run(self):
        start_time = time.time()

        self.__set_proxy_pool()

        all_items = Downloader.pipeline(self.__get_all_coursewares, self.__get_real_coursewares,
                                        self.__get_download_urls)

        with ThreadPoolExecutor(max_workers=10) as executor:
            all_tasks = {}
            for subject in all_items:
                print(f'开始处理 {subject} 下的所有课件')
                for item in all_items[subject]:
                    all_tasks[executor.submit(self.download, subject, item.get('title'),
                                              f'http://en.xiejiaxin.com/waiyanban/abShowSoftDown.asp?UrlID=1&SoftID={item.get("code")}')] = item.get(
                        'title')

            for future in as_completed(all_tasks):
                url = all_tasks[future]

                try:
                    title = future.result()
                    if isinstance(title, str):
                        print('《{c.green}{title}{c.reset}》{c.green}下载成功{c.reset}'.format(title=title, c=cf))
                except Exception as e:
                    print('在处理 {url} 的时候抛出了一个异常，内容为 {c.red}{e}{c.reset}'.format(url=url, e=str(e), c=cf))

        print('耗时：', cf.magenta(f'{self.time_diff(start_time, time.time())}'), sep='')


if __name__ == '__main__':
    downloader = Downloader()
    downloader.run()
