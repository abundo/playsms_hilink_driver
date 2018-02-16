#!/usr/bin/env python3
"""
A driver, interfacing playsms with a Huawei E3372 USB modem in hilink mode.

Supports sending and receiving SMS

License:
  Copyright 2017 Anders Löwinger, anders@abundo.se

  This file is part of playsms_hilink_driver.

  playsms_hilink_driver is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  playsms_hilink_driver is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with playsms_hilink_driver.  If not, see <http://www.gnu.org/licenses/>.


"""

import os
import os.path
import sys
import json
import datetime
import time
import threading
import logging
import logging.handlers
import urllib.parse
import xmltodict
import requests
import yaml
import argparse

from orderedattrdict import AttrDict

from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn


conf = AttrDict()

# ----- start of configuration ------------------------------------------------

CONFIG_FILE = "/etc/playsms_hilink_driver/config.yaml"

# conf.http_server_port = 8888
# conf.modem_base_url = "http://192.168.8.1"
# conf.modem_cookie_url = '/html/index.html'


# ----- Helper functions -----------------------------------------------------

datetime_str_format = "%Y-%m-%d %H:%M:%S"


def now_dt():
    return datetime.datetime.now().replace(microsecond=0)


def now_str():
    return now_dt().strftime(datetime_str_format)


def ordered_load(stream, Loader=yaml.Loader, object_pairs_hook=AttrDict):
    """
    Load Yaml document, replace all hashes/mappings with AttrDict
    """
    class Ordered_Loader(Loader):
        pass

    def construct_mapping(loader, node):
        loader.flatten_mapping(node)
        return object_pairs_hook(loader.construct_pairs(node))
    Ordered_Loader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping)
    return yaml.load(stream, Ordered_Loader)


def yaml_load(filename):
    with open(filename, "r") as f:
        try:
            # self.default_data = yaml.load(f)
            data = ordered_load(f, yaml.SafeLoader)
            return data
        except yaml.YAMLError as err:
            raise UtilException("Cannot load YAML file %s, err: %s" % (filename, err))


# ----- Read configuration file ----------------------------------------------

conf = yaml_load(CONFIG_FILE)


# ----- setup logging, console or syslog if run as daemon --------------------

log = logging.getLogger('hilink_driver')
log.setLevel(conf.log.level)

# remove all handlers
for hdlr in log.handlers:
    log.removeHandler(hdlr)

if sys.stdout.isatty():
    consolehandler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    consolehandler.setFormatter(formatter)
    log.addHandler(consolehandler)
else:
    syslogger = logging.handlers.SysLogHandler(address='/dev/log')
    formatter = logging.Formatter('%(module)s: %(levelname)s %(message)s')
    syslogger.setFormatter(formatter)
    log.addHandler(syslogger)


# ----- end of logging setup -------------------------------------------------

class PlaySMS:
    """
    Handle communication to/from PlaySMS
    """
    def __init__(self):
        pass
    
    def insert_sms_into_playsms(self, id=None, from_=None, to=None, text=None):
#        http://10.10.80.129/playsms/plugin/gateway/generic/callback.php?
#        \&from=0722060322\&message=nisse\&to=46705747187\&smsc=generic
        data = AttrDict()
        data.id = id
        data.authcode = "fc5fc18a232c42cf17a5be44f5a018314422505d"
        data['from'] = from_        # from is a python reserved keyword
        data.message = text
        data.to = "+46705747187"
        data.smsc = 'generic'

        url = "http://10.10.80.129/playsms/plugin/gateway/generic/callback.php?"
        url += urllib.parse.urlencode(data, encoding='utf-8')
        ret = requests.get(url=url).text
        return ret
    
    def sms_from_playsms(self):
        pass

playsms = PlaySMS()

