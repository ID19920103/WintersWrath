#coding:utf-8
import os
import re
import sys
import md5
import json
import time
import redis
import logging
import function
from selenium import webdriver
from google.cloud import storage
from google.cloud.storage import Blob
from termcolor import colored, cprint
from selenium.common.exceptions import TimeoutException

#################################################################################################
logging.basicConfig(level=logging.DEBUG,
                format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
                datefmt='%a, %d %b %Y %H:%M:%S',
                filename='app.log',
                filemode='a')

console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)
#################################################################################################

#运行时间装饰器
def exeTime(func):
    def newFunc(*args, **args2):
        t0 = time.time()
        print "@%s, {%s} start" % (time.strftime("%X", time.localtime()), func.__name__)
        back = func(*args, **args2)
        print "@%s, {%s} end" % (time.strftime("%X", time.localtime()), func.__name__)
        print "@%.3fs taken for {%s}" % (time.time() - t0, func.__name__)
        return back
    return newFunc

class Uploder():
    def __init__(self):
        self.storage_client = storage.Client()
        try:
            self.bucket = self.storage_client.get_bucket('argus_space')
            logging.debug("成功获得GCP存储空间.")
        except Exception as e:
            logging.error( '指定存储空间不存在，请检查GCP.' )

    def generator(self, file_name):
        #encryption_key = 'c7f32af42e45e85b9848a6a14dd2a8f6'
        self.blob = Blob( file_name, self.bucket, encryption_key=None )
        self.blob.upload_from_filename( file_name )
        self.blob.make_public()

    def get_media_link(self):
        return self.blob.media_link

    def get_public_link(self):
        return self.blob.public_url

    def get_dir(self, dir_name):
        return os.listdir(dir_name)

class Alloctor:
    def __init__(self):
        self.url = ''   #url地址
        self.host = '35.187.193.187'    #redis服务器地址
        self.port = 6380    #redis服务端口
        self.db = 0     #redis数据库
        try:
            self.redis_db = redis.ConnectionPool(host = self.host, port = self.port, db = self.db)
            self.redis_db = redis.Redis(connection_pool = self.redis_db)
            logging.info( colored(' 装载器准备完毕', 'green') )
        except:
            logging.error( '装载器无法连接Redis服务器，请检查配置.' )

    def getUrl(self):
        for times in range(3):  #预处理队列读取
            pre_url_json = self.redis_db.spop('preparation')  #弹出预处理url

            if pre_url_json is not None:
                #format: json(data = [{'url':'http://www.126.com', 'level':'1'}])
                pre_url = json.loads(pre_url_json)['url'].encode('utf-8')
                level = json.loads(pre_url_json)['level']
                logging.info( str(pre_url) + ' is selected, level is ' + str(level) )
                return pre_url, level

            else:
                logging.error( '无法从预处理队列取得url，正在重试('+ str(times+1) +')...' )
                time.sleep(1)
                continue

        raise LookupError("无法从预处理队列取得url，请检查Redis服务器.")
        #sys.exit(0) #退出

    def update_data(self, data_name, data):
        try:
            self.redis_db.hmset(data_name, data)
            self.redis_db.sadd("done", data_name)
            logging.info( colored(data_name + ' 数据包回传成功', 'green') )
        except:
            logging.error( '数据包回传失败，请检查Redis服务器.' )


class Sdriver:
    def __init__(self):
        try:
            self.JS_PATH = '/home/dumingzhex/Downloads/phantomjs-2.1.1-linux-x86_64/bin/phantomjs'  #PhantomJS路径
            self.IMAGE_PATH = '/home/dumingzhex/Projects/WintersWrath/webspider/Image/'   #截图保存路径
            self.driver = webdriver.PhantomJS(executable_path = self.JS_PATH)
            self.driver.set_page_load_timeout(5)   #设置渲染超时时间
            self.driver.set_script_timeout(5)
            self.IMAGE_NAME = md5.new()
            logging.info( colored(' 渲染器准备完毕', 'green') )
        except:
            logging.error( '渲染器无法连接，请检查配置.' )

    def get_page(self, url, level, uploder):
        try:
            self.driver.get(url)
        except TimeoutException:
            self.driver.execute_script('window.stop()')
            logging.info( colored( '页面 ' + url + ' 加载超时，停止加载...', 'red', attrs=['blink']) )
        except Exception as e:
            logging.info( " 未知错误: " + str(e) )

        url_list = []
        pattern = re.compile(r'[a-zA-z]+://[^\s]*')
        self.IMAGE_NAME.update(url)
        md5_name = self.IMAGE_NAME.hexdigest()

        try:
            page_source =  self.driver.page_source
            logging.info( '获取到 ' + url + ' 页面HTML' )

            link_handler = self.driver.find_elements_by_tag_name('a')
            logging.info( '获取到 ' + url + ' 链接资源' )

            self.driver.save_screenshot( self.IMAGE_PATH + md5_name + ".png")
            logging.info( '获取到 ' + url + ' 截图' )
            uploder.generator(self.IMAGE_PATH + md5_name + ".png")
            image_public_url = uploder.get_public_link()
        except Exception, e:
            logging.error( '获取 ' + url + '内容失败' + str(e))

        try:
            for link_url in link_handler:
                match_url = pattern.match( link_url.get_attribute("href") )
                if match_url:
                    url_list.append(match_url.group().encode('utf-8'))
        except:
            logging.info( colored( '外链资源异常.', 'yellow') )

        finally:
            link_data = json.dumps(url_list)

        url_data = { "page_source":page_source, "link_handler":link_data, "image": image_public_url, "level":level}
        #except:
        #    logging.error( '获取 ' + url + '内容失败' )
        #    data = {"result":"failed"}

        return url_data

    def close_driver(self):
        self.driver.quit()
