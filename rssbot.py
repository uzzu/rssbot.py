#!/usr/bin/python
# -*- coding: utf-8 -*-
#

import datetime
import hashlib
import os
import random
import re
import time
import traceback
import urllib
import urllib2
import json
import feedparser

################################################################################
###                          classes for general                             ###
################################################################################
class RssStatus(object):
    u'''
    ビルド情報保持クラス.保存用
    '''
    def __init__(self, title, pub_date):
        self.title = title
        self.pub_date = pub_date

    def to_stored_line(self):
        u'''
        ローカルに保存する用のフォーマットで出力
        '''
        return '# ' + self.pub_date + ' --- <<' + self.title + '>>'

    @staticmethod
    def from_stored_line(line):
        u'''
        ローカルに保存してあるファイルの行のフォーマットでパースしつつRssStatusオブジェクトを返却
        '''
        match = re.match(r'^# (.*) --- <<(.*)>>$', line, re.M | re.I)
        pub_date = match.group(1)
        title = match.group(2)
        return RssStatus(title, pub_date)

class Identity(object):
    u'''
    識別子
    '''
    def __init__(self, value):
        self.value = value
    def __eq__(self, other):
        return self.value == other.value
    def __ne__(self, other):
        return self.value != other.value

################################################################################
###                          classes for chatwork                            ###
################################################################################

class ChatworkApiToken(object):
    u'''
    '''
    def __init__(self, value):
        u'''
        :param value:
        :rtype : ChatworkApiToken
        '''
        self.value = value

class ChatworkRoom(object):
    u'''
    chatworkの部屋
    id: 部屋のID
    '''
    def __init__(self, roomId):
        u'''
        :param roomId:
        :rtype : ChatworkRoom
        '''
        self.id = roomId

class ChatworkMessageId(Identity):
    def __init__(self, value):
        Identity.__init__(self, value)

    @staticmethod
    def from_json(obj):
        r = ChatworkMessageId(obj['message_id'])
        return r

class ChatworkMessageBuilder(object):
    u'''
    chatworkのchat文字列を生成するimmutable Builderクラス
    '''
    def __init__(self, ctx = None):
        u'''
        :param ctx:
        :rtype : object
        '''
        if ctx is None:
            self._info_writing = False
            self._title_writing = False
            self._text = ''
            return
        self._info_writing = ctx._info_writing
        self._title_writing = ctx._title_writing
        self._text = ctx._text

    def begin_info(self):
        u'''
        infoを開始
        '''
        if self._info_writing: raise Exception('info was started')
        r = ChatworkMessageBuilder(self)
        r._text += '[info]'
        r._info_writing = True
        return r

    def end_info(self):
        u'''
        infoを終了
        '''
        if not self._info_writing: raise Exception('info was not started.')
        r = ChatworkMessageBuilder(self)
        r._text += '[/info]'
        r._info_writing = False
        return r

    def begin_title(self):
        u'''
        titleを開始
        '''
        if self._title_writing: raise Exception('title was started')
        r = ChatworkMessageBuilder(self)
        r._text += '[title]'
        r._title_writing = True
        return r

    def end_title(self):
        u'''
        titleを終了
        '''
        if not self._info_writing: raise Exception('title was not started.')
        r = ChatworkMessageBuilder(self)
        r._text += '[/title]'
        r._title_writing = False
        return r

    def with_body(self, text):
        u'''
        chat文字列に指定したtextを含める
        '''
        r = ChatworkMessageBuilder(self)
        r._text += text
        return r

    def is_valid(self):
        u'''
        ビルド可能な状態か否かを返却
        '''
        if not (not self._info_writing and not self._title_writing): return False
        return True

    def build(self):
        u'''
        ビルドを実施し、chat用の文字列を返却
        '''
        if not self.is_valid(): raise Exception('Are you finished writing title or info?')
        return self._text

class ChatworkClient(object):
    def __init__(self, token, base_url = 'https://api.chatwork.com/v1/'):
        u'''
        :param token: ChatworkApiToken
        :rtype : ChatworkClient
        '''
        self.token = token
        self.base_url = base_url

    def send_message(self, room, message):
        u'''
        :param room: ChatworkRoom
        :param message: text
        '''
        url = self.base_url + 'rooms/' + room.id + '/messages'
        req = self._create_request(url)
        params = urllib.urlencode({'body': message.encode('utf-8')})
        response = urllib2.urlopen(req, params)
        raw_body = response.read()
        json_obj = json.loads(raw_body)
        return ChatworkMessageId.from_json(json_obj)

    def _create_request(self, url):
        req = urllib2.Request(url)
        req.add_header('X-ChatWorkToken', self.token.value)
        return req

################################################################################
###                          implements for bot                              ###
################################################################################

class NotifyOption(object):
    default_title = 'RSS情報をお送りします'
    def __init__(self, rss_url, last_rss_status_path, rooms, title):
        self.rss_url = rss_url
        self.last_rss_status_path = last_rss_status_path
        self.rooms = rooms
        self.title = title

    @staticmethod
    def from_json(obj):
        rss_url = obj['rss_url']
        last_rss_status_path = obj['last_rss_status_path']
        rooms = []
        for room_id in obj['rooms']: rooms.append(ChatworkRoom(room_id))
        title = obj.get('title', NotifyOption.default_title)
        return NotifyOption(rss_url, last_rss_status_path, rooms, title)

