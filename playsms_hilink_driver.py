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

from lib_log import log
from lib_usb_modem import USB_modem

# ----- start of configuration ------------------------------------------------

CONFIG_FILE = "/etc/playsms_hilink_driver/config.yaml"

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
            data = ordered_load(f, yaml.SafeLoader)
            return data
        except yaml.YAMLError as err:
            raise UtilException("Cannot load YAML file %s, err: %s" % (filename, err))


# ----- Read configuration file ----------------------------------------------

conf = yaml_load(CONFIG_FILE)

log.setLevel(conf.log.level)

usb_modem = USB_modem()


class PlaySMS:
    """
    Handle communication to/from PlaySMS
    """
    def __init__(self):
        self.thread = threading.Thread(target=self.background_poller, args=())
        self.thread.daemon = True
        self.thread.start()

    
    def background_poller(self):
        """
        Separate thread, that periodically polls modem for new messages
        """
        while True:
            messages = usb_modem.list_received_sms()
            for message in messages:
                log.info("Received SMS index: %s  from: %s  message: %s" % (message.Index, message.Phone, message.Content))
                playsms.insert_sms_into_playsms(id=message.Index, from_=message.Phone, text=message.Content)
                usb_modem.delete_sms(message.Index)
            time.sleep(10)
            
    
    def insert_sms_into_playsms(self, id=None, from_=None, to=None, text=None):
#        http://10.10.80.129/playsms/plugin/gateway/generic/callback.php?
#        &from=0722060322&message=nisse&to=46705747187&smsc=generic

        data = AttrDict()
        data.id = id
        data.authcode = "fc5fc18a232c42cf17a5be44f5a018314422505d"
        data['from'] = from_        # from is a python reserved keyword
        data.message = text
        data.to = "+46705747187"
        data.smsc = 'generic'
        
        headers = {
            'Content-Type'    : 'application/x-www-form-urlencoded',
            'charset'        : 'UTF-8',
            'Accept'        : 'application/json',
            }
        
        url = "http://127.0.0.1/playsms/plugin/gateway/generic/callback.php?"
        r = requests.post(url, headers=headers, data=data, timeout=10)
        return r

#        url += urllib.parse.urlencode(data, encoding='utf-8')
#        url += urllib.parse.urlencode(data)
#        ret = requests.get(url=url).text
#        return ret
    
    def sms_from_playsms(self):
        pass


playsms = PlaySMS()


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
            index = usb_modem.send_sms(numbers=numbers, text=text)
            return self._return_json(200, "%s OK" % index)
                
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
