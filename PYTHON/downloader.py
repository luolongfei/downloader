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
import traceback
from urllib import parse
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, ALL_COMPLETED
import requests
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

    def __init__(self):
        # 解析命令行传参
        self.args = self.get_all_args()

        # 课本页面地址
        self.page_url = self.args.page_url

        # 最大线程数
        # 官方文档推荐将其值最大设为机器处理器的个数乘以 5
        # self.max_workers = os.cpu_count() * 5
        self.max_workers = self.args.max_workers

        self.curl = requests.Session()
        self.curl.headers = Downloader.headers

    @staticmethod
    def download(subject, title, url):
        """
        下载课本
        :param subject:
        :param title:
        :param url:
        :return:
        """
        filename = 'data/{}/{}.pdf'.format(subject, title)
        if os.path.exists(filename) and os.path.getsize(filename):
            return True

        print('{c.italic_yellow}开始下载 《{title}》{c.no_italic}{c.close_fg_color}'.format(c=cf, title=title))
        with requests.get(url, headers=Downloader.headers, stream=True) as r:
            r.encoding = 'utf-8'

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

    def __get_books_items(self, page_url):
        """
        获取所有课本的标题与下载地址
        :param page_url:
        :return:
        """
        r = self.curl.get(page_url)
        r.encoding = 'utf-8'

        d = pq(r.text)
        subject = d('.con_title_jcdzs2020 h4').text().strip()
        li = d('#container ul li')

        books_items = []
        for item in li.items():
            title = item.find('h6 a').text().strip()
            path = item.find('.btn_type_dl').attr('href')
            url = parse.urljoin(page_url, path)

            books_items.append({
                'title': title,
                'url': url
            })

        return subject, books_items

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
                            default='https://bp.pep.com.cn/jc/ptgzkcbzsyjks/gzkbsxjsys/', type=str)
        parser.add_argument('-mw', '--max_workers', help='最大线程数', default=5, type=int)

        return parser.parse_args()

    @catch_exception
    def run(self):
        start_time = time.time()

        subject, books_items = self.__get_books_items(self.page_url)
        print('共发现 {c.bold_red_on_black}{count}{c.reset} 份课本，开始创建任务'.format(count=len(books_items), c=cf))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 将任务添加到线程池
            # 将 future 与 url 映射，便于后续捕获当前任务的 url
            all_tasks = {executor.submit(Downloader.download, subject, item.get('title'), item.get('url')): item.get('url') for item in books_items}

            # 阻塞，让主线程等待所有任务执行完成
            # wait(all_tasks, return_when=ALL_COMPLETED)

            for future in as_completed(all_tasks):
                url = all_tasks[future]

                try:
                    data = future.result()
                    if isinstance(data, str):
                        print('《{c.green}{title}{c.reset}》{c.green}下载成功{c.reset}'.format(title=data, c=cf))
                except Exception as e:
                    print('在处理 {url} 的时候抛出了一个异常，内容为 {c.red}{e}{c.reset}'.format(url=url, e=str(e), c=cf))
                else:
                    pass

            print('耗时：', cf.magenta(f'{self.time_diff(start_time, time.time())}'), sep='')


if __name__ == '__main__':
    downloader = Downloader()
    downloader.run()