class RssConfig(object):
    u'''
    RssBotのConfiguration
    '''
    default_last_rss_status_path = 'last_rss_status.txt'
    default_interval = 3600
    default_notify_options = []
    def __init__(self, checksum, api_token, interval, notify_options):
        self.checksum = checksum
        self.api_token = api_token
        self.interval = interval
        self.notify_options = notify_options

    @staticmethod
    def from_file(path):
        u'''
        configファイルからRssConfigオブジェクトを生成して返却
        '''
        last_rss_status = {}
        lines = ''
        if os.path.exists(path):
            with open(path, 'r') as f: lines = f.readlines()
        conf_text = "".join(lines)
        checksum = hashlib.sha1(conf_text).hexdigest()
        conf_obj = json.loads(conf_text)
        api_token = ChatworkApiToken(conf_obj['api_token'])
        interval = conf_obj.get('interval', RssConfig.default_interval)
        options_json = conf_obj.get('notify_options', [])
        options = []
        for option_json in options_json:
            options.append(NotifyOption.from_json(option_json))
        return RssConfig(checksum, api_token, interval, options)

    def is_same_config(self, that):
        return self.checksum == that.checksum

class RssFeedBot(object):
    def __init__(self, config_file_path = 'config.json'):
        u'''
        :param config:
        :rtype : RssFeedBot
        '''
        self._config_file_path = config_file_path
        self._chatwork = None
        self._config = None

    def run(self):
        self._update_config()
        while True:
            try:
                self._process()
            except Exception:
                print '%s %s' % (datetime.datetime.today().strftime('%x %X'), traceback.format_exc())
            self._sleep()
            try:
                self._update_config()
            except Exception:
                print '%s %s' % (datetime.datetime.today().strftime('%x %X'), traceback.format_exc())

    def _sleep(self):
        time.sleep(self._config.interval)

    def _update_config(self):
        new_config = RssConfig.from_file(self._config_file_path)
        if (self._config is not None) and self._config.is_same_config(new_config): return
        self._config = new_config
        self._chatwork = ChatworkClient(self._config.api_token)
        print '%s Configuration has been updated.' % (datetime.datetime.today().strftime('%x %X'))

    def _process(self):
        for option in self._config.notify_options:
            feed = feedparser.parse(option.rss_url)
            olds = self._read_last_rss_status(option.last_rss_status_path)
            news = []
            entries_for_notify = []
            for entry in feed.entries:
                is_new_entry = True
                entry_for_notify = None
                for old in olds:
                    if old.title == entry.title and old.pub_date == entry.published:
                        is_new_entry = False
                        break
                if is_new_entry:
                    entry_for_notify = entry
                    news.append(RssStatus(entry.title, entry.published))
                if entry_for_notify is None: continue
                entries_for_notify.append(entry_for_notify)
            self._notify_reports(option, entries_for_notify)
            news.extend(olds)
            self._write_last_rss_status(option.last_rss_status_path, news)

    def _notify_reports(self, option, entries):
        u'''

        :param reports:
        :param options:
        '''
        body = ''
        for entry in entries:
            description = entry.description.replace('<br />', '\n')
            html_tag_re = re.compile(r'<[^>]+>')
            description = html_tag_re.sub('', description)
            body += self._build_message(entry.published, entry.title, description)
        if body == '': return
        message = self._decorate_message(option.title, body)
        for room in option.rooms:
            print room.id
            print message
            print '\n'
            self._chatwork.send_message(room, message)

    def _build_message(self, published, title, description):
        u'''
        メッセージを生成
        '''
        return ChatworkMessageBuilder() \
            .with_body('[') \
            .with_body(published) \
            .with_body('] ') \
            .with_body(title) \
            .with_body('\n') \
            .with_body(description) \
            .with_body('\n\n') \
            .build()

    def _decorate_message(self, title, report_body):
        u'''
        infoとかtitleでくくっておしゃれにしちゃう
        '''
        if not report_body: return ''
        if report_body[-1] == '\n': report_body = report_body[:-1]
        return ChatworkMessageBuilder() \
            .begin_info() \
                .begin_title() \
                    .with_body(title) \
                .end_title() \
                .with_body(report_body) \
            .end_info() \
            .build()

    def _read_last_rss_status(self, last_rss_status_path):
        u'''
        保存してあるRSS情報を取得
        '''
        last_rss_status = []
        lines = ''
        if os.path.exists(last_rss_status_path):
            with open(last_rss_status_path, 'r') as f: lines = f.readlines()
        for line in lines:
            status = RssStatus.from_stored_line(line)
            last_rss_status.append(status)
        return last_rss_status

    def _write_last_rss_status(self, last_rss_status_path, rss_status):
        u'''
        ビルド情報を保存
        '''
        text_to_write = ''
        for status in rss_status:
            text_to_write += status.to_stored_line()
            text_to_write += '\n'
        with open(last_rss_status_path, 'w+') as f: f.write(text_to_write)

################################################################################
###                               entry point                                ###
################################################################################

def main():
    RssFeedBot().run()

if __name__ == '__main__':
    main()
