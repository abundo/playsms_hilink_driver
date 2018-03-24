#!/usr/bin/env python3
"""
Library to communicate with a Huawei E3372 USB modem in hilink mode.

Supports sending and receiving SMS

When sending a SMS, the modem does not return any Task ID. We therefore 


Send Task:
- Get Tasks in outbox, delete until empty
- send Task
- wait until Task is in outbox
- get Task from outbox, with Task ID
- delete Task in outbox
- timeout 10 sek

Separate process, handling all communication with modem. Uses a queue
for serialisation of Tasks. This ensures only one transaction is 
in progress with the USB modem.

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
import logging
import logging.handlers
import urllib.parse
import xmltodict
import requests
import argparse
import multiprocessing

from orderedattrdict import AttrDict

from lib_log import log

# ----- start of configuration ------------------------------------------------

BASE_URL = 'http://192.168.8.1'
COOKIE_URL = '/html/index.html'

# ----- Helper functions -----------------------------------------------------

datetime_str_format = "%Y-%m-%d %H:%M:%S"


def now_dt():
    return datetime.datetime.now().replace(microsecond=0)


def now_str():
    return now_dt().strftime(datetime_str_format)


class Task:
    def __init__(self, action=None):
        self.action = action


class USB_modem:
    """
    Manage the USB modem via hilink
    
    Starts a background process, which does all communication with the  modem.
    This serializes all communication with the modem
    """

    def __init__(self):
        self.session = requests.Session()
        
        self.task_queue = multiprocessing.Queue()       # Tasks to worker
        self.result_queue = multiprocessing.Queue()     # Tasks from worker
        self.p = multiprocessing.Process(target=self.background_worker, args=(self.task_queue, self.result_queue))
        self.p.start()

    # ----------------------------------------------------------------------
    # Here is all background process and helper functions
    # ----------------------------------------------------------------------

    def background_worker(self, task_queue, result_queue):
        """
        This method is running as a separate process
        """
        r = self.session.get(BASE_URL + COOKIE_URL)
        # except requests.exceptions.ConnectionError as err:
        
        while True:
            task = task_queue.get()
            
            res = Task(action='result')
            if task.action == 'list_received_sms':
                messages = self.b_get_sms_list()
                res.messages = messages
                self.result_queue.put(res)

            elif task.action == 'list_sent_sms':
                messages = self.b_get_sms_list(outbox=True)
                res.messages = messages
                self.result_queue.put(res)

            elif task.action == 'send_sms':
    
                # delete any lingering SMS in outbox
                while True:
                    messages = self.b_get_sms_list(outbox=True)
                    if len(messages):
                        for message in messages:
                            self.b_delete_sms(message.Index)
                    else:
                        break

                # send SMS
                res.index = -1
                self.b_send_sms(numbers=task.numbers, text=task.text)
                
                # list SMS in outbox.
                # It takes some time until the sent message is visible
                # in the outbox. Wait for it
                for i in range(0,5):
                    time.sleep(1)
                    messages = self.b_get_sms_list(outbox=True)
                    
                if len(messages):
                    res.index = messages[0].Index
                    if len(messages) > 1:
                        log.warning("After SMS sent, more than one message in outbox")
                        
                    # delete sms in outbox
                    self.b_delete_sms(res.index)
                else:
                    log.error("Sent SMS was not stored in outbox")

                self.result_queue.put(res)

            elif task.action == 'receive_sms':
                self.result_queue.put(res)

            elif task.action == 'delete_sms':
                index = task.index
                r = self.b_delete_sms(index)
                self.result_queue.put(res)
            
            elif task.action == 'stop':
                print("Ending background process")
                self.result_queue.put(res)
                return  # this quits the background process

            else:
                print("Unknown task: %s" % task.action)


    def b_get_session(self):
        """
        All communication with the USB modem needs a valid session
        """
        session_token = xmltodict.parse(self.session.get(BASE_URL +\
            "/api/webserver/SesTokInfo").text).get('response',None)
        session = session_token.get("SesInfo")  #cookie
        token = session_token.get("TokInfo")    #token
        return session, token


    def b_get_sms_list(self, outbox=False):
        """
        Return a list with up to 10 received SMSes
        """
        session, token = self.b_get_session()
        headers = {
            'Cookie': session, 
            '__RequestVerificationToken': token, 
            'charset'        : 'UTF-8',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            }

        if outbox:
            boxtype = '2'
        else:
            boxtype = '1'

        api_url = BASE_URL + "/api/sms/sms-list"
        post_data =  b""
        post_data += b'<?xml version="1.0" encoding="UTF-8"?>\n'
        post_data += b"<request>\n"
        post_data += b"  <PageIndex>1</PageIndex>\n"
        post_data += b"  <ReadCount>10</ReadCount>\n"
        post_data += b"  <BoxType>%s</BoxType>" % boxtype.encode()
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
                        if msg['Content'] is None:
                            msg['Content'] = ' '
                        msg['Content'] = msg['Content'].encode('latin1').decode('utf8', 'ignore')
                        ret_messages.append(msg)
                        print(msg)

        return ret_messages


    def b_delete_sms(self, index):
        """
        Delete a SMS from the modem.
        """
        log.info("Delete SMS with index %s" % index)
        session, token = self.b_get_session()
        headers = {
            'Cookie': session, 
            '__RequestVerificationToken': token, 
            }
        api_url = BASE_URL + "/api/sms/delete-sms"
        post_data = b""
        post_data += b'<?xml version="1.0" encoding="UTF-8"?>\n'
        post_data += b"<request>\n"
        post_data += b"  <Index>%s</Index>\n" % str(index).encode()
        post_data += b"</request>\n"
        ret = self.session.post(url=api_url, data=post_data, headers=headers).text
        data = xmltodict.parse(ret)
        return data


    def b_send_sms(self, numbers=None, text=None):
        log.info("Sending SMS, numbers: %s  Text: %s" % ( ",".join(numbers), text))
        session, token = self.b_get_session()
        api_url = BASE_URL + "/api/sms/send-sms"
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
        post_data += b"  <Length>%s</Length>\n" % length.encode()
        post_data += b"  <Reserved>1</Reserved>\n"
        post_data += b"  <Date>%s</Date>\n" % now_str().encode()
        post_data += b"</request>\n"
        
        ret = self.session.post(url=api_url, data=post_data, headers=headers).text
        return xmltodict.parse(ret)


    # ----------------------------------------------------------------------
    # End of background process and helper functions
    # ----------------------------------------------------------------------


    def list_received_sms(self):
        m = Task(action='list_received_sms')
        self.task_queue.put(m)
        task = self.result_queue.get()
        return task.messages
    

    def list_sent_sms(self):
        t = Task(action='list_sent_sms')
        self.task_queue.put(t)
        task = self.result_queue.get()
        return task.messages


    def send_sms(self, numbers, text):
        t = Task(action='send_sms')
        t.numbers = numbers
        t.text = text
        self.task_queue.put(t)
        task = self.result_queue.get()
        return task.index


    def receive_sms(self, index):
        t = Task(action='receive_sms')
        t.index = index
        self.task_queue.put(t)
        task = self.result_queue.get()
    

    def delete_sms(self, index):
        t = Task(action='delete_sms')
        t.index = index
        self.task_queue.put(t)
        task = self.result_queue.get()
        # return task.status


    def stop(self):
        t = Task(action='stop')
        self.task_queue.put(t)


def main():
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--cmd",
                        required=True,
                        choices = ['list_received_sms',
                                   'list_sent_sms',
                                   'send_sms',
                                   'receive_sms',
                                   'delete_sms',
                                   ])
    parser.add_argument("--number")
    parser.add_argument("--text")
    parser.add_argument("--index", type=int, default=None)

    args = parser.parse_args()

    usb_modem = USB_modem()
    
    if args.cmd == 'list_received_sms':
        messages = usb_modem.list_received_sms()
        if len(messages):
            for message in messages:
                print(message)
        else:
            print("No messages received")

    elif args.cmd == 'list_sent_sms':
        messages = usb_modem.list_sent_sms()
        if len(messages):
            for message in messages:
                print(message)
        else:
            print("No messages received")

    elif args.cmd == 'send_sms':
        if not args.number:
            print("Please specify number")
            sys.exit(1)
        if not args.text:
            print("Please specify text to be sent")
            sys.exit(1)

        index = usb_modem.send_sms([args.number], args.text)
        print("index %s" % index)

    elif args.cmd == 'receive_sms':
        pass
    
    elif args.cmd == 'delete_sms':
        if not args.index:
            print('Please specify index')
            sys.exit(1)
        usb_modem.delete_sms(args.index)
    
    else:
        print("Error: Unknown command %s" % args.cmd)
        sys.exit(1)
    
    usb_modem.stop()


if __name__ == "__main__":
    main()