class USB_modem:
    """
    Class to manage the USB modem via hilink
    
    Starts a background process, that periodically polls the modem
    for new SMS. When a SMS is received, it is forwarded to playsms
    """

    def __init__(self):
        self.session = requests.Session()
        r = self.session.get(conf.modem.base_url + conf.modem.cookie_url)

        # Start background thread, polling for received SMS
        self.thread = threading.Thread(target=self.poll_receive_sms, args=())
        self.thread.daemon = True
        self.thread.start()


    def get_session(self):
        """
        All communication with the USB modem needs a valid session
        """
        session_token = xmltodict.parse(self.session.get(conf.modem.base_url +\
            "/api/webserver/SesTokInfo").text).get('response',None)
        session = session_token.get("SesInfo")  #cookie
        token = session_token.get("TokInfo") #token
        return session, token
    

    def get_sms_list(self):
        """
        Return a list with up to 10 received SMSes
        """
        session, token = self.get_session()
        headers = {
            'Cookie': session, 
            '__RequestVerificationToken': token, 
            }

        api_url = conf.modem.base_url + "/api/sms/sms-list"
        post_data =  b""
        post_data += b'<?xml version="1.0" encoding="UTF-8"?>\n'
        post_data += b"<request>\n"
        post_data += b"  <PageIndex>1</PageIndex>\n"
        post_data += b"  <ReadCount>10</ReadCount>\n"
        post_data += b"  <BoxType>1</BoxType>"
        post_data += b"  <SortType>0</SortType>"
        post_data += b"  <Ascending>0</Ascending>"
        post_data += b"  <UnreadPreferred>0</UnreadPreferred>"
        post_data += b"</request>\n"
        
        ret = self.session.post(url=api_url, data=post_data, headers=headers).text
        data = xmltodict.parse(ret)
        ret_messages = []

        if 'Messages' in data['response']:
            messages = data['response']['Messages']
            if messages is not None:
                message_list = messages['Message']

                # If we only have one message, it is not returned as a list
                # so it cannot be iterated over, convert to list.
                if not isinstance(message_list, list):
                    message_list = [ message_list ]

                for message in message_list:
                    if message['SmsType'] == '1':
                        msg = AttrDict()
                        for attr in ['Index', 'Phone', 'SmsType', 'Content']:
                            msg[attr] = message[attr]
                        ret_messages.append(msg)
        return ret_messages


    def delete_sms(self, index):
        """
        Delete a SMS from the modem.
        """
        log.info("Delete SMS with index %s" % index)
        session, token = self.get_session()
        headers = {
            'Cookie': session, 
            '__RequestVerificationToken': token, 
            }
        api_url = conf.modem.base_url + "/api/sms/delete-sms"
        post_data = b""
        post_data += b'<?xml version="1.0" encoding="UTF-8"?>\n'
        post_data += b"<request>\n"
        post_data += b"  <Index>%s</Index>\n" % index.encode()
        post_data += b"</request>\n"
        ret = self.session.post(url=api_url, data=post_data, headers=headers).text
        data = xmltodict.parse(ret)
        return data


    def poll_receive_sms(self):
        """
        Runs as a separate thread, polling for new SMS
        All recevied SMSes are inserted into playsms, then deleted from the modem
        """
        while True:
            messages = self.get_sms_list()
            for message in messages:
                log.info("Received SMS index: %s  from: %s  message: %s" % (message.Index, message.Phone, message.Content))
                playsms.insert_sms_into_playsms(id=message.Index, from_=message.Phone, text=message.Content)
                self.delete_sms(message.Index)
            time.sleep(10)


    def send_sms(self, numbers=None, text=None):
        log.info("Sending SMS, number: %s  message: %s" % ( ",".join(numbers), text))
        session, token = self.get_session()
        api_url = conf.modem.base_url + "/api/sms/send-sms"
        length = str(len(text))
        headers = {
            'Cookie': session, 
            '__RequestVerificationToken': token,
             "Content-Type":"application/x-www-form-urlencoded; charset=UTF-8"
            }

        # Build XML structure
        post_data = b""
        post_data += b'<?xml version="1.0" encoding="UTF-8"?>\n'
        post_data += b"<request>\n"
        post_data += b"  <Index>-1</Index>\n"
        post_data += b"  <Phones>\n"
        for number in numbers:
            post_data += b"    <Phone>%s</Phone>\n" % number.encode()
        post_data += b"  </Phones>\n"
        post_data += b"  <Sca></Sca>\n"
        post_data += b"  <Content>%s</Content>\n" % text.encode()
        post_data += b"  <Length>%s</Length>\n" % str(length).encode()
        post_data += b"  <Reserved>1</Reserved>\n"
        post_data += b"  <Date>%s</Date>\n" % now_str().encode()
        post_data += b"</request>\n"
        
        ret = self.session.post(url=api_url, data=post_data, headers=headers).text
        return xmltodict.parse(ret)


usb_modem = USB_modem()

if 0:
    if 1:
        messages = usb_modem.get_sms_list()
        print(messages)
        #if len(messages) > 0:
        #    ret = usb_modem.delete_sms(messages[0].Index)
        sys.exit(1)

    if 0:
        ret = usb_modem.send_sms(numbers=['0722060322'], text="räksmörgås RÄKSMÖRGÅS")
        print("ret", ret)
        sys.exit(1)

class RequestHandler(BaseHTTPRequestHandler):
    """
    HTTP server
    This implements the generic API, which playsms uses to send an SMS
    Receive the message and send it to the USB modem
    """

    def log_message(self, format_, *args):
        """
        Supress all handled URLs output to stdout
        """
        return
    
    def _return(self, response_code, message, content_type="text/html"):
        # Write content as utf-8 data
        if isinstance(message, str):
            message = bytes(message, "utf8")
        self.send_response(response_code)
       
        self.send_header('Content-type', content_type)
#        self.send_header('Content-Length',str(len(message)))       # only needed for http 1.1 ?
        self.end_headers()
        self.wfile.write(message)
        
    def _return_json(self, response_code, data):
        jsondata = json.dumps(data)
        self._return(response_code, jsondata, content_type="application/json")

    def do_GET(self):
        log.debug("path %s" % self.path)
        path = self.path

        if path.startswith("/api/send_sms"):
            query = urllib.parse.urlparse(self.path).query
            args = urllib.parse.parse_qs(query, encoding='utf-8')
            text = args["message"][0]
            numbers = args["msisdn"]
            ret = usb_modem.send_sms(numbers=numbers, text=text)
            return self._return_json(200, "OK")
                
        return self._return(401, "Unknown API call\n")


class ThreadingServer(ThreadingMixIn, HTTPServer):
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", 
                        default=False,
                        action="store_true",
                        help="Run as a server, interfacing with playSMS")

    args = parser.parse_args()

    if args.server:
        log.info('starting HTTP server on port %s' % (conf.http_server.port))
        server_address = ('127.0.0.1', conf.http_server.port)
        httpd = ThreadingServer(server_address, RequestHandler)
        httpd.serve_forever()
    else:
        print("Nothing to do")


if __name__ == "__main__":
    main()
