# playSMS Hilink driver

This driver interfaces playSMS with a Huawei E3372 USB modem in hilink mode.

Supports sending and receiving SMS

Developed and tested on a Intel NUC, with Ubuntu 16.04 server, 64-bit


## Installation

### Install dependcies

    sudo apt-get install python3-pip python3-yaml python3-xmltodict python3-requests
    sudo pip3 install orderedattrdict


### Create user for daemon

It is recommended to run this driver as a normal user. This user is only
used when running the driver as a daemon, no need to allow logins.

    sudo adduser hilink_driver

    # Disable/lock logins
    sudo passwd -l hilink_driver


### Checkout code

    cd /opt
    git clone https://github.com/lowinger42/playsms_hilink_driver.git


### Copy configuration

    sudo mkdir /etc/playsms_hilink_driver
    sudo cp /opt/playsms_hilink_driver/config_example.yaml /etc/playsms_hilink_driver/config.yaml

If needed, edit/update /etc/hilink_driver/config.yaml for your environment

It is important that the playsms-callback URL is correct.


### Install systemd service defintion

    sudo cp /opt/playsms_hilink_driver/playsms_hilink_driver.service /lib/systemd/system


### Enable and start service

    sudo systemctl daemon-reload
    sudo systemctl enable playsms_hilink_driver
    sudo systemctl start playsms_hilink_driver


### Configuration of playsms

A generic smsc needs to added, with the proper configuation, pointing to this script

Set generic send SMS URL to

http://127.0.0.1:8888/api/send_sms?user={GENERIC_API_USERNAME}&pwd={GENERIC_API_PASSWORD}&sender={GENERIC_SENDER}&msisdn={GENERIC_TO}&message={GENERIC_MESSAGE}


## Todo

- Support for PIN? Does it  need to be disabled?
- Do we need to delete outgoing SMSes from the modem? What happens when its full? (200 msgs)
